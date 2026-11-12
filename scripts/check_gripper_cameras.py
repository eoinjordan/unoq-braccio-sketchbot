#!/usr/bin/env python3
"""Measure the gripper-top camera holders against the Braccio reference model.

The two holders (hardware/pencil-grip/braccio_gripper_xiao_round_display.scad
and braccio_gripper_esp_eye.scad) sit on top of the gripper block and look
forward along the fingers. This exports each from OpenSCAD where it sits,
places the reference geometry round it with the joint frames of
sim/gazebo/urdf/braccio_sketchbot.urdf.xacro, and reports the smallest gap to
each neighbour over the joint ranges, and how much of the camera's view the
claws cover:

    python scripts/check_gripper_cameras.py
    python scripts/check_gripper_cameras.py --pick-distance 120 --json

Reference geometry:

  * hardware/braccio-arm: braccio_wrist_pitch.stl, braccio_wrist_roll.stl,
    braccio_elbow.stl and the two gripper meshes, the ones the URDF loads
    (GPL-3.0, see that folder). --meshes points at another copy.
  * hardware/pencil-grip/braccio_pen_finger_8mm.stl, placed where the URDF's
    pen_link puts it, and again on the other face of the gripper.

The reference draws the gripper block as a 4.5 mm plate and the fingers as two
flat blades. It has no gripper servo, horn or lead, so nothing here can speak
for those: the holders keep clear of the hole in the plate where the servo
goes, and that is all.

Needs numpy and manifold3d, and OpenSCAD on the PATH (or --openscad). It is a
bench tool, not part of the test suite.
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
HOLDERS = {
    "xiao_round_display": PARTS / "braccio_gripper_xiao_round_display.scad",
    "esp_eye": PARTS / "braccio_gripper_esp_eye.scad",
}
MESH_DIRS = [REPO / "hardware" / "braccio-arm"]

# Joint limits, radians, from the URDF.
ROLL_RANGE = (-math.pi / 2, math.pi / 2)
PITCH_RANGE = (-math.pi / 2, math.pi / 2)
GRIP_RANGE = (0.1750, 1.2741)       # 0.1750 open, 1.2741 closed
SEARCH_MM = 80.0                    # gaps wider than this are reported as such
ASPECT = (4, 3)                     # sensor shape assumed for the view


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


def other_face(block_mid_y):
    """Mirror in the gripper block's mid-plane: the same thing on the face
    the holder is not on."""
    m = np.eye(4)
    m[1, 1] = -1
    m[1, 3] = 2 * block_mid_y
    return m


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


def rays_hit(origin, directions, tris):
    """For each direction from origin, does the ray meet any triangle?"""
    e1 = tris[:, 1] - tris[:, 0]
    e2 = tris[:, 2] - tris[:, 0]
    t0 = origin - tris[:, 0]
    q = np.cross(t0, e1)
    hits = np.zeros(len(directions), dtype=bool)
    for i, d in enumerate(directions):
        p = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        u = np.einsum("ij,ij->i", t0, p) * inv
        v = (q @ d) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hits[i] = bool((ok & (u >= 0) & (v >= 0) & (u + v <= 1)
                        & (t > 1e-6)).any())
    return hits


def view_rays(axis, fov_deg, columns=64, rows=48):
    """Ray directions over a 4:3 picture whose diagonal spans fov_deg."""
    axis = np.asarray(axis, float)
    right = np.array([1.0, 0.0, 0.0])
    up = np.cross(axis, right)
    diagonal = math.tan(math.radians(fov_deg) / 2)
    half_w = diagonal * ASPECT[0] / math.hypot(*ASPECT)
    half_h = diagonal * ASPECT[1] / math.hypot(*ASPECT)
    xs = (np.arange(columns) + 0.5) / columns * 2 - 1
    ys = (np.arange(rows) + 0.5) / rows * 2 - 1
    return np.array([axis + x * half_w * right + y * half_h * up
                     for y in ys for x in xs])


def export(openscad, workdir, name, pick, part):
    out = Path(workdir) / f"{name}_{part}_{pick}.stl"
    result = subprocess.run(
        [openscad, "-o", str(out), "-D", f"pick_distance={pick}",
         "-D", f'part="{part}"', "-D", 'pose="gripper"', str(HOLDERS[name])],
        capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        raise SystemExit(f"OpenSCAD failed:\n{result.stderr}")
    found = re.search(r'ECHO: "gripper_camera (\{.*\})"',
                      result.stdout + result.stderr)
    if not found:
        raise SystemExit("the part did not report its geometry")
    return load(out), json.loads(found.group(1))


def tie_band(tie, info, thick=1.5, half_width=1.8):
    """A cable tie as a closed band: through the pad's tunnel, down the
    outside of the jaws and under the gripper block."""
    import manifold3d as m3
    cx, half0, ref_z, taper, top_y, block_t, jaw = info["block"]
    z = tie[0]
    half = half0 + taper * (z - ref_z) + jaw
    y0 = top_y - block_t
    y1 = tie[1] + info["tie_tunnel"][1]
    inner = m3.Manifold.cube([2 * half, y1 - y0, 2 * half_width])
    outer = m3.Manifold.cube([2 * half + 2 * thick, y1 - y0 + thick,
                              2 * half_width])
    return (outer.translate([cx - half - thick, y0 - thick, z - half_width])
            - inner.translate([cx - half, y0, z - half_width]))


def sweep(values, steps):
    lo, hi = values
    return [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]


def check(openscad, meshes, name, pick, workdir):
    ref = {part: load(meshes / f"braccio_{part}.stl")
           for part in ("wrist_pitch", "wrist_roll", "elbow",
                        "left_gripper", "right_gripper")}
    holder, info = export(openscad, workdir, name, pick, "holder")
    boards, _ = export(openscad, workdir, name, pick, "electronics")
    base = moved(ref["wrist_roll"], gripper_base())
    grips = sweep(GRIP_RANGE, 7)
    rolls = sweep(ROLL_RANGE, 13)
    pitches = sweep(PITCH_RANGE, 13)
    block_mid_y = info["block"][4] - info["block"][5] / 2

    def fingers(q):
        return (moved(ref["right_gripper"], right_finger(q))
                + moved(ref["left_gripper"], left_finger(q)))

    lens = np.array(info["lens"], float)
    target = np.array(info["target"], float)
    axis = np.array(info["axis"], float)
    report = {"geometry": {
        "tilt_deg": round(info["tilt_deg"], 2),
        "lens above the gripper centre line, mm": round(float(lens[1]), 1),
        "lens along the gripper from the finger mount, mm":
            round(float(lens[2]) - 30.0, 1),
        "lens to the pick point, mm":
            round(float(np.linalg.norm(target - lens)), 1),
    }}

    gaps = {}
    # The saddle touches the block by design. Stand it 0.05 mm off the face so
    # that two touching faces do not count as an overlap.
    seated = moved(holder, shift(0, 0.05, 0))
    gaps["gripper block, overlap volume mm3"] = str(
        round((seated ^ base).volume(), 3))
    gaps["fingers, open to closed: holder"] = min(
        gap(holder, fingers(q)) for q in grips)
    gaps["fingers, open to closed: boards and plug"] = min(
        gap(boards, fingers(q)) for q in grips)
    bands = [tie_band(tie, info) for tie in info["ties"]]
    gaps["fingers, open to closed: cable ties"] = min(
        gap(band, fingers(q)) for band in bands for q in grips)
    pen = moved(load(PARTS / "braccio_pen_finger_8mm.stl"), pen_finger())
    gaps["pen finger, where the URDF draws it"] = min(
        gap(holder, pen), gap(boards, pen))
    pen_far = moved(pen, other_face(block_mid_y))
    gaps["pen finger, on the other face of the gripper"] = min(
        gap(holder, pen_far), gap(boards, pen_far))
    gaps["wrist body, roll -90..90: holder"] = min(
        gap(holder, moved(ref["wrist_pitch"], wrist_body(r))) for r in rolls)
    gaps["wrist body, roll -90..90: boards and plug"] = min(
        gap(boards, moved(ref["wrist_pitch"], wrist_body(r))) for r in rolls)
    arm = [moved(ref["elbow"], forearm(r, p)) for r in rolls for p in pitches]
    gaps["forearm, roll and wrist pitch -90..90: holder"] = min(
        gap(holder, solid) for solid in arm)
    gaps["forearm, roll and wrist pitch -90..90: boards and plug"] = min(
        gap(boards, solid) for solid in arm)
    report["gaps"] = gaps

    # ---- what the camera sees -------------------------------------------
    rays = view_rays(axis, info["fov_deg"])
    centre = (target - lens)[None, :]
    view = {}
    for label, q in (("open", GRIP_RANGE[0]),
                     ("half open", sum(GRIP_RANGE) / 2),
                     ("closed", GRIP_RANGE[1])):
        claws = triangles(fingers(q))
        covered = rays_hit(lens, rays, claws)
        view[f"claws {label}: share of the picture covered"] = round(
            float(covered.mean()), 3)
        blocked = rays_hit(lens, centre, claws)[0]
        view[f"claws {label}: line to the pick point"] = (
            "blocked" if blocked else "clear")
    fixed = triangles(holder + base)
    view["holder and gripper block: share of the picture covered"] = \
        round(float(rays_hit(lens, rays, fixed).mean()), 3)
    report["view"] = view
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
    parser.add_argument("--holder", nargs="+", default=list(HOLDERS),
                        choices=list(HOLDERS))
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
        for name in args.holder:
            for pick in args.pick_distance:
                pick = int(pick) if float(pick).is_integer() else pick
                report = check(openscad, meshes, name, pick, workdir)
                reports[f"{name} at {pick} mm"] = report
                for key, value in report["gaps"].items():
                    if "URDF draws" in key:
                        continue    # see the README: that placement is on-axis
                    if isinstance(value, float) and value < 0:
                        failed = True
                    if isinstance(value, str) and float(value) > 1.0:
                        failed = True
    if args.json:
        print(json.dumps(reports, indent=2))
        return 1 if failed else 0

    for title, report in reports.items():
        print(title)
        for section in ("geometry", "gaps", "view"):
            for key, value in report[section].items():
                if section == "gaps" and isinstance(value, float):
                    value = (f">{SEARCH_MM:.0f} mm" if value == SEARCH_MM
                             else f"{value:.1f} mm")
                print(f"  {key:<58} {value}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
