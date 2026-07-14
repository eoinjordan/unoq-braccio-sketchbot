"""Turn a binary line-art image into ordered pen strokes.

A *stroke* is a list of ``(x, y)`` points in pixel coordinates of the square
line-art canvas (top-left origin, +y down). The planner later maps these into
paper millimetres.
"""

from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np

Point = Tuple[float, float]
Stroke = List[Point]


def strokes_from_edges(edges: np.ndarray, drawing_cfg: dict) -> List[Stroke]:
    """Trace contours in an edge image into simplified polyline strokes."""
    vec_cfg = drawing_cfg.get("vectorize", {})
    min_len = float(vec_cfg.get("min_contour_len_px", 12))
    epsilon = float(vec_cfg.get("simplify_epsilon_px", 1.5))
    max_strokes = int(vec_cfg.get("max_strokes", 400))
    max_points = int(vec_cfg.get("max_points_per_stroke", 120))

    # Close small gaps so edges become continuous contours.
    kernel = np.ones((2, 2), np.uint8)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    strokes: List[Stroke] = []
    for contour in contours:
        if cv2.arcLength(contour, closed=False) < min_len:
            continue
        approx = cv2.approxPolyDP(contour, epsilon, closed=False)
        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        if len(pts) < 2:
            continue
        if len(pts) > max_points:
            step = int(np.ceil(len(pts) / max_points))
            pts = pts[::step]
        strokes.append(pts)

    # Keep the longest strokes first, then optionally trim by fraction/limit.
    strokes.sort(key=_stroke_length, reverse=True)

    keep_fraction = float(drawing_cfg.get("style", {}).get("keep_longest_fraction", 1.0))
    if keep_fraction < 1.0:
        keep = max(1, int(len(strokes) * keep_fraction))
        strokes = strokes[:keep]

    return strokes[:max_strokes]


def _stroke_length(stroke: Stroke) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(stroke, stroke[1:]):
        total += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    return total


def bounding_box(strokes: List[Stroke]) -> Tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) across all strokes."""
    xs = [x for s in strokes for x, _ in s]
    ys = [y for s in strokes for _, y in s]
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))
