#!/usr/bin/env python3
"""Measure the XIAO round display holder against the Braccio wrist and gripper.

The holder (hardware/pencil-grip/braccio_wrist_xiao_round_display.scad) fits
two ways, by the hub screws or by cable ties round the wrist. This exports it
from OpenSCAD in both poses, places the reference geometry round it with the
joint frames of sim/gazebo/urdf/braccio_sketchbot.urdf.xacro, and reports the
smallest gap to each neighbour over the joint ranges:

    python scripts/check_xiao_holder.py
    python scripts/check_xiao_holder.py --pick-distance 90 120 180 --json

Reference geometry:

  * hardware/braccio-arm: braccio_wrist_pitch.stl, braccio_wrist_roll.stl,
    braccio_elbow.stl and the two gripper meshes, the ones the URDF loads
    (GPL-3.0, see that folder). --meshes points at another copy.
  * hardware/pencil-grip/braccio_pen_finger_8mm.stl, placed where the URDF's
    pen_link puts it.

Needs numpy and manifold3d, and OpenSCAD on the PATH (or --openscad). It is a
bench tool, not part of the test suite: the suite checks the exported meshes
with scripts/mesh_check.py and needs neither.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.mesh_check import _weld, load_stl  # noqa: E402

PARTS = REPO / "hardware" / "pencil-grip"
SOURCE = PARTS / "braccio_wrist_xiao_round_display.scad"
MESH_DIRS = [REPO / "hardware" / "braccio-arm"]

# Joint limits, radians, from the URDF.
ROLL_RANGE = (-math.pi / 2, math.pi / 2)
PITCH_RANGE = (-math.pi / 2, math.pi / 2)
GRIP_RANGE = (0.1750, 1.2741)       # 0.1750 open, 1.2741 closed
SEARCH_MM = 60.0                    # gaps wider than this are reported as such
HUB_RADIUS_MM = 12.0


def rot(axis, angle):
    x, y, z = np.asarray(axis, float) / np.linalg.norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    k = 1 - c
    m = np.eye(4)
    m[:3, :3] = [[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
                 [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
                 [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]
    return m


def shift(x, y, z):
    m = np.eye(4)
    m[:3, 3] = [x, y, z]
    return m


def rpy(roll, pitch, yaw):
    return rot((0, 0, 1), yaw) @ rot((0, 1, 0), pitch) @ rot((1, 0, 0), roll)


# Everything below is expressed in wrist_roll_link, in millimetres.
def gripper_base():
    return shift(6, 0, 0)


def right_finger(q):
    return (shift(10, 0, 30) @ rpy(0, -0.2967, 0) @ rot((0, -1, 0), q)
            @ shift(0, -12, 10) @ rpy(0, math.pi / 2, 0))


def left_finger(q):
    return (shift(-10, 0, 30) @ rpy(0, 3.4383, 0) @ rot((0, 1, 0), q)
            @ shift(0, -12, 0) @ rpy(0, math.pi / 2, 0))


def pen_finger():
    return shift(-16.5, 14.175, 30) @ rpy(math.pi, 0, 0)


def roll_in_pitch(roll):
    """wrist_rotation: wrist_roll_link in wrist_pitch_link."""
    return shift(0, 0, 60) @ rpy(0, 0, math.pi / 2) @ rot((0, 0, -1), roll)


def wrist_body(roll):
    return np.linalg.inv(roll_in_pitch(roll)) @ shift(3, -0.4, -24)


def forearm(roll, pitch):
    pitch_in_elbow = shift(0, 0, 125) @ rot((1, 0, 0), pitch)
    return (np.linalg.inv(roll_in_pitch(roll)) @ np.linalg.inv(pitch_in_elbow)
            @ shift(-4.5, 5, -25))


def load(path):
    import manifold3d as m3
    tris, _ = load_stl(path)
    verts, faces = _weld(tris)
    solid = m3.Manifold(m3.Mesh(vert_properties=np.asarray(verts, np.float32),
                                tri_verts=np.asarray(faces, np.uint32)))
    if solid.status() != m3.Error.NoError:
        raise SystemExit(f"{path}: not a closed solid ({solid.status()})")
    return solid


def moved(solid, matrix):
    return solid.transform(np.asarray(matrix[:3, :], dtype=np.float64))


def gap(a, b):
    """Smallest distance between two solids; negative if they overlap."""
    overlap = (a ^ b).volume()
    if overlap > 1e-3:
        return -overlap ** (1.0 / 3.0)
    return float(a.min_gap(b, SEARCH_MM))


def triangles(solid):
    mesh = solid.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3].astype(float)
    return verts[np.asarray(mesh.tri_verts)]


def ray_blocked(origin, target, tris):
    """Does the segment origin -> target cross any triangle?"""
    direction = target - origin
    e1 = tris[:, 1] - tris[:, 0]
    e2 = tris[:, 2] - tris[:, 0]
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    t0 = origin - tris[:, 0]
    u = np.einsum("ij,ij->i", t0, p) * inv
    q = np.cross(t0, e1)
    v = np.einsum("j,ij->i", direction, q) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6) & (t < 1 - 1e-6)
    return bool(hit.any())


def export(openscad, workdir, pick, part, pose):
    out = Path(workdir) / f"{part}_{pose}_{pick}.stl"
    result = subprocess.run(
        [openscad, "-o", str(out), "-D", f"pick_distance={pick}",
         "-D", f'part="{part}"', "-D", f'pose="{pose}"', str(SOURCE)],
        capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        raise SystemExit(f"OpenSCAD failed:\n{result.stderr}")
    found = re.search(r'ECHO: "xiao_holder (\{.*\})"',
                      result.stdout + result.stderr)
    if not found:
        raise SystemExit("the part did not report its geometry")
    return load(out), json.loads(found.group(1))


def tie_band(z, half_width, body_lo, body_hi, tunnel_y, thick=1.5):
    """A cable tie as a closed band round the wrist body and through a tunnel."""
    import manifold3d as m3
    x0, y0 = body_lo
    x1 = body_hi[0]
    inner = m3.Manifold.cube([x1 - x0, tunnel_y - y0, 2 * half_width])
    outer = m3.Manifold.cube([x1 - x0 + 2 * thick, tunnel_y - y0 + 2 * thick,
                              2 * half_width])
    return (outer.translate([x0 - thick, y0 - thick, z - half_width])
            - inner.translate([x0, y0, z - half_width]))


def sweep(values, steps):
    lo, hi = values
    return [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]


def check(openscad, meshes, pick, workdir):
    import manifold3d as m3

    ref = {name: load(meshes / f"braccio_{name}.stl")
           for name in ("wrist_pitch", "wrist_roll", "elbow",
                        "left_gripper", "right_gripper")}
    pen = moved(load(PARTS / "braccio_pen_finger_8mm.stl"), pen_finger())
    base = moved(ref["wrist_roll"], gripper_base())
    grips = sweep(GRIP_RANGE, 6)
    rolls = sweep(ROLL_RANGE, 37)
    pitches = sweep(PITCH_RANGE, 7)

    def fingers(q):
        return (moved(ref["right_gripper"], right_finger(q))
                + moved(ref["left_gripper"], left_finger(q)))

    report = {}
    holder_s, info = export(openscad, workdir, pick, "holder", "screw")
    boards_s, _ = export(openscad, workdir, pick, "electronics", "screw")
    holder_t, _ = export(openscad, workdir, pick, "holder", "tie")
    boards_t, _ = export(openscad, workdir, pick, "electronics", "tie")
    report["geometry"] = info
    target = np.array(info["target"], float)

    # ---- fitted by the hub: the holder turns with the gripper ------------
    hub = m3.Manifold.cylinder(400, HUB_RADIUS_MM + 0.5, HUB_RADIUS_MM + 0.5,
                               64).translate([0, 0, -200])
    clear_of_hub = holder_s - hub
    screw = {}
    screw["gripper base, outside the hub"] = gap(clear_of_hub, base)
    screw["fingers, open to closed"] = min(
        min(gap(holder_s, fingers(q)), gap(boards_s, fingers(q)))
        for q in grips)
    screw["pen finger, as the URDF places it"] = min(
        gap(holder_s, pen), gap(boards_s, pen))
    screw["wrist body, roll -90..90"] = min(
        min(gap(holder_s, moved(ref["wrist_pitch"], wrist_body(r))),
            gap(boards_s, moved(ref["wrist_pitch"], wrist_body(r))))
        for r in rolls)
    screw["wrist body, outside the hub"] = min(
        gap(clear_of_hub, moved(ref["wrist_pitch"], wrist_body(r)))
        for r in rolls)
    screw["forearm, roll and wrist pitch -90..90"] = min(
        min(gap(holder_s, moved(ref["elbow"], forearm(r, p))),
            gap(boards_s, moved(ref["elbow"], forearm(r, p))))
        for r in rolls[::3] for p in pitches)
    lens = np.array(info["lens_screw"], float)
    blocked = [q for q in grips
               if ray_blocked(lens, target, triangles(fingers(q) + base + pen))]
    screw["line of sight to the pick point"] = (
        "clear" if not blocked else f"blocked at grip {blocked}")
    report["screws"] = screw

    # ---- fitted by the ties: the gripper rolls past the holder -----------
    # The reference wrist body is 1.1 mm off the roll axis across the cheek;
    # the saddle goes where the body is. It is stood 0.05 mm off the cheek so
    # that the two touching faces do not count as an overlap.
    body = moved(ref["wrist_pitch"], wrist_body(0.0))
    lo, hi = body.bounding_box()[:3], body.bounding_box()[3:]
    seat = shift((-16.4 + 18.6) / 2, 0.05, 0)
    holder_t = moved(holder_t, seat)
    boards_t = moved(boards_t, seat)
    tie = {}
    tie["wrist body, overlap volume mm3"] = str(
        round((holder_t ^ body).volume(), 3))
    tie["wrist body, electronics"] = gap(boards_t, body)

    def rolled(solid, r):
        return moved(solid, rot((0, 0, 1), r))

    moving = [(r, q, rolled(base + fingers(q), r)) for r in rolls for q in grips]
    tie["gripper base and fingers, roll -90..90"] = min(
        gap(holder_t, solid) for _, _, solid in moving)
    tie["gripper base and fingers, electronics"] = min(
        gap(boards_t, solid) for _, _, solid in moving)
    tunnel_y = 29.0 + 3.0 + info["tie_tunnel"][1]
    bands = [tie_band(z, 1.8, (-16.4, -26.0), (18.6, 29.0), tunnel_y)
             for z in info["tie_z"]]
    tie["ties, to anything that rolls"] = min(
        gap(band, solid) for band in bands for _, _, solid in moving[::6])
    tie["ties, below the roll joint plane"] = -(max(info["tie_z"]) + 1.8)
    tie["forearm, wrist pitch -90..90"] = min(
        min(gap(holder_t, moved(ref["elbow"], forearm(0.0, p))),
            gap(boards_t, moved(ref["elbow"], forearm(0.0, p))))
        for p in sweep(PITCH_RANGE, 19))
    lens = np.array(info["lens_tie"], float) + seat[:3, 3]
    clear = [math.degrees(r) for r in rolls
             if not any(ray_blocked(lens, target, triangles(solid))
                        for rr, _, solid in moving if rr == r)]
    tie["line of sight clear at roll, degrees"] = (
        [round(min(clear)), round(max(clear))] if clear else "never")
    tie["line of sight, rolls checked clear"] = f"{len(clear)} of {len(rolls)}"
    report["ties"] = tie

    # ---- what the camera sees of the holder itself ----------------------
    axis = np.array(info["axis"], float)
    verts = triangles(holder_s).reshape(-1, 3) - np.array(info["lens_screw"])
    ahead = verts[verts @ axis > 0.5]
    if len(ahead):
        angles = np.degrees(np.arccos(
            (ahead @ axis) / np.linalg.norm(ahead, axis=1)))
        report["holder in view"] = {
            "nearest part of the holder off the optical axis, degrees":
                round(float(angles.min()), 1),
            "half field of view, degrees": info["fov_deg"] / 2,
        }
    else:
        report["holder in view"] = "no part of the holder is ahead of the lens"
    return report


def find_openscad(given):
    import shutil
    candidates = [given, "openscad", "openscad.com",
                  "C:/Program Files/OpenSCAD/openscad.com",
                  "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"]
    for candidate in candidates:
        if candidate and (shutil.which(candidate) or Path(candidate).exists()):
            return candidate
    raise SystemExit("OpenSCAD not found; pass --openscad")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--meshes", type=Path, default=None,
                        help="folder holding the Braccio reference STLs")
    parser.add_argument("--openscad", default=None)
    parser.add_argument("--pick-distance", type=float, nargs="+",
                        default=[90, 120, 180])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    meshes = args.meshes or next((d for d in MESH_DIRS if d.is_dir()), None)
    if meshes is None:
        raise SystemExit("reference meshes not found; pass --meshes")
    openscad = find_openscad(args.openscad)

    failed = False
    reports = {}
    with tempfile.TemporaryDirectory() as workdir:
        for pick in args.pick_distance:
            pick = int(pick) if float(pick).is_integer() else pick
            report = check(openscad, meshes, pick, workdir)
            reports[str(pick)] = report
            for fit in ("screws", "ties"):
                for name, value in report[fit].items():
                    if isinstance(value, float) and value < 0:
                        failed = True
            if float(report["ties"]["wrist body, overlap volume mm3"]) > 1.0:
                failed = True
    if args.json:
        print(json.dumps(reports, indent=2))
        return 1 if failed else 0

    for pick, report in reports.items():
        info = report["geometry"]
        print(f"pick distance {pick} mm: tilt {info['tilt_deg']:.1f} deg, "
              f"tie slide {info['tie_slide']:.1f} mm")
        for fit in ("screws", "ties"):
            print(f"  fitted by the {fit}")
            for name, value in report[fit].items():
                shown = (f">{SEARCH_MM:.0f} mm" if value == SEARCH_MM
                         else f"{value:.1f} mm") if isinstance(value, float) \
                    else value
                print(f"    {name:<44} {shown}")
        print(f"  holder in view: {report['holder in view']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
