"""Checks run on a camera frame after every move.

Three questions, each answered from two frames:

* did the base move?  The arm stands on a white printed sheet. Its outline is
  compared with the outline in a reference frame, ignoring the part of the
  picture the arm itself covers in either frame.
* did anything else change in the work zone?  A hand, a foot, a dragged
  cable or a knocked bin all show up as a changed region that the arm's own
  silhouette does not explain.
* is the picture usable at all?  A frame that lost focus says nothing.

None of this is a safety system. It stops a run early; it does not make the
arm safe to stand next to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .geometry import ArmGeometry, project


def sharpness(frame_bgr: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> float:
    """Variance of the Laplacian; falls by an order of magnitude out of focus."""
    grey = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if roi is not None:
        x0, y0, x1, y1 = roi
        grey = grey[y0:y1, x0:x1]
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def arm_mask(shape, P: np.ndarray, arm: ArmGeometry, angles: Sequence[float],
             thickness_px: int = 110, base_radius_px: int = 120) -> np.ndarray:
    """Pixels the arm can cover at a pose: a fat line along its links.

    Each joint is projected at its real height, so the mask leans the way the
    arm does in the picture. The floor point under every joint is joined in as
    well, which covers most of the shadow.
    """
    mask = np.zeros(shape[:2], np.uint8)
    base_floor = project(P, (0.0, 0.0, 0.0))
    shoulder = project(P, (0.0, 0.0, arm.base_height_mm))
    pts = [base_floor, shoulder]
    floor_pts = [base_floor]
    for name in ("elbow", "wrist", "tip"):
        x, y, z = arm.point_xyz(angles, name)
        pts.append(project(P, (x, y, z)))
        floor_pts.append(project(P, (x, y, 0.0)))
    for chain in (pts, floor_pts):
        arr = np.asarray(chain, np.int32).reshape(-1, 1, 2)
        cv2.polylines(mask, [arr], False, 255, thickness_px)
    for a, b in zip(pts[2:], floor_pts[1:]):
        cv2.line(mask, tuple(int(v) for v in a), tuple(int(v) for v in b), 255, thickness_px)
    cv2.circle(mask, tuple(int(v) for v in base_floor), base_radius_px, 255, -1)
    return mask


def sheet_mask(frame_bgr: np.ndarray, centre_px: Sequence[float], radius_px: float) -> np.ndarray:
    """White base sheet near the base: bluer than the floor, neutral, bright."""
    blurred = cv2.GaussianBlur(frame_bgr, (5, 5), 0)
    lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB).astype(np.float32)
    # Floor colour from the neighbourhood of the base, not the whole frame:
    # bags, feet and paper elsewhere in the picture must not move it.
    h, w = frame_bgr.shape[:2]
    reach = int(2.2 * radius_px)
    x0, x1 = max(0, int(centre_px[0]) - reach), min(w, int(centre_px[0]) + reach)
    y0, y1 = max(0, int(centre_px[1]) - reach), min(h, int(centre_px[1]) + reach)
    floor_b = float(np.median(lab[y0:y1, x0:x1, 2]))
    white = (lab[..., 2] < floor_b - 12.0) & (np.abs(lab[..., 1] - 128.0) < 9.0) \
        & (lab[..., 0] > 105.0) & (lab[..., 2] > 108.0)
    zone = np.zeros(frame_bgr.shape[:2], np.uint8)
    cv2.circle(zone, (int(centre_px[0]), int(centre_px[1])), int(radius_px), 255, -1)
    out = (white.astype(np.uint8) * 255) & zone
    return cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


@dataclass
class ShiftResult:
    moved: bool
    changed_px: int
    sheet_px: int
    fraction: float


def base_shift(ref_bgr: np.ndarray, frame_bgr: np.ndarray, centre_px: Sequence[float],
               radius_px: float, exclude: Optional[np.ndarray] = None,
               min_fraction: float = 0.15, min_px: int = 800) -> ShiftResult:
    """Compare the base sheet outline between a reference and a new frame.

    ``exclude`` masks out where the arm is in either frame. A sheet that slid
    or turned leaves a rim of pixels that are sheet in one frame and floor in
    the other; that rim, as a fraction of the visible sheet, is the measure.
    """
    a = sheet_mask(ref_bgr, centre_px, radius_px)
    b = sheet_mask(frame_bgr, centre_px, radius_px)
    return _shift_from_masks(a, b, exclude, min_fraction, min_px)


def _shift_from_masks(a: np.ndarray, b: np.ndarray, exclude: Optional[np.ndarray],
                      min_fraction: float, min_px: int) -> ShiftResult:
    if exclude is not None:
        keep = cv2.bitwise_not(exclude)
        a, b = a & keep, b & keep
    diff = cv2.bitwise_xor(a, b)
    # Edge flicker is one or two pixels wide; a real shift is a thick rim.
    diff = cv2.morphologyEx(diff, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    changed = int(np.count_nonzero(diff))
    sheet = int(np.count_nonzero(a))
    fraction = changed / max(1, sheet)
    return ShiftResult(changed >= min_px and fraction >= min_fraction, changed, sheet, fraction)


def changed_mask(ref_bgr: np.ndarray, frame_bgr: np.ndarray) -> np.ndarray:
    """Pixels that changed colour or brightness by more than a shadow does."""
    a = cv2.cvtColor(cv2.GaussianBlur(ref_bgr, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.int16)
    b = cv2.cvtColor(cv2.GaussianBlur(frame_bgr, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.int16)
    d = np.abs(a - b)
    return ((d[..., 0] > 55) | (d[..., 1] > 16) | (d[..., 2] > 20)).astype(np.uint8) * 255


@dataclass
class Region:
    area_px: int
    x_px: int
    y_px: int


def unexplained_changes(ref_bgr: np.ndarray, frame_bgr: np.ndarray, zone: np.ndarray,
                        explained: Optional[np.ndarray] = None, min_area: int = 1500) -> List[Region]:
    """Changed regions inside ``zone`` that ``explained`` does not cover."""
    ch = changed_mask(ref_bgr, frame_bgr) & zone
    if explained is not None:
        ch &= cv2.bitwise_not(explained)
    ch = cv2.morphologyEx(ch, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(ch)
    return [Region(int(stats[i, 4]), int(cent[i][0]), int(cent[i][1]))
            for i in range(1, n) if stats[i, 4] >= min_area]


def disc_mask(shape, centre_px: Sequence[float], radius_px: float,
              x_max: Optional[int] = None) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    cv2.circle(m, (int(centre_px[0]), int(centre_px[1])), int(radius_px), 255, -1)
    if x_max is not None:
        m[:, x_max:] = 0
    return m


def spots_mask(shape, spots: Sequence[Tuple[float, float, float]]) -> np.ndarray:
    """Discs (x, y, radius) where a change is expected, such as a lifted brick."""
    m = np.zeros(shape[:2], np.uint8)
    for x, y, r in spots:
        cv2.circle(m, (int(x), int(y)), int(r), 255, -1)
    return m


def orange_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Pixels the colour of the arm: redder and yellower than the floor.

    A red brick is redder still but less yellow, which is what keeps it out.
    """
    lab = cv2.cvtColor(cv2.GaussianBlur(frame_bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    floor = np.median(lab.reshape(-1, 3), axis=0)
    a, b = lab[..., 1], lab[..., 2]
    orange = (a - floor[1] > 18.0) & (b - floor[2] > 14.0) & ((a - b) <= -6.0)
    return orange.astype(np.uint8) * 255


@dataclass
class ArmSighting:
    ok: bool
    fractions: Tuple[float, ...]      # arm colour found at each checked point
    points_px: Tuple[Tuple[float, float], ...]


def arm_where_expected(frame_bgr: np.ndarray, P: np.ndarray, arm: ArmGeometry,
                       angles: Sequence[float], disc_px: int = 30,
                       min_fraction: float = 0.2, need: int = 2) -> ArmSighting:
    """Is the forearm where the commanded pose puts it?

    Three points along the middle of the forearm are projected into
    the frame and each is checked for arm colour. If the base has turned or
    slid, or a joint has stalled, the forearm is somewhere else and the
    points land on floor. The forearm is used because it is on top and
    visible from above in every pose.
    """
    orange = orange_mask(frame_bgr)
    e = np.array(arm.point_xyz(angles, "elbow"))
    w = np.array(arm.point_xyz(angles, "wrist"))
    points, fractions = [], []
    # The elbow end barely moves when the base turns and the wrist end
    # carries a black servo, so the points sit in the middle of the link.
    for t in (0.3, 0.5, 0.7):
        u, v = project(P, tuple(e + t * (w - e)))
        points.append((u, v))
        disc = np.zeros(orange.shape, np.uint8)
        cv2.circle(disc, (int(round(u)), int(round(v))), disc_px, 255, -1)
        total = int(np.count_nonzero(disc))
        fractions.append(float(np.count_nonzero(orange & disc)) / max(1, total))
    good = sum(f >= min_fraction for f in fractions)
    return ArmSighting(good >= need, tuple(round(f, 2) for f in fractions), tuple(points))


def grow(mask: np.ndarray, margin_px: int) -> np.ndarray:
    """Mask grown outward by a margin (done at quarter size for speed)."""
    small = cv2.resize(mask, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_NEAREST)
    k = max(1, int(margin_px / 4))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    grown = cv2.dilate(small, kernel)
    return cv2.resize(grown, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
