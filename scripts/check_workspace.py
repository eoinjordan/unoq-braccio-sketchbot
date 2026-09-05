#!/usr/bin/env python3
"""Check that every point of the configured paper box is actually drawable.

``sketch_artist.cli`` silently skips moves it cannot solve, so a paper box that
is out of reach shows up as a drawing with pieces missing rather than an error.
This checks the box up front and, when it does not fit, reports the largest
rectangle that does.

    python scripts/check_workspace.py                 # check config/workspace.yaml
    python scripts/check_workspace.py --suggest       # ... and propose a box
    python scripts/check_workspace.py --pen 130       # try a different pen length

The binding constraints are the servo ranges, not just the arm's reach: the
elbow and wrist only bend +-90 degrees from in line, so the shoulder-to-wrist
distance must stay between ``hypot(l1, l2)`` and ``l1 + l2``, and the forearm
can never point above horizontal while the pen stays vertical.
"""

from __future__ import annotations

import argparse
import copy
from typing import List, Optional, Tuple

import sys
from pathlib import Path

# Allow running as `python scripts/<name>.py` from anywhere in the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sketch_artist import config as cfg
from sketch_artist.kinematics import BraccioKinematics, UnreachableError

Box = Tuple[float, float, float, float]  # origin_x, origin_y, width, height

# Servo travel of the real TinkerKit Braccio (unoq_braccio_driver.braccio_model).
REAL_LIMITS = {"base": (0, 180), "shoulder": (15, 165),
               "elbow": (0, 180), "wrist_vertical": (0, 180)}

# What the Gazebo model can actually do, expressed in the same servo degrees.
# unoq_braccio_sim's URDF gives the shoulder +-1.309 rad and the elbow/wrist
# +-1.5708 rad about a zero that sits 90 degrees off the Braccio's, so the model
# reaches less than the real arm. Poses outside this draw correctly on hardware
# but get clamped in simulation.
SIM_LIMITS = {"base": (0, 180), "shoulder": (0, 75),
              "elbow": (0, 90), "wrist_vertical": (0, 90)}

LIMIT_SETS = {"real": [REAL_LIMITS], "sim": [SIM_LIMITS],
              "both": [REAL_LIMITS, SIM_LIMITS]}


def _within(angles, limit_sets) -> bool:
    values = {"base": angles.base, "shoulder": angles.shoulder,
              "elbow": angles.elbow, "wrist_vertical": angles.wrist_vertical}
    return all(lo <= values[joint] <= hi
               for limits in limit_sets
               for joint, (lo, hi) in limits.items())


def drawable(kin: BraccioKinematics, x: float, y: float, heights,
             limit_sets=LIMIT_SETS["both"]) -> bool:
    """True when the pen reaches (x, y) at every height without clamping."""
    for z in heights:
        try:
            angles = kin.solve(x, y, z, strict=True)
        except UnreachableError:
            return False
        if not _within(angles, limit_sets):
            return False
    return True


def _grid(box: Box, step: float) -> List[Tuple[float, float]]:
    ox, oy, w, h = box
    xs = [ox + i * step for i in range(int(w / step) + 1)] + [ox + w]
    ys = [oy + i * step for i in range(int(h / step) + 1)] + [oy + h]
    return [(x, y) for x in xs for y in ys]


def check_box(kin: BraccioKinematics, box: Box, heights, step: float = 5.0,
              limit_sets=LIMIT_SETS["both"]) -> Tuple[int, int]:
    """Return (drawable_points, total_points) over a grid covering the box."""
    points = _grid(box, step)
    good = sum(1 for x, y in points if drawable(kin, x, y, heights, limit_sets))
    return good, len(points)


def largest_box(kin: BraccioKinematics, heights, step: float = 5.0,
                aspect: float = 1.0,
                limit_sets=LIMIT_SETS["both"]) -> Optional[Box]:
    """Largest fully drawable box of the given height/width ratio.

    Samples reachability once onto a grid, then scans candidate boxes against a
    summed-area table, so the cost is one IK solve per grid point rather than
    one per candidate box. ``aspect`` 1.0 searches squares (what a portrait
    wants); the drawable region is an annulus, so the biggest square is set by
    how wide that band is.
    """
    reach = kin.l1 + kin.l2
    xs = _frange(step, reach, step)
    ys = _frange(-reach, reach, step)
    mask = [[1 if drawable(kin, x, y, heights, limit_sets) else 0 for y in ys]
            for x in xs]

    # Summed-area table: total[i][j] = free points in mask[:i][:j].
    total = [[0] * (len(ys) + 1) for _ in range(len(xs) + 1)]
    for i in range(len(xs)):
        for j in range(len(ys)):
            total[i + 1][j + 1] = (mask[i][j] + total[i][j + 1]
                                   + total[i + 1][j] - total[i][j])

    def all_free(i0: int, j0: int, di: int, dj: int) -> bool:
        got = (total[i0 + di][j0 + dj] - total[i0][j0 + dj]
               - total[i0 + di][j0] + total[i0][j0])
        return got == di * dj

    best: Optional[Box] = None
    for cells_x in range(2, len(xs) + 1):
        width = (cells_x - 1) * step
        cells_y = int(round(width * aspect / step)) + 1
        if cells_y < 2 or cells_y > len(ys):
            continue
        for i0 in range(0, len(xs) - cells_x + 1):
            for j0 in range(0, len(ys) - cells_y + 1):
                if all_free(i0, j0, cells_x, cells_y):
                    best = (xs[i0], ys[j0], width, (cells_y - 1) * step)
                    break
            if best is not None and best[2] == width:
                break
    return best


