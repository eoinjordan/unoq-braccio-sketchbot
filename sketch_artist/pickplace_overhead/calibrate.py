"""Calibrate the overhead camera against the arm, without going near the floor.

The arm holds its closed gripper out at a set of known poses, all with the
fingertips well above anything on the floor. In each frame the fingertips
are found as the far end of the white jaws. Those pixel positions, paired
with where the kinematics say the fingertips are, give the camera's
projection matrix.

The same data measures the tool length. The fingertip position depends on
the tool length differently at every tool pitch, so only the right length
lets one camera explain all the frames; the fit is repeated over candidate
lengths and the one with the smallest reprojection error wins.

Because the pairs are (pixel, commanded position), a small constant error in
the kinematic model is absorbed by the fit instead of ending up in the pick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .geometry import (Angles, ArmGeometry, Unreachable, fit_camera, project,
                       reprojection_errors)


@dataclass
class Sample:
    angles: Angles
    pixel: Tuple[float, float]


def calibration_poses(arm: ArmGeometry, bases: Sequence[float],
                      reaches: Sequence[float] = (250.0, 290.0, 330.0),
                      heights: Sequence[float] = (150.0, 195.0, 240.0),
                      pitches: Sequence[float] = (0.0, -25.0, -50.0),
                      jaws: float = 60.0, behind: bool = True) -> List[Angles]:
    """Poses that spread the fingertips through a volume above the floor.

    Ordered so that neighbours are close: one base heading at a time, and a
    serpentine through reach and height within it.
    """
    poses: List[Angles] = []
    flip = False
    for base in bases:
        column: List[Angles] = []
        for pitch in pitches:
            for z in heights:
                for r in reaches:
                    yaw = math.radians(base - 90.0 + (180.0 if behind else 0.0))
                    try:
                        column.append(arm.solve(r * math.cos(yaw), r * math.sin(yaw), z, pitch,
                                                90.0, jaws))
                    except Unreachable:
                        continue
        column.sort(key=lambda a: (a[1], a[2]))
        poses.extend(reversed(column) if flip else column)
        flip = not flip
    return poses


def find_fingertip(reference_bgr: np.ndarray, frame_bgr: np.ndarray,
                   base_px: Sequence[float], heading_px_deg: float,
                   half_angle_deg: float = 30.0, min_radius_px: float = 150.0,
                   max_radius_px: float = 700.0,
                   expected_px: Optional[Sequence[float]] = None,
                   search_px: float = 170.0) -> Optional[Tuple[float, float]]:
    """Pixel of the closed fingertips: the far end of the white jaws.

    Looks only inside a wedge from the base along ``heading_px_deg`` (the
    on-screen direction the arm reaches, counter-clockwise from image +x),
    at pixels that are white now and were not white in the reference frame.
    With ``expected_px`` (where a rough camera model puts the fingertips) the
    search is also limited to ``search_px`` around it, which keeps a white
    cable further out from being taken for the jaws.
    """
    lab = cv2.cvtColor(cv2.GaussianBlur(frame_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = cv2.cvtColor(cv2.GaussianBlur(reference_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    floor_b = float(np.median(ref[..., 2]))
    white = (lab[..., 2] < floor_b - 12.0) & (np.abs(lab[..., 1] - 128.0) < 10.0) & (lab[..., 0] > 120.0)
    was_white = (ref[..., 2] < floor_b - 8.0) & (np.abs(ref[..., 1] - 128.0) < 12.0)
    mask = (white & ~was_white).astype(np.uint8) * 255

    h, w = mask.shape
    ys, xs = np.mgrid[0:h, 0:w]
    dx, dy = xs - base_px[0], -(ys - base_px[1])
    radius = np.hypot(dx, dy)
    bearing = np.degrees(np.arctan2(dy, dx))
    off = (bearing - heading_px_deg + 180.0) % 360.0 - 180.0
    wedge = (np.abs(off) <= half_angle_deg) & (radius >= min_radius_px) & (radius <= max_radius_px)
    if expected_px is not None:
        wedge &= np.hypot(xs - expected_px[0], ys - expected_px[1]) <= search_px
    mask &= wedge.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 250:
            continue
        sel = labels == i
        r = radius[sel]
        far = r >= np.percentile(r, 97.0)
        tip = (float(xs[sel][far].mean()), float(ys[sel][far].mean()))
        # Without a prediction the blob reaching furthest out wins; with one,
        # the blob whose far end is nearest the prediction.
        score = -float(r.max()) if expected_px is None else             math.hypot(tip[0] - expected_px[0], tip[1] - expected_px[1])
        if best is None or score < best[0]:
            best = (score, tip)
    return None if best is None else best[1]


@dataclass
class Calibration:
    P: np.ndarray
    tool_mm: float
    rms_px: float
    max_px: float
    rms_mm: float                 # reprojection error scaled to the floor plane
    samples: int
    rejected: int


def fit(samples: Sequence[Sample], arm: ArmGeometry,
        tool_candidates: Optional[Iterable[float]] = None,
        outlier_px: float = 12.0) -> Calibration:
    """Camera matrix and tool length from fingertip sightings.

    With ``tool_candidates`` the tool length is chosen by reprojection error;
    without, ``arm.tool_mm`` is trusted. One round of outlier rejection drops
    sightings that landed on a cable or a reflection.
    """
    if tool_candidates is None:
        tool_candidates = [arm.tool_mm]
    best: Optional[Calibration] = None
    for tool in tool_candidates:
        trial = replace(arm, tool_mm=float(tool))
        xyz = [trial.point_xyz(s.angles, "tip") for s in samples]
        pix = [s.pixel for s in samples]
        try:
            P = fit_camera(xyz, pix)
        except ValueError:
            continue
        err = reprojection_errors(P, xyz, pix)
        # Drop the worst sighting while it is clearly off, one at a time: a
        # single bad point bends the whole fit, so judging all the residuals
        # of the first fit at once would throw good points out with it.
        rejected = 0
        while err.max() > outlier_px and len(xyz) > 8 and rejected < len(samples) // 5:
            worst = int(err.argmax())
            xyz.pop(worst)
            pix.pop(worst)
            rejected += 1
            try:
                P = fit_camera(xyz, pix)
            except ValueError:
                break
            err = reprojection_errors(P, xyz, pix)
        rms = float(np.sqrt((err ** 2).mean()))
        # Pixels to millimetres at mid-height of the samples.
        zs = sorted(p[2] for p in xyz)
        mid = xyz[len(xyz) // 2]
        u, v = project(P, (mid[0], mid[1], zs[len(zs) // 2]))
        u2, v2 = project(P, (mid[0] + 10.0, mid[1], zs[len(zs) // 2]))
        px_per_mm = math.hypot(u2 - u, v2 - v) / 10.0
        cal = Calibration(P, float(tool), rms, float(err.max()), rms / max(1e-9, px_per_mm),
                          len(xyz), rejected)
        if best is None or cal.rms_px < best.rms_px:
            best = cal
    if best is None:
        raise ValueError("no camera could be fitted to the samples")
    return best


def leave_one_out_mm(samples: Sequence[Sample], arm: ArmGeometry) -> float:
    """Honest error: predict each sighting from a fit to all the others."""
    from .geometry import back_project
    errors = []
    for i, s in enumerate(samples):
        rest = [t for j, t in enumerate(samples) if j != i]
        try:
            P = fit_camera([arm.point_xyz(t.angles, "tip") for t in rest], [t.pixel for t in rest])
        except ValueError:
            continue
        x, y, z = arm.point_xyz(s.angles, "tip")
        bx, by = back_project(P, s.pixel, z)
        errors.append(math.hypot(bx - x, by - y))
    return float(np.sqrt(np.mean(np.square(errors)))) if errors else float("nan")


def save(path: str, cal: Calibration, extra: Optional[dict] = None) -> None:
    import json
    data = {"P": cal.P.tolist(), "tool_mm": cal.tool_mm, "rms_px": cal.rms_px,
            "max_px": cal.max_px, "rms_mm": cal.rms_mm, "samples": cal.samples,
            "rejected": cal.rejected}
    data.update(extra or {})
    with open(path, "w", encoding="ascii") as fh:
        json.dump(data, fh, indent=1)


def load(path: str) -> dict:
    import json
    with open(path, encoding="ascii") as fh:
        data = json.load(fh)
    data["P"] = np.asarray(data["P"], float)
    return data
