"""Plan a drawing: map pixel strokes into paper millimetres, order them to
minimise pen travel, and expand into pen up/down moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .vectorize import Stroke, bounding_box

Point = Tuple[float, float]


@dataclass
class Move:
    """A single planned move of the pen tip in paper millimetres."""
    x_mm: float
    y_mm: float
    pen_down: bool


def _fit_transform(strokes: List[Stroke], paper: dict) -> Tuple[float, float, float, float, float]:
    """Compute scale + offset to fit the drawing inside the paper box.

    Returns (scale, off_x, off_y, origin_x, origin_y). Preserves aspect ratio
    and centres the drawing in the paper rectangle.
    """
    min_x, min_y, max_x, max_y = bounding_box(strokes)
    src_w = max(1e-6, max_x - min_x)
    src_h = max(1e-6, max_y - min_y)

    paper_w = float(paper["width_mm"])
    paper_h = float(paper["height_mm"])
    scale = min(paper_w / src_w, paper_h / src_h)

    drawn_w = src_w * scale
    drawn_h = src_h * scale
    off_x = (paper_w - drawn_w) / 2.0
    off_y = (paper_h - drawn_h) / 2.0
    return scale, off_x, off_y, min_x, min_y


def _to_mm(pt: Point, scale: float, off_x: float, off_y: float,
           src_min_x: float, src_min_y: float, paper: dict) -> Point:
    x, y = pt
    # Map pixel coords into paper millimetres. Both axes are mapped without
    # flipping; the arm coordinate frame is configured via workspace.yaml
    # (paper origin_x/y and servo_calibration signs).
    mm_x = float(paper["origin_x_mm"]) + off_x + (x - src_min_x) * scale
    mm_y = float(paper["origin_y_mm"]) + off_y + (y - src_min_y) * scale
    return mm_x, mm_y


def _order_strokes(strokes: List[Stroke]) -> List[Stroke]:
    """Greedy nearest-neighbour ordering to reduce pen-up travel."""
    if not strokes:
        return []
    remaining = list(strokes)
    ordered: List[Stroke] = [remaining.pop(0)]
    while remaining:
        last = ordered[-1][-1]
        best_i, best_d, best_rev = 0, float("inf"), False
        for i, s in enumerate(remaining):
            d_start = _dist(last, s[0])
            d_end = _dist(last, s[-1])
            if d_start < best_d:
                best_i, best_d, best_rev = i, d_start, False
            if d_end < best_d:
                best_i, best_d, best_rev = i, d_end, True
        nxt = remaining.pop(best_i)
        ordered.append(nxt[::-1] if best_rev else nxt)
    return ordered


def _dist(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def plan(strokes: List[Stroke], workspace_cfg: dict) -> List[Move]:
    """Return an ordered list of pen moves in paper millimetres."""
    paper = workspace_cfg["paper"]
    if not strokes:
        return []

    join_gap_mm = float(workspace_cfg.get("planner", {}).get("join_gap_mm", 0.0))
    scale, off_x, off_y, src_min_x, src_min_y = _fit_transform(strokes, paper)
    ordered = _order_strokes(strokes)

    moves: List[Move] = []
    prev_end: Point | None = None
    for stroke in ordered:
        first = _to_mm(stroke[0], scale, off_x, off_y, src_min_x, src_min_y, paper)
        if prev_end is not None and _dist(prev_end, first) <= join_gap_mm:
            # Close enough: keep the pen down and draw through the gap.
            moves.append(Move(first[0], first[1], pen_down=True))
        else:
            # Pen-up travel to the start of the stroke, then pen down.
            moves.append(Move(first[0], first[1], pen_down=False))
            moves.append(Move(first[0], first[1], pen_down=True))
        for pt in stroke[1:]:
            mm = _to_mm(pt, scale, off_x, off_y, src_min_x, src_min_y, paper)
            moves.append(Move(mm[0], mm[1], pen_down=True))
        prev_end = _to_mm(stroke[-1], scale, off_x, off_y, src_min_x, src_min_y, paper)
    # Lift at the end.
    if moves:
        last = moves[-1]
        moves.append(Move(last.x_mm, last.y_mm, pen_down=False))
    return moves


def move_count(moves: List[Move]) -> Tuple[int, int]:
    """Return (pen_down_points, pen_up_moves) for reporting."""
    down = sum(1 for m in moves if m.pen_down)
    up = sum(1 for m in moves if not m.pen_down)
    return down, up
