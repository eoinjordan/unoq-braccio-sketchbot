"""Colour segmentation for bricks and the bin seen from an overhead camera.

This is a stand-in detector. It exists so the pick loop can be proven on a
wooden floor with plain yellow, red and white bricks and a blue bin; it knows
nothing about shape beyond "a compact blob of the right size". Anything that
offers the same call can replace it::

    detect(frame) -> list of (label, x_px, y_px, confidence)

``Detection`` is a tuple whose first four fields are exactly that, followed by
optional geometry (the long-axis angle and the box size in pixels) that the
planner uses to turn the jaws across the narrow side of a brick. A detector
that cannot supply the geometry leaves the defaults and the planner falls back
to a fixed jaw angle.

Colours are judged in CIE Lab relative to the floor, not against fixed
thresholds, because the floor is a warm wood whose hue sits within a few
degrees of a yellow brick under indoor light. The floor colour is the median
of the frame inside the region of interest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, NamedTuple, Optional, Sequence, Tuple

import cv2
import numpy as np

YELLOW = "yellow_brick"
RED = "red_brick"
WHITE = "white_brick"
BIN = "bin"
BRICK_LABELS = (YELLOW, RED, WHITE)


class Detection(NamedTuple):
    label: str
    x_px: float
    y_px: float
    confidence: float
    angle_deg: float = 0.0     # long axis, degrees counter-clockwise from image +x
    length_px: float = 0.0     # long side of the fitted box
    width_px: float = 0.0      # short side of the fitted box
    area_px: float = 0.0


@dataclass
class ColourDetectorConfig:
    # Region searched, (x0, y0, x1, y1) in pixels; None is the whole frame.
    roi: Optional[Tuple[int, int, int, int]] = None
    # Brick blob area limits in pixels. At about 1.3 px/mm a 2x4 brick with
    # 8 mm studs is roughly 85 x 43 px.
    min_area: float = 350.0
    max_area: float = 9000.0
    # Fraction of the fitted box a blob must fill. Cables and glare fail this.
    min_fill: float = 0.62
    max_aspect: float = 4.5
    bin_min_area: float = 9000.0
    # Lab offsets from the floor colour (OpenCV 8-bit Lab units).
    yellow_db: float = 13.0
    red_da: float = 24.0
    white_db: float = -13.0
    white_min_l: float = 150.0
    # Circles (x, y, radius) and polygons to ignore: the arm, its base sheet.
    ignore_circles: Sequence[Tuple[float, float, float]] = field(default_factory=tuple)
    ignore_polygons: Sequence[Sequence[Tuple[float, float]]] = field(default_factory=tuple)


def floor_lab(frame_bgr: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
    """Median Lab colour inside the region of interest: the floor."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    if roi is not None:
        x0, y0, x1, y1 = roi
        lab = lab[y0:y1, x0:x1]
    return np.median(lab.reshape(-1, 3), axis=0)


