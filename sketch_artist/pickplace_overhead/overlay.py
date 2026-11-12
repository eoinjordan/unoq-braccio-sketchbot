"""Draw a plan over a camera frame: detections, base frame, keep-outs, reach."""

from __future__ import annotations

import math
from typing import Optional, Sequence

import cv2
import numpy as np

from .detect import Detection, annotate
from .geometry import ArmGeometry, Envelope, Unreachable, project
from .plan import BrickPlan, PickConfig


def _pt(P, xyz):
    u, v = project(P, xyz)
    return int(round(u)), int(round(v))


def _text(img, text, org, colour=(255, 255, 255), scale=0.55):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 1, cv2.LINE_AA)


def reach_band(arm: ArmGeometry, z: float, pitches: Sequence[float]):
    """Smallest and largest reach at height z over the allowed tool pitches."""
    ok = []
    for r in range(60, 420, 2):
        for pitch in pitches:
            try:
                arm.solve(float(r), 0.0, z, pitch)
                ok.append(r)
                break
            except Unreachable:
                continue
    return (min(ok), max(ok)) if ok else None


def draw_plan(frame_bgr: np.ndarray, detections: Sequence[Detection], plans: Sequence[BrickPlan],
              P: np.ndarray, arm: ArmGeometry, env: Envelope, cfg: PickConfig,
              title: Optional[str] = None) -> np.ndarray:
    notes = [""] * len(detections)
    for p in plans:
        notes[p.index] = "PICK r=%.0f" % p.reach_mm if p.reachable else "skip"
    out = annotate(frame_bgr, detections, notes)

    # Base frame: origin, +x (red) and +y (green), 100 mm long, on the floor.
    o = _pt(P, (0, 0, 0))
    cv2.arrowedLine(out, o, _pt(P, (100, 0, 0)), (0, 0, 255), 2, tipLength=0.15)
    cv2.arrowedLine(out, o, _pt(P, (0, 100, 0)), (0, 200, 0), 2, tipLength=0.15)
    _text(out, "base", (o[0] + 6, o[1] + 18))

    # Reach band at grasp height, drawn over the allowed base sector behind the arm.
    band = reach_band(arm, cfg.grasp_z_mm, range(int(cfg.pitch_min_deg), int(cfg.pitch_max_deg) + 1, 5))
    if band:
        lo, hi = env.base_range
        for r, colour in ((band[0], (255, 0, 255)), (band[1], (255, 0, 255))):
            pts = []
            for i in range(0, 61):
                base = lo + (hi - lo) * i / 60.0
                yaw = math.radians(base - 90.0 + 180.0)
                pts.append(_pt(P, (r * math.cos(yaw), r * math.sin(yaw), 0.0)))
            cv2.polylines(out, [np.asarray(pts, np.int32)], False, colour, 1, cv2.LINE_AA)

    for k in env.keep_outs:
        top = [_pt(P, (x, y, k.top_mm)) for x, y in k.polygon_xy]
        foot = [_pt(P, (x, y, 0.0)) for x, y in k.polygon_xy]
        cv2.polylines(out, [np.asarray(top, np.int32)], True, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.polylines(out, [np.asarray(foot, np.int32)], True, (0, 0, 160), 1, cv2.LINE_AA)
        _text(out, "keep-out %s to %.0f mm" % (k.name, k.top_mm), (top[0][0], top[0][1] - 8), (0, 0, 255))

    for p in plans:
        if not p.reachable:
            continue
        u, v = _pt(P, (p.xy_mm[0], p.xy_mm[1], cfg.brick_top_mm))
        cv2.drawMarker(out, (u, v), (0, 255, 0), cv2.MARKER_CROSS, 18, 2)
    if title:
        _text(out, title, (20, 34), (255, 255, 255), 0.8)
    return out
