#!/usr/bin/env python3
"""Check that a cable tie can pass through every tie tunnel as exported.

The gripper-top camera holders and the saddle fit piece are tied to the
gripper block through a tunnel in the saddle pad. A tunnel that is drawn in the
source but closed in the mesh, by a part added after the cut or by a wall the
tunnel ends in, would only be found with a tie in hand, so the exported STLs
themselves are probed here:

  * straight through: lines the length of the part, spread over the cross
    section of a 3.6 x 1.4 mm tie, cross no triangle, so the tunnel is open
    from one mouth to the other and both mouths are open to the outside;
  * a real tunnel: somewhere along it there is a floor, a roof and a wall
    each side, so the tie is held and the passage is not just missing plastic.

    python scripts/check_tie_tunnels.py            # probe the shipped STLs
    python scripts/check_tie_tunnels.py --write    # refresh the probe list

The STLs are in their print pose, so where each tunnel lies in them is kept in
hardware/pencil-grip/braccio_gripper_tie_tunnels.json. --write rebuilds that
file from what OpenSCAD reports for each part (scripts/render_hardware.sh does
this after exporting). Probing needs numpy only; tests/test_tie_tunnels.py
runs it.
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

from scripts.mesh_check import load_stl  # noqa: E402

PARTS = REPO / "hardware" / "pencil-grip"
PROBES = PARTS / "braccio_gripper_tie_tunnels.json"
TIE_MM = (3.6, 1.4)                 # the largest tie the tunnel is for
REACH_MM = 150.0                    # probe lines run this far each way

# STL, its source, and the OpenSCAD settings it is exported with.
EXPORTS = [
    (f"braccio_gripper_{holder}{suffix}.stl", f"braccio_gripper_{holder}.scad",
     pick)
    for holder in ("xiao_round_display", "esp_eye")
    for suffix, pick in (("_near", 90), ("", 120), ("_far", 180))
] + [("braccio_gripper_saddle_fit_test.stl",
      "braccio_gripper_saddle_fit_test.scad", None)]


def to_print(point, info):
    """Wrist roll frame to the STL's own frame (its print pose)."""
    x, y, z = point
    if "front_z" in info:           # the saddle fit piece stands on its front
        return [x, -y, info["front_z"] - z]
    ox, oy, oz = info["origin"]
    t = math.radians(info["tilt_deg"])
    dy, dz = y - oy, z - oz
    yk = dy * math.cos(t) + dz * math.sin(t)
    zk = -dy * math.sin(t) + dz * math.cos(t)
    return [x - ox, -yk, info["bed_w"] - zk]


def probes_for(info):
    """One probe per tunnel: its centre and three unit vectors in the STL."""
    width, thick = info["tie_tunnel"]
    out = []
    for z, y in info["ties"]:
        centre = to_print([0.0, y + thick / 2, z], info)

        def direction(d):
            tip = to_print([d[0], y + thick / 2 + d[1], z + d[2]], info)
            return [round(a - b, 6) for a, b in zip(tip, centre)]

        out.append({
            "centre": [round(v, 4) for v in centre],
            "along": direction((1, 0, 0)),      # the way the tie runs
            "across": direction((0, 0, 1)),     # the tie's width
            "up": direction((0, 1, 0)),         # the tie's thickness
            "tunnel_mm": [width, thick],
        })
    return out


def write_probes(openscad):
    table = {}
    with tempfile.TemporaryDirectory() as work:
        for stl, source, pick in EXPORTS:
            command = [openscad, "-o", str(Path(work) / "probe.echo")]
            if pick is not None:
                command += ["-D", f"pick_distance={pick}"]
            result = subprocess.run(command + [str(PARTS / source)],
                                    capture_output=True, text=True)
            text = result.stdout + result.stderr
            echo = Path(work) / "probe.echo"
            if echo.exists():
                text += echo.read_text(encoding="utf-8", errors="replace")
            found = re.search(r'gripper_camera (\{.*\})"', text)
            if not found:
                raise SystemExit(f"{source} did not report its geometry:\n{text}")
            table[stl] = probes_for(json.loads(found.group(1)))
    PROBES.write_text(json.dumps(table, indent=2) + "\n", encoding="ascii")
    return table


def crossings(tris, start, end):
    """How many triangles the segment start -> end passes through."""
    direction = end - start
    e1 = tris[:, 1] - tris[:, 0]
    e2 = tris[:, 2] - tris[:, 0]
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    t0 = start - tris[:, 0]
    u = np.einsum("ij,ij->i", t0, p) * inv
    q = np.cross(t0, e1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    return int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0) & (t < 1)).sum())


def probe(stl_path, tunnel):
    """(lines blocked, lines tried, enclosed) for one tunnel in one STL."""
    tris, _ = load_stl(stl_path)
    centre = np.array(tunnel["centre"], float)
    along = np.array(tunnel["along"], float)
    across = np.array(tunnel["across"], float)
    up = np.array(tunnel["up"], float)
    blocked = tried = 0
    for a in np.linspace(-TIE_MM[0] / 2, TIE_MM[0] / 2, 5):
        for b in np.linspace(-TIE_MM[1] / 2, TIE_MM[1] / 2, 3):
            point = centre + a * across + b * up
            tried += 1
            if crossings(tris, point - REACH_MM * along, point + REACH_MM * along):
                blocked += 1
    enclosed = False
    for step in np.linspace(-45, 45, 61):
        point = centre + step * along
        if all(crossings(tris, point, point + 40 * d)
               for d in (up, -up, across, -across)):
            enclosed = True
            break
    return blocked, tried, enclosed


def check_all():
    table = json.loads(PROBES.read_text(encoding="ascii"))
    results = []
    for stl, tunnels in sorted(table.items()):
        for index, tunnel in enumerate(tunnels):
            blocked, tried, enclosed = probe(PARTS / stl, tunnel)
            results.append((stl, index, blocked, tried, enclosed))
    return results


def find_openscad(given):
    import shutil
    for candidate in (given, "openscad", "openscad.com",
                      "C:/Program Files/OpenSCAD/openscad.com",
                      "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"):
        if candidate and (shutil.which(candidate) or Path(candidate).exists()):
            return candidate
    raise SystemExit("OpenSCAD not found; pass --openscad")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="rebuild the probe list from the OpenSCAD sources")
    parser.add_argument("--openscad", default=None)
    args = parser.parse_args(argv)
    if args.write:
        write_probes(find_openscad(args.openscad))
    failed = False
    for stl, index, blocked, tried, enclosed in check_all():
        state = "open" if not blocked else f"BLOCKED on {blocked} of {tried} lines"
        walls = "walled all round" if enclosed else "NOT A TUNNEL"
        print(f"{stl}: tunnel {index + 1}: {state}, {walls}")
        failed = failed or bool(blocked) or not enclosed
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