def class_masks(frame_bgr: np.ndarray, cfg: ColourDetectorConfig,
                floor: Optional[np.ndarray] = None) -> dict:
    """Boolean mask per label, before any blob filtering."""
    blurred = cv2.GaussianBlur(frame_bgr, (5, 5), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    if floor is None:
        floor = floor_lab(frame_bgr, cfg.roi)
    l, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    da, db = a - floor[1], b - floor[2]
    # The orange arm is red AND yellow in Lab terms; a red brick is red with
    # less yellow than red. That difference keeps the arm out of both classes.
    red = (da > cfg.red_da) & ((a - b) > -6.0)
    orange = (da > cfg.red_da * 0.6) & ~red
    yellow = (db > cfg.yellow_db) & (da < cfg.red_da * 0.6) & (l > 110)
    white = (db < cfg.white_db) & (np.abs(a - 128.0) < 9.0) & (l > cfg.white_min_l) & (b > 110)
    blue = (b < 105.0) & (l > 40)
    return {YELLOW: yellow, RED: red, WHITE: white, BIN: blue, "_orange": orange}


def _ignore_mask(shape, cfg: ColourDetectorConfig) -> np.ndarray:
    keep = np.full(shape[:2], 255, np.uint8)
    if cfg.roi is not None:
        x0, y0, x1, y1 = cfg.roi
        keep[:] = 0
        keep[y0:y1, x0:x1] = 255
    for x, y, r in cfg.ignore_circles:
        cv2.circle(keep, (int(round(x)), int(round(y))), int(round(r)), 0, -1)
    for poly in cfg.ignore_polygons:
        cv2.fillPoly(keep, [np.asarray(poly, np.int32)], 0)
    return keep


def _blobs(mask: np.ndarray, min_area: float):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            yield c, area


def _box(contour) -> Tuple[float, float, float, float, float]:
    """Centre, long side, short side and long-axis angle of the fitted box.

    The angle is counter-clockwise from image +x as seen on screen (image y
    points down, so it is negated), folded into (-90, 90].
    """
    (cx, cy), (w, h), ang = cv2.minAreaRect(contour)
    if w < h:
        w, h, ang = h, w, ang + 90.0
    ang = -ang
    while ang <= -90.0:
        ang += 180.0
    while ang > 90.0:
        ang -= 180.0
    return cx, cy, w, h, ang


class ColourDetector:
    """Classical detector for yellow, red and white bricks and a blue bin."""

    def __init__(self, cfg: Optional[ColourDetectorConfig] = None):
        self.cfg = cfg or ColourDetectorConfig()

    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        cfg = self.cfg
        floor = floor_lab(frame_bgr, cfg.roi)
        masks = class_masks(frame_bgr, cfg, floor)
        keep = _ignore_mask(frame_bgr.shape, cfg)
        kernel = np.ones((3, 3), np.uint8)
        out: List[Detection] = []

        for label in BRICK_LABELS:
            m = (masks[label].astype(np.uint8) * 255) & keep
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=2)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)
            for contour, area in _blobs(m, cfg.min_area):
                if area > cfg.max_area:
                    continue
                cx, cy, long_side, short_side, ang = _box(contour)
                if short_side < 1.0:
                    continue
                fill = area / (long_side * short_side)
                aspect = long_side / short_side
                if fill < cfg.min_fill or aspect > cfg.max_aspect:
                    continue
                conf = float(np.clip(0.3 + 0.7 * (fill - cfg.min_fill) / (1.0 - cfg.min_fill), 0.0, 1.0))
                out.append(Detection(label, float(cx), float(cy), round(conf, 3), float(ang),
                                     float(long_side), float(short_side), float(area)))

        # The bin: the largest blue blob. Its rim occludes itself, so the box of
        # the convex hull is used rather than the blob outline.
        m = (masks[BIN].astype(np.uint8) * 255) & keep
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        best = None
        for contour, area in _blobs(m, cfg.bin_min_area):
            if best is None or area > best[1]:
                best = (contour, area)
        if best is not None:
            hull = cv2.convexHull(best[0])
            cx, cy, long_side, short_side, ang = _box(hull)
            fill = best[1] / max(1.0, long_side * short_side)
            out.append(Detection(BIN, float(cx), float(cy), round(float(np.clip(fill, 0, 1)), 3),
                                 float(ang), float(long_side), float(short_side), float(best[1])))
        return out


def box_corners(det: Detection) -> np.ndarray:
    """Four corners of a detection's fitted box, in pixels."""
    t = np.radians(-det.angle_deg)   # back to image coordinates (y down)
    ux, uy = np.cos(t), np.sin(t)
    hl, hw = det.length_px / 2.0, det.width_px / 2.0
    c = np.array([det.x_px, det.y_px])
    u, v = np.array([ux, uy]), np.array([-uy, ux])
    return np.array([c + hl * u + hw * v, c + hl * u - hw * v,
                     c - hl * u - hw * v, c - hl * u + hw * v])


_COLOURS = {YELLOW: (0, 200, 255), RED: (0, 0, 230), WHITE: (255, 255, 255), BIN: (255, 120, 0)}


def annotate(frame_bgr: np.ndarray, detections: Sequence[Detection],
             notes: Optional[Sequence[str]] = None) -> np.ndarray:
    """Copy of the frame with every detection boxed and labelled."""
    out = frame_bgr.copy()
    for i, d in enumerate(detections):
        colour = _COLOURS.get(d.label, (0, 255, 0))
        if d.length_px > 0:
            pts = box_corners(d).astype(np.int32)
            cv2.polylines(out, [pts], True, (0, 0, 0), 4)
            cv2.polylines(out, [pts], True, colour, 2)
        cv2.circle(out, (int(d.x_px), int(d.y_px)), 4, (0, 0, 0), -1)
        text = "%d %s %.2f" % (i, d.label, d.confidence)
        if notes is not None and i < len(notes) and notes[i]:
            text += " " + notes[i]
        org = (int(d.x_px + d.length_px / 2 + 6), int(d.y_px - 6))
        cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)
    return out