def _frange(start: float, stop: float, step: float) -> List[float]:
    out, value = [], start
    while value <= stop:
        out.append(round(value, 3))
        value += step
    return out


def describe(kin: BraccioKinematics, heights) -> List[str]:
    import math
    span_min = math.hypot(kin.l1, kin.l2)
    span_max = kin.l1 + kin.l2
    lines = [
        f"links: base {kin.base_height:.0f} mm, upper arm {kin.l1:.0f} mm, "
        f"forearm {kin.l2:.0f} mm, wrist->pen {kin.wrist_pen:.0f} mm",
        f"shoulder-to-wrist distance must stay in "
        f"[{span_min:.1f}, {span_max:.1f}] mm (elbow bends +-90 deg)",
    ]
    for z in heights:
        wrist_h = z + kin.wrist_pen - kin.base_height
        if abs(wrist_h) >= span_max:
            lines.append(f"  pen z={z:+.0f} mm: wrist would sit {wrist_h:+.0f} mm "
                         f"from the shoulder, past the arm's {span_max:.0f} mm reach")
            continue
        r_min = math.sqrt(max(0.0, span_min ** 2 - wrist_h ** 2))
        r_max = math.sqrt(max(0.0, span_max ** 2 - wrist_h ** 2))
        lines.append(f"  pen z={z:+.0f} mm: reachable radius {r_min:.0f}..{r_max:.0f} mm")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the configured paper box against the arm's reach.")
    parser.add_argument("--suggest", action="store_true",
                        help="Also search for the largest box that does fit.")
    parser.add_argument("--pen", type=float,
                        help="Override links.wrist_pen_mm (mm) for a what-if.")
    parser.add_argument("--step", type=float, default=5.0,
                        help="Grid resolution in mm (default 5).")
    parser.add_argument("--aspect", type=float, default=1.0,
                        help="Height/width of the suggested box (1.0 = square).")
    parser.add_argument("--limits", choices=sorted(LIMIT_SETS), default="both",
                        help="Servo travel to respect: the real Braccio, the "
                             "Gazebo model, or both (default).")
    args = parser.parse_args(argv)

    workspace = copy.deepcopy(cfg.load_all()["workspace"])
    if args.pen is not None:
        workspace["links"]["wrist_pen_mm"] = args.pen

    kin = BraccioKinematics(workspace)
    pen = workspace["pen"]
    heights = (float(pen["down_z_mm"]), float(pen["up_z_mm"]))
    paper = workspace["paper"]
    box: Box = (float(paper["origin_x_mm"]), float(paper["origin_y_mm"]),
                float(paper["width_mm"]), float(paper["height_mm"]))

    for line in describe(kin, heights):
        print(line)

    limit_sets = LIMIT_SETS[args.limits]
    good, total = check_box(kin, box, heights, args.step, limit_sets)
    print(f"\npaper box {box[2]:.0f} x {box[3]:.0f} mm at "
          f"({box[0]:.0f}, {box[1]:.0f}): {good}/{total} grid points drawable")

    if good == total:
        print("OK: the whole paper box is drawable.")
        return 0

    print("FAIL: part of the paper box is out of reach; the arm will skip "
          "those strokes.")
    if args.suggest:
        print("searching for the largest box that fits ...")
        best = largest_box(kin, heights, args.step, args.aspect, limit_sets)
        if best is None:
            print("  none found: shorten the pen (links.wrist_pen_mm), lower "
                  "pen.up_z_mm, or move the paper below the arm's base plane.")
        else:
            ox, oy, w, h = best
            print(f"  paper:\n    origin_x_mm: {ox:.0f}\n    origin_y_mm: {oy:.0f}"
                  f"\n    width_mm: {w:.0f}\n    height_mm: {h:.0f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
