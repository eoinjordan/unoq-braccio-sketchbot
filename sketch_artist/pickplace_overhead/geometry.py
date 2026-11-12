"""Arm and camera geometry for overhead pick and place. No hardware, no OpenCV.

Arm
---
The sketchbot kinematics reach forward of the base with a pen. Here the tool is
the gripper and the targets may lie behind the base, so the arm reaches over
its own shoulder (shoulder servo above 90). That pose is the mirror image of
the forward one: ``servo' = 180 - servo`` for shoulder, elbow and wrist, with
the base turned half a turn. ``solve`` picks the side from where the target is.

Servo conventions are the sketchbot's (see ``sketch_artist.kinematics``): the
shoulder reads its elevation above horizontal, elbow and wrist read the bend
from the previous link with 90 meaning in line.

Base frame: origin on the floor under the base axis, +x where base servo 90
points, +y where base servo 180 points, z up. Nothing here assumes which way
that is in the picture; the camera model absorbs it, mirror image included.

Camera
------
One fixed camera is a 3x4 projection matrix fitted to points whose base-frame
position is known because the arm was commanded there. A pixel then maps back
to the base frame on any horizontal plane, which is how a brick top seen in
the picture becomes a pick target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

Angles = Tuple[float, float, float, float, float, float]

REST_POSE: Angles = (90.0, 45.0, 180.0, 180.0, 90.0, 10.0)


class Unreachable(ValueError):
    """The target cannot be reached inside the joint limits."""


@dataclass
class ArmGeometry:
    base_height_mm: float = 92.0      # floor to shoulder axis
    upper_arm_mm: float = 125.0
    forearm_mm: float = 125.0
    # Wrist pitch axis to fingertips. 105 was read off a photo of the short
    # printed fingers; the stock Braccio gripper is longer. MEASURE IT.
    tool_mm: float = 105.0
    # Firmware clamps for base, shoulder, elbow, wrist pitch, wrist roll, jaws.
    limits: Tuple[Tuple[float, float], ...] = (
        (0, 180), (15, 165), (0, 180), (0, 180), (0, 180), (10, 110))
    # Keep the elbow and wrist a few degrees off their ends when solving.
    elbow_margin_deg: float = 3.0
    wrist_margin_deg: float = 0.0

    # -- forward ---------------------------------------------------------
    def chain(self, angles: Sequence[float]) -> dict:
        """Elbow, wrist and tip as (r, z) in the arm plane, r > 0 in front.

        Also the tool pitch in degrees above horizontal, measured on the side
        the tool is on.
        """
        t1 = math.radians(angles[1])
        t2 = t1 + math.radians(angles[2] - 90.0)
        t3 = t2 + math.radians(angles[3] - 90.0)
        er = self.upper_arm_mm * math.cos(t1)
        ez = self.base_height_mm + self.upper_arm_mm * math.sin(t1)
        wr = er + self.forearm_mm * math.cos(t2)
        wz = ez + self.forearm_mm * math.sin(t2)
        tr = wr + self.tool_mm * math.cos(t3)
        tz = wz + self.tool_mm * math.sin(t3)
        return {"elbow": (er, ez), "wrist": (wr, wz), "tip": (tr, tz), "pitch_deg": math.degrees(t3)}

    def point_xyz(self, angles: Sequence[float], name: str = "tip") -> Tuple[float, float, float]:
        """Base-frame position of the elbow, wrist or tip."""
        r, z = self.chain(angles)[name]
        yaw = math.radians(angles[0] - 90.0)
        return (r * math.cos(yaw), r * math.sin(yaw), z)

    # -- inverse ---------------------------------------------------------
    def planar(self, r: float, z: float, pitch_deg: float) -> Tuple[float, float, float]:
        """Forward-side shoulder, elbow, wrist servo angles for a tip at (r, z).

        ``pitch_deg`` is the tool elevation: -90 hangs straight down, 0 is
        level. Raises ``Unreachable`` outside the limits.
        """
        t3 = math.radians(pitch_deg)
        wx = r - self.tool_mm * math.cos(t3)
        wz = z - self.tool_mm * math.sin(t3) - self.base_height_mm
        d = math.hypot(wx, wz)
        l1, l2 = self.upper_arm_mm, self.forearm_mm
        if d > l1 + l2 - 1e-6 or d < abs(l1 - l2) + 1e-6:
            raise Unreachable("wrist point is %.0f mm from the shoulder" % d)
        internal = math.acos(max(-1.0, min(1.0, (l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2))))
        t1 = math.atan2(wz, wx) + math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
        t2 = t1 - (math.pi - internal)
        shoulder = math.degrees(t1)
        elbow = 90.0 + math.degrees(t2 - t1)
        wrist = 90.0 + math.degrees(t3 - t2)
        return shoulder, elbow, wrist

    def solve(self, x: float, y: float, z: float, pitch_deg: float = -90.0,
              wrist_roll: float = 90.0, jaws: float = 10.0) -> Angles:
        """Six servo angles placing the fingertips at base-frame (x, y, z)."""
        r = math.hypot(x, y)
        heading = math.degrees(math.atan2(y, x))          # -180..180, 0 is in front
        shoulder, elbow, wrist = self.planar(r, z, pitch_deg)
        # Judge the fold on the forward-side angles, where "too close" and
        # "too far" read the same whichever side the target is on.
        if elbow < self.elbow_margin_deg:
            raise Unreachable("elbow would fold past its end (%.0f deg): too close or too high" % elbow)
        if wrist < self.wrist_margin_deg:
            raise Unreachable("wrist would fold past its end (%.0f deg): too close or too high" % wrist)
        if elbow > 180.0 or wrist > 180.0:
            raise Unreachable("elbow %.0f / wrist %.0f past 180" % (elbow, wrist))
        if -90.0 <= heading <= 90.0:
            base = 90.0 + heading
        else:                                             # behind: lean over the shoulder
            base = 90.0 + (heading - 180.0 if heading > 0 else heading + 180.0)
            shoulder, elbow, wrist = 180.0 - shoulder, 180.0 - elbow, 180.0 - wrist
        angles = (base, shoulder, elbow, wrist, float(wrist_roll), float(jaws))
        self.check_limits(angles)
        return tuple(round(a, 1) for a in angles)       # type: ignore[return-value]

    def solve_any_pitch(self, x: float, y: float, z: float,
                        pitches: Iterable[float] = (-90, -85, -80, -75, -70, -65, -60),
                        **kw) -> Tuple[Angles, float]:
        """First reachable pose over a list of tool pitches, steepest first."""
        last: Optional[Exception] = None
        for pitch in pitches:
            try:
                return self.solve(x, y, z, pitch_deg=pitch, **kw), float(pitch)
            except Unreachable as exc:
                last = exc
        raise Unreachable("no pitch reaches (%.0f, %.0f, %.0f): %s" % (x, y, z, last))

    def check_limits(self, angles: Sequence[float], solving: bool = False) -> None:
        names = ("base", "shoulder", "elbow", "wrist", "wrist_roll", "jaws")
        margins = (0.0, 0.0, self.elbow_margin_deg, self.wrist_margin_deg, 0.0, 0.0) if solving \
            else (0.0,) * 6
        for name, value, (lo, hi), m in zip(names, angles, self.limits, margins):
            if not (lo + m - 1e-9 <= value <= hi - m + 1e-9):
                raise Unreachable("%s servo %.1f outside %g-%g" % (name, value, lo + m, hi - m))


def interpolate(a: Sequence[float], b: Sequence[float], max_step_deg: float) -> List[Angles]:
    """Joint-space steps from a to b, none moving any joint more than the step."""
    span = max(abs(q - p) for p, q in zip(a, b))
    n = max(1, int(math.ceil(span / max_step_deg - 1e-9)))
    return [tuple(p + (q - p) * i / n for p, q in zip(a, b)) for i in range(1, n + 1)]  # type: ignore[misc]


# -- keep-out volumes -------------------------------------------------------

def point_in_polygon(x: float, y: float, poly: Sequence[Sequence[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polygon_distance(x: float, y: float, poly: Sequence[Sequence[float]]) -> float:
    """Distance to the polygon; zero inside it."""
    if point_in_polygon(x, y, poly):
        return 0.0
    n = len(poly)
    return min(_segment_distance(x, y, *poly[i], *poly[(i + 1) % n]) for i in range(n))


@dataclass
class KeepOut:
    """A prism the tool may not enter: a floor-plane polygon up to a height."""
    name: str
    polygon_xy: Sequence[Sequence[float]]
    top_mm: float
    margin_mm: float = 0.0

    def violated(self, x: float, y: float, z: float) -> bool:
        return z < self.top_mm and polygon_distance(x, y, self.polygon_xy) <= self.margin_mm


@dataclass
class Envelope:
    """Everything a commanded pose is checked against before it is sent."""
    arm: ArmGeometry
    floor_clearance_mm: float = 30.0          # lowest the fingertips may go
    joint_clearance_mm: float = 60.0          # lowest the elbow and wrist may go
    keep_outs: List[KeepOut] = field(default_factory=list)
    # Base servo range the arm may use; keeps it off the side where people sit.
    base_range: Tuple[float, float] = (0.0, 180.0)
    # Largest reach in front of the base (toward base servo 90's heading), mm.
    max_front_reach_mm: float = 1e9

    def violation(self, angles: Sequence[float], floor_clearance_mm: Optional[float] = None) -> Optional[str]:
        try:
            self.arm.check_limits(angles)
        except Unreachable as exc:
            return str(exc)
        if not (self.base_range[0] - 1e-9 <= angles[0] <= self.base_range[1] + 1e-9):
            return "base servo %.1f outside the allowed sector %g-%g" % (angles[0], *self.base_range)
        chain = self.arm.chain(angles)
        floor = self.floor_clearance_mm if floor_clearance_mm is None else floor_clearance_mm
        if chain["tip"][1] < floor - 1e-6:
            return "fingertips at z=%.0f mm, below the %.0f mm guard" % (chain["tip"][1], floor)
        for name in ("elbow", "wrist"):
            if chain[name][1] < self.joint_clearance_mm:
                return "%s at z=%.0f mm, too low" % (name, chain[name][1])
            if chain[name][0] > self.max_front_reach_mm:
                return "%s reaches %.0f mm in front of the base" % (name, chain[name][0])
        if chain["tip"][0] > self.max_front_reach_mm:
            return "fingertips reach %.0f mm in front of the base" % chain["tip"][0]
        x, y, z = self.arm.point_xyz(angles, "tip")
        for k in self.keep_outs:
            if k.violated(x, y, z):
                return "fingertips inside keep-out '%s' at z=%.0f mm" % (k.name, z)
        return None

    def check_path(self, start: Sequence[float], goal: Sequence[float],
                   floor_clearance_mm: Optional[float] = None) -> Optional[str]:
        """First violation along the joint-space line from start to goal."""
        for step in [tuple(start)] + interpolate(start, goal, 0.5):
            why = self.violation(step, floor_clearance_mm)
            if why:
                return why
        return None


# -- camera ---------------------------------------------------------------

def _normalise(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mean = points.mean(axis=0)
    scale = math.sqrt(points.shape[1]) / max(1e-12, np.sqrt(((points - mean) ** 2).sum(axis=1)).mean())
    dim = points.shape[1]
    T = np.eye(dim + 1)
    T[:dim, :dim] *= scale
    T[:dim, dim] = -scale * mean
    return (points - mean) * scale, T


def fit_camera(xyz: Sequence[Sequence[float]], pixels: Sequence[Sequence[float]]) -> np.ndarray:
    """Least-squares 3x4 projection matrix from six or more known points.

    The points must not all lie in one plane. Coordinates are conditioned
    first (Hartley normalisation), which matters with millimetres and pixels
    in the same system.
    """
    X = np.asarray(xyz, float)
    U = np.asarray(pixels, float)
    if X.shape[0] < 6 or X.shape[0] != U.shape[0]:
        raise ValueError("need six or more point pairs")
    Xn, TX = _normalise(X)
    Un, TU = _normalise(U)
    rows = []
    for (x, y, z), (u, v) in zip(Xn, Un):
        P = [x, y, z, 1.0]
        rows.append([*P, 0, 0, 0, 0, *[-u * p for p in P]])
        rows.append([0, 0, 0, 0, *P, *[-v * p for p in P]])
    _, s, vt = np.linalg.svd(np.asarray(rows))
    if s[-2] < 1e-9 * s[0]:
        raise ValueError("points are degenerate (all in one plane?)")
    Pn = vt[-1].reshape(3, 4)
    P = np.linalg.inv(TU) @ Pn @ TX
    return P / np.linalg.norm(P[2, :3])


def project(P: np.ndarray, xyz: Sequence[float]) -> Tuple[float, float]:
    h = P @ np.array([xyz[0], xyz[1], xyz[2], 1.0])
    return float(h[0] / h[2]), float(h[1] / h[2])


def back_project(P: np.ndarray, pixel: Sequence[float], z: float) -> Tuple[float, float]:
    """Base-frame (x, y) of the point on the plane at height z seen at pixel."""
    u, v = pixel
    A = np.array([[P[0, 0] - u * P[2, 0], P[0, 1] - u * P[2, 1]],
                  [P[1, 0] - v * P[2, 0], P[1, 1] - v * P[2, 1]]])
    b = -np.array([(P[0, 2] - u * P[2, 2]) * z + P[0, 3] - u * P[2, 3],
                   (P[1, 2] - v * P[2, 2]) * z + P[1, 3] - v * P[2, 3]])
    x, y = np.linalg.solve(A, b)
    return float(x), float(y)


def camera_centre(P: np.ndarray) -> Tuple[float, float, float]:
    _, _, vt = np.linalg.svd(P)
    c = vt[-1]
    return float(c[0] / c[3]), float(c[1] / c[3]), float(c[2] / c[3])


def reprojection_errors(P: np.ndarray, xyz, pixels) -> np.ndarray:
    return np.array([math.hypot(*(np.array(project(P, p)) - np.array(q))) for p, q in zip(xyz, pixels)])


def mm_per_pixel(P: np.ndarray, pixel: Sequence[float], z: float) -> float:
    """Local scale on the plane at height z around a pixel."""
    x0, y0 = back_project(P, pixel, z)
    x1, y1 = back_project(P, (pixel[0] + 10.0, pixel[1]), z)
    return math.hypot(x1 - x0, y1 - y0) / 10.0


def nominal_camera(base_px: Sequence[float], px_per_mm: float, front_angle_deg: float,
                   height_mm: float, nadir_px: Sequence[float], mirrored: bool = True) -> np.ndarray:
    """A camera looking straight down, built from a few numbers read off a frame.

    Good enough to dry-run a plan before a real calibration, nothing more.
    ``front_angle_deg`` is the on-screen direction (counter-clockwise from
    image +x) of the base frame's +x axis. ``mirrored`` is True when base
    frame +y lies clockwise of +x on screen.
    """
    f = px_per_mm * height_mm
    a = math.radians(front_angle_deg)
    ex = np.array([math.cos(a), -math.sin(a)])              # image direction of +x
    ey = np.array([math.sin(a), math.cos(a)]) if mirrored else np.array([-math.sin(a), -math.cos(a)])
    # Camera position over the floor, from where the base lands in the image.
    d = (np.asarray(nadir_px, float) - np.asarray(base_px, float)) / px_per_mm
    M = np.column_stack([ex, ey])
    cx, cy = np.linalg.solve(M, d)
    R = np.array([[ex[0], ey[0], 0.0], [ex[1], ey[1], 0.0], [0.0, 0.0, -1.0]])
    K = np.array([[f, 0, nadir_px[0]], [0, f, nadir_px[1]], [0, 0, 1.0]])
    C = np.array([cx, cy, height_mm])
    P = K @ np.column_stack([R, -R @ C])
    return P / np.linalg.norm(P[2, :3])


def tool_length_from_image(elbow_px, wrist_px, tip_px, forearm_mm: float = 125.0) -> float:
    """Tool length from one frame of the arm with forearm and tool level.

    With both links level and in line they are at the same height, so their
    pixel lengths are in the same ratio as their real lengths and the camera
    height drops out.
    """
    fore = math.hypot(wrist_px[0] - elbow_px[0], wrist_px[1] - elbow_px[1])
    tool = math.hypot(tip_px[0] - wrist_px[0], tip_px[1] - wrist_px[1])
    if fore < 1.0:
        raise ValueError("elbow and wrist coincide in the image")
    return forearm_mm * tool / fore
