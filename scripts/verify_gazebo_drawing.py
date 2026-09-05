#!/usr/bin/env python3
"""Compare what the Braccio actually drew in Gazebo with what was planned.

``sim/gazebo/braccio_sim/pen_tracker.py`` logs the simulated pen tip to CSV.
This re-runs the same planning the CLI did and checks, for every pen-down
sample, how far the pen was from the nearest planned stroke segment. That is
the end-to-end assertion: the picture, the plan, the IK, the M/S protocol, the
bridge, the controller and the physics all have to agree for it to pass.

    python scripts/verify_gazebo_drawing.py --csv output/gazebo_drawing.csv \
        --image examples/sample_face_eoin.png --style none --tolerance 4
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import List, Sequence, Tuple

import sys
from pathlib import Path

# Allow running as `python scripts/<name>.py` from anywhere in the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from sketch_artist import config as cfg
from sketch_artist.planner import Move, plan
from sketch_artist.portrait import to_line_art
from sketch_artist.scenes import compose, resolve_style
from sketch_artist.vectorize import strokes_from_edges

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


def planned_segments(image: str, style: str) -> Tuple[List[Segment], List[Move]]:
    conf = cfg.load_all()
    frame = cv2.imread(str(cfg.resolve_path(image)))
    if frame is None:
        raise SystemExit(f"could not read image: {image}")
    edges = to_line_art(frame, conf["drawing"])
    strokes = strokes_from_edges(edges, conf["drawing"])
    canvas = int(conf["drawing"].get("capture", {}).get("target_px", 512))
    chosen = resolve_style(conf["scenes"], style, interactive=False)
    strokes = compose(strokes, chosen, conf["scenes"], canvas)
    moves = plan(strokes, conf["workspace"])

    segments: List[Segment] = []
    previous: Point | None = None
    for move in moves:
        here = (move.x_mm, move.y_mm)
        if move.pen_down and previous is not None:
            segments.append((previous, here))
        previous = here if move.pen_down else None
    return segments, moves


def point_to_segment(p: Point, seg: Segment) -> float:
    (x1, y1), (x2, y2) = seg
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return math.dist(p, (x1, y1))
    t = max(0.0, min(1.0, ((p[0] - x1) * dx + (p[1] - y1) * dy) / length_sq))
    return math.dist(p, (x1 + t * dx, y1 + t * dy))


def read_samples(path: Path) -> List[Tuple[float, float, float, bool]]:
    out = []
    with path.open(encoding="ascii") as handle:
        for row in csv.DictReader(handle):
            out.append((float(row["x_mm"]), float(row["y_mm"]),
                        float(row["z_mm"]), row["pen_down"] == "1"))
    return out


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the Gazebo pen path against the planned drawing.")
    parser.add_argument("--csv", default="output/gazebo_drawing.csv")
    parser.add_argument("--image", default="examples/sample_face_eoin.png")
    parser.add_argument("--style", default="none")
    parser.add_argument("--tolerance", type=float, default=4.0,
                        help="Allowed 95th-percentile deviation, mm.")
    parser.add_argument("--min-coverage", type=float, default=0.9,
                        help="Fraction of planned pen-down points the pen must "
                             "reach.")
    args = parser.parse_args(argv)

    csv_path = Path(cfg.resolve_path(args.csv))
    if not csv_path.exists():
        print(f"no pen log at {csv_path}: did the sim run?")
        return 2

    segments, moves = planned_segments(args.image, args.style)
    if not segments:
        print("the plan contains no pen-down segments")
        return 2

    samples = read_samples(csv_path)
    drawn = [(x, y) for x, y, _z, down in samples if down]
    if not drawn:
        print(f"the pen never went down in {len(samples)} samples")
        return 1

    # Accuracy: how far each recorded sample sat from the planned strokes.
    errors = [min(point_to_segment(point, segment) for segment in segments)
              for point in drawn]

    # Coverage: how many planned pen-down points the pen actually reached. This
    # is measured over points rather than segments because the arm dwells at
    # each commanded point, so samples cluster on the vertices and a
    # nearest-segment count under-reports a complete drawing by about half.
    planned_points = [(move.x_mm, move.y_mm) for move in moves if move.pen_down]
    reached = sum(1 for planned in planned_points
                  if min(math.dist(planned, point) for point in drawn)
                  <= args.tolerance)
    coverage = reached / len(planned_points)
    p50, p95, worst = (percentile(errors, 0.5), percentile(errors, 0.95),
                       max(errors))

    print(f"planned {len(segments)} stroke segments from {len(moves)} moves")
    print(f"pen-down samples in Gazebo: {len(drawn)} of {len(samples)}")
    print(f"deviation from the planned strokes: "
          f"median {p50:.2f} mm, p95 {p95:.2f} mm, worst {worst:.2f} mm")
    print(f"planned points the pen actually reached: "
          f"{reached}/{len(planned_points)} ({coverage * 100:.0f}%)")

    ok = p95 <= args.tolerance and coverage >= args.min_coverage
    if ok:
        print(f"PASS: the simulated Braccio drew the planned picture "
              f"(p95 <= {args.tolerance} mm, coverage >= "
              f"{args.min_coverage * 100:.0f}%)")
        return 0
    if p95 > args.tolerance:
        print(f"FAIL: p95 deviation {p95:.2f} mm exceeds {args.tolerance} mm")
    if coverage < args.min_coverage:
        print(f"FAIL: the pen only reached {coverage * 100:.0f}% of the "
              f"planned points")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
