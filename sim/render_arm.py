"""Render the real Braccio (the unoq_braccio_sim STL meshes) posed by the
sketchbot's drawing commands.

Gazebo needs Linux + a display, so this is a headless stand-in that loads the
*exact same* URDF kinematics and meshes the Gazebo model uses
(``unoq_braccio_sim``) and poses them with the sketchbot's servo commands via
the *same* servo->radian mapping as the ROS ``joint_trajectory_bridge``. It
proves the sketchbot drives the real arm structure, and produces the teaching
figure in the README.

    python -m sim.render_arm --image examples/sample_face_eoin.png \
        --style none --out docs/images/gazebo_caricature.png

The STL meshes live in the sibling ``unoq-braccio`` repo (GPL-3.0, not vendored
here); point --meshes at them if they are not in the default location.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

import cv2
import numpy as np

from sketch_artist import config as cfg
from sketch_artist.planner import plan
from sketch_artist.portrait import to_line_art
from sketch_artist.scenes import compose, resolve_style
from sketch_artist.vectorize import strokes_from_edges

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MESHES = REPO.parent / "unoq-braccio" / "ros2_ws" / "src" / \
    "unoq_braccio_sim" / "meshes" / "braccio_stedden"

# URDF joint chain, transcribed from unoq_braccio_sim/urdf/braccio.urdf.xacro.
# Each entry: (joint_name, parent_link, child_link, xyz, rpy, axis, servo_index)
CHAIN = [
    ("base_fixed", "world", "base_link", (0, 0, 0.02), (0, 0, 0), None, None),
    ("base", "base_link", "braccio_base_link", (0, 0, 0.01), (0, 0, 0), (0, 0, 1), 0),
    ("shoulder", "braccio_base_link", "shoulder_link", (0, -0.002, 0.072), (-1.5708, 0, 0), (1, 0, 0), 1),
    ("elbow", "shoulder_link", "elbow_link", (0, 0, 0.125), (-1.5708, 0, 0), (1, 0, 0), 2),
    ("wrist_vertical", "elbow_link", "wrist_pitch_link", (0, 0, 0.125), (-1.5708, 0, 0), (1, 0, 0), 3),
    ("wrist_rotation", "wrist_pitch_link", "wrist_roll_link", (0, 0, 0.06), (0, 0, 1.5708), (0, 0, -1), 4),
    ("gripper", "wrist_roll_link", "right_gripper_link", (0.010, 0, 0.03), (0, -0.2967, 0), (0, -1, 0), 5),
    ("left_gripper_mimic", "wrist_roll_link", "left_gripper_link", (-0.010, 0, 0.03), (0, 3.4383, 0), (0, 1, 0), 5),
]

# Per-link mesh visual origin (xyz, rpy), scale 0.001 (mm -> m).
MESHES = {
    "braccio_base_link": ("braccio_base.stl", (0, 0.004, 0), (0, 0, 3.1416)),
    "shoulder_link": ("braccio_shoulder.stl", (-0.0045, 0.0055, -0.026), (0, 0, 0)),
    "elbow_link": ("braccio_elbow.stl", (-0.0045, 0.005, -0.025), (0, 0, 0)),
    "wrist_pitch_link": ("braccio_wrist_pitch.stl", (0.003, -0.0004, -0.024), (0, 0, 0)),
    "wrist_roll_link": ("braccio_wrist_roll.stl", (0.006, 0, 0), (0, 0, 0)),
    "right_gripper_link": ("braccio_right_gripper.stl", (0, -0.012, 0.010), (0, 1.5708, 0)),
    "left_gripper_link": ("braccio_left_gripper.stl", (0, -0.012, 0), (0, 1.5708, 0)),
}


def _rpy(r: float, p: float, y: float) -> np.ndarray:
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def _T(xyz, rpy=(0, 0, 0), R=None) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = R if R is not None else _rpy(*rpy)
    m[:3, 3] = xyz
    return m


def _axis_R(axis, angle: float) -> np.ndarray:
    a = np.array(axis, float)
    a = a / np.linalg.norm(a)
    x, y, z = a
    c, s, C = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def servo_to_radians(servo6) -> dict:
    """Real unoq_braccio_sim mapping (joint_trajectory_bridge)."""
    out = {}
    names = ["base", "shoulder", "elbow", "wrist_vertical", "wrist_rotation", "gripper"]
    for name, deg in zip(names, servo6):
        if name == "gripper":
            out[name] = 0.1750 + max(0.0, min(1.0, (deg - 10.0) / 100.0)) * (1.2741 - 0.1750)
        else:
            out[name] = math.radians(deg - 90.0)
    return out


def link_transforms(joint_rad: dict) -> dict:
    """Forward kinematics: world transform for every link."""
    T = {"world": np.eye(4)}
    for name, parent, child, xyz, rpy, axis, _idx in CHAIN:
        origin = _T(xyz, rpy)
        if axis is not None:
            origin = origin @ _T((0, 0, 0), R=_axis_R(axis, joint_rad.get(name, 0.0)))
        T[child] = T[parent] @ origin
    return T


def load_meshes(mesh_dir: Path, decimate: int):
    import trimesh
    meshes = {}
    for link, (fname, vxyz, vrpy) in MESHES.items():
        path = mesh_dir / fname
        m = trimesh.load(str(path), process=False)
        m.apply_scale(0.001)
        m.apply_transform(_T(vxyz, vrpy))
        if decimate and len(m.faces) > decimate:
            try:
                m = m.simplify_quadric_decimation(decimate)
            except Exception:
                pass
        meshes[link] = (m.vertices.copy(), m.faces.copy())
    return meshes


def pen_tip(T: dict) -> np.ndarray:
    """Approximate pen/gripper tip in world coords (end of the gripper)."""
    return (T["right_gripper_link"] @ np.array([0.075, -0.012, 0.01, 1.0]))[:3]


def _shade(verts, faces, base_rgb, light=(0.3, 0.4, 1.0)):
    tris = verts[faces]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    l = np.array(light, float)
    l = l / np.linalg.norm(l)
    shade = 0.35 + 0.65 * np.clip(n @ l, 0, 1)
    return tris, np.clip(np.array(base_rgb)[None, :] * shade[:, None], 0, 1)


def _ik(target, seed=(90.0, 130.0, 90.0, 110.0)):
    """Servo (base, shoulder, elbow, wrist_vertical) that puts the pen tip at
    ``target`` (metres) with the pen pointing down. Numerical IK on the FK
    above, so the real arm actually reaches each drawing point."""
    from scipy.optimize import least_squares

    def residual(s):
        T = link_transforms(servo_to_radians((s[0], s[1], s[2], s[3], 90, 90)))
        tip = pen_tip(T)
        wr = T["wrist_roll_link"][:3, 3]
        d = tip - wr
        d = d / (np.linalg.norm(d) + 1e-9)
        return [tip[0] - target[0], tip[1] - target[1], tip[2] - target[2],
                2.0 * d[0], 2.0 * d[1], 1.5 * (d[2] + 1.0)]

    r = least_squares(residual, list(seed),
                      bounds=([0, 15, 0, 0], [180, 165, 180, 180]), max_nfev=300)
    return r.x


def _table_target(x_mm, y_mm, paper):
    """Map a paper-mm point onto a reachable patch of the arm's table (metres).

    The arm reaches forward along +Y, so paper 'away from base' (x) maps to
    forward Y, paper left-right (y) maps to X, on a table just below the base.
    """
    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])
    fy = 0.15 + (x_mm - ox) / w * 0.095
    fx = -((y_mm - oy) / h - 0.5) * 0.11
    return np.array([fx, fy, -0.008])


def render(polylines, corners, meshes, out_path: str, frames: int):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    flat = np.concatenate(polylines) if polylines else np.zeros((1, 3))
    orange = (0.95, 0.35, 0.05)
    white = (0.86, 0.86, 0.82)
    colors = {"braccio_base_link": orange, "shoulder_link": orange,
              "elbow_link": orange, "wrist_pitch_link": orange,
              "wrist_roll_link": white, "right_gripper_link": white,
              "left_gripper_link": white}

    cols = 2 if frames > 1 else 1
    rows = int(np.ceil(frames / cols))
    fig = plt.figure(figsize=(6.0 * cols, 6.0 * rows))
    seed = (90.0, 130.0, 90.0, 110.0)

    for k in range(frames):
        frac = (k + 1) / frames
        n = max(2, int(round(frac * len(flat))))
        servo = _ik(flat[n - 1], seed)
        seed = servo
        T = link_transforms(servo_to_radians((servo[0], servo[1], servo[2], servo[3], 90, 90)))

        ax = fig.add_subplot(rows, cols, k + 1, projection="3d")
        for link, (verts, faces) in meshes.items():
            vh = np.c_[verts, np.ones(len(verts))] @ T[link].T
            tris, facecolors = _shade(vh[:, :3], faces, colors[link])
            ax.add_collection3d(Poly3DCollection(tris, facecolors=facecolors,
                                                 edgecolors="none", linewidths=0))
        # Paper outline on the table.
        ax.plot(corners[:, 0], corners[:, 1], corners[:, 2], color="#c0c0c0", linewidth=1)
        # Caricature drawn so far (stroke by stroke, up to n points).
        drawn = 0
        for pl in polylines:
            if drawn >= n:
                break
            take = min(len(pl), n - drawn)
            if take >= 2:
                ax.plot(pl[:take, 0], pl[:take, 1], pl[:take, 2],
                        color="#0b1221", linewidth=1.7)
            drawn += len(pl)
        tip = pen_tip(T)
        ax.scatter([tip[0]], [tip[1]], [tip[2]], color="#e2483d", s=22)

        ax.set_xlim(-0.14, 0.14)
        ax.set_ylim(-0.02, 0.28)
        ax.set_zlim(-0.05, 0.29)
        ax.set_box_aspect((0.28, 0.30, 0.34))
        ax.view_init(elev=30, azim=-82)
        ax.set_axis_off()
        ax.set_title(f"drawing {int(frac * 100)}%", fontsize=11)

    fig.suptitle("Braccio (unoq_braccio_sim STL model) drawing the sketchbot caricature",
                 fontsize=13)
    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110, facecolor="white")
    print(f"Wrote {out_path}  ({len(flat)} points, {len(polylines)} strokes)")


def build_scene(image: str, style: str):
    conf = cfg.load_all()
    frame = cv2.imread(str(cfg.resolve_path(image)))
    if frame is None:
        raise SystemExit(f"Could not read image: {image}")
    edges = to_line_art(frame, conf["drawing"])
    strokes = strokes_from_edges(edges, conf["drawing"])
    canvas = int(conf["drawing"].get("capture", {}).get("target_px", 512))
    chosen = resolve_style(conf["scenes"], style, interactive=False)
    strokes = compose(strokes, chosen, conf["scenes"], canvas)
    moves = plan(strokes, conf["workspace"])
    paper = conf["workspace"]["paper"]

    polylines, cur = [], []
    for m in moves:
        if m.pen_down:
            cur.append(_table_target(m.x_mm, m.y_mm, paper))
        elif cur:
            polylines.append(np.array(cur))
            cur = []
    if cur:
        polylines.append(np.array(cur))

    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])
    corners = np.array([_table_target(x, y, paper) for x, y in
                        [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h), (ox, oy)]])
    return polylines, corners


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render the real Braccio drawing the caricature.")
    p.add_argument("--image", default="examples/sample_face_eoin.png")
    p.add_argument("--style", default="none")
    p.add_argument("--meshes", default=str(DEFAULT_MESHES))
    p.add_argument("--out", default="docs/images/gazebo_caricature.png")
    p.add_argument("--frames", type=int, default=4)
    p.add_argument("--decimate", type=int, default=1200)
    args = p.parse_args(argv)

    mesh_dir = Path(args.meshes)
    if not mesh_dir.exists():
        raise SystemExit(
            f"Braccio meshes not found at {mesh_dir}.\n"
            "Clone the unoq-braccio repo next to this one, or pass --meshes.")

    polylines, corners = build_scene(args.image, args.style)
    meshes = load_meshes(mesh_dir, args.decimate)
    render(polylines, corners, meshes, str(cfg.resolve_path(args.out)), args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
