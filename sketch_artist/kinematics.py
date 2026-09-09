"""Inverse kinematics for the Braccio drawing with a (nearly) vertical pen.

The Braccio is treated as a planar 2-link arm (shoulder + elbow) that rotates
about a vertical base axis. The pen hangs from the wrist at a fixed elevation
theta3 = -90 deg + ``links.pen_tilt_deg``, so the wrist point sits
``wrist_pen_mm`` back along the pen from the tip:

    base_angle = atan2(Y, X)                 # which way to face
    r          = sqrt(X^2 + Y^2)             # in-plane reach to the tip
    W          = (r, Z) - wrist_pen_mm * (cos theta3, sin theta3)
    S          = (0, base_height_mm)         # shoulder point
    two-link law-of-cosines from S to W with links (shoulder_mm, elbow_mm)

With no tilt that is the familiar "wrist directly above the tip". A positive
tilt leans the TOP of the pen toward the base, the way a hand holds a pencil.
It exists because of a hard mechanical fact measured on the bench: with the
printed pen grip fitted, the wrist_vertical servo cannot fold below ~14 deg
(the finger pivot lands on the wrist housing), while a vertical 163 mm pen
over a sheet at base level needs 4-17 deg. Commanded into that dead zone the
servo just stalls, the pen hangs tilted anyway, and nothing the model says
about the tip height is true - which looks exactly like "the arm is stuck on
the first stroke". The wrist servo angle is (theta3 - theta2), so every degree
of tilt buys a degree of wrist clearance. See ``servo_limits`` in
workspace.yaml for how the stop itself is declared.

That yields the *absolute* elevation of each link above horizontal (theta1 for
the upper arm, theta2 for the forearm, theta3 for the pen). The
Braccio's servos are **serial revolute joints**, so only the shoulder is
absolute; the elbow and wrist servos measure the bend *relative to the previous
link*, and 90 deg means "in line with it":

    shoulder servo = offset + sign * theta1
    elbow servo    = offset + sign * (theta2 - theta1)
    wrist servo    = offset + sign * (theta3 - theta2)

Treating the elbow and wrist as absolute (as this module used to) produces
angles that no serial arm can follow, which is why drawings came out distorted
on both the real arm and in Gazebo.

Two consequences fall straight out of the servo ranges, and both are checked by
``scripts/check_workspace.py``:

* the elbow and wrist only bend +-90 deg from in line, so the shoulder-to-wrist
  distance has to stay between ``hypot(l1, l2)`` and ``l1 + l2``, and the
  forearm may never point above horizontal;
* a long pen pushes the wrist point high, which shrinks the drawable area fast.

Per-joint ``offset``/``sign`` come from ``config/workspace.yaml`` and MUST be
tuned to your servo zero positions (see docs/calibration.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Tuple

# The pen hangs tip down: the last link's elevation above horizontal, in
# degrees, before ``links.pen_tilt_deg`` is added.
PEN_ELEVATION_DEG = -90.0

# The range the firmware accepts for every servo. Real joints can stop short
# of it - see ``servo_limits`` in workspace.yaml and BraccioKinematics.limits.
SERVO_RANGE = (0.0, 180.0)
JOINTS = ("base", "shoulder", "elbow", "wrist_vertical")


class UnreachableError(ValueError):
    """Raised when a target point is outside the arm's workspace."""


@dataclass
class ServoAngles:
    """Six servo angles in degrees.

    These are floats on purpose. The paper sits ~175 mm from the base axis, so
    one degree of base rotation sweeps the pen tip about 3 mm -- a 40 mm sheet
    spans only 13 degrees. Rounded to whole degrees a portrait collapses into
    about a dozen addressable columns and comes out as rubble; a tenth of a
    degree is 0.3 mm and draws cleanly. See workspace.yaml motion.servo_decimals.
    """
    base: float
    shoulder: float
    elbow: float
    wrist_vertical: float
    wrist_rotation: float
    gripper: float

    def as_tuple(self) -> Tuple[float, float, float, float, float, float]:
        return (self.base, self.shoulder, self.elbow,
                self.wrist_vertical, self.wrist_rotation, self.gripper)


class BraccioKinematics:
    def __init__(self, workspace_cfg: dict):
        links = workspace_cfg["links"]
        self.base_height = float(links["base_height_mm"])
        self.l1 = float(links["shoulder_mm"])
        self.l2 = float(links["elbow_mm"])
        self.wrist_pen = float(links["wrist_pen_mm"])
        # Degrees the top of the pen leans toward the base; 0 = vertical.
        self.pen_tilt = float(links.get("pen_tilt_deg", 0.0))
        self.cal = workspace_cfg["servo_calibration"]
        self.gripper_down = int(workspace_cfg["pen"]["down_gripper"])
        # Decimal places kept on every emitted servo angle. 0 restores the old
        # whole-degree protocol for firmware that cannot accept fractions.
        self.decimals = int(
            workspace_cfg.get("motion", {}).get("servo_decimals", 1))
        # Per-joint servo limits, narrower than the 0-180 the firmware takes,
        # for joints that hit something before the servo does. A pose that
        # needs a joint outside its limits is unreachable in strict mode and
        # clamped to the limit otherwise - never commanded into the stop.
        self.limits: Dict[str, Tuple[float, float]] = {}
        cfg_limits = workspace_cfg.get("servo_limits") or {}
        for joint in JOINTS:
            lim = cfg_limits.get(joint) or {}
            lo = float(lim.get("min", SERVO_RANGE[0]))
            hi = float(lim.get("max", SERVO_RANGE[1]))
            if not (SERVO_RANGE[0] <= lo < hi <= SERVO_RANGE[1]):
                raise ValueError(
                    f"servo_limits.{joint}: min/max {lo:g}/{hi:g} must satisfy "
                    f"0 <= min < max <= 180")
            self.limits[joint] = (lo, hi)

    @property
    def pen_elevation(self) -> float:
        """The pen's elevation above horizontal, in radians (tip down)."""
        return math.radians(PEN_ELEVATION_DEG + self.pen_tilt)

    def link_elevations(self, x_mm: float, y_mm: float,
                        z_mm: float) -> Tuple[float, float, float]:
        """Return (base, theta1, theta2) in radians for a pen tip at (x, y, z).

        ``theta1``/``theta2`` are the absolute elevations of the upper arm and
        forearm above horizontal; ``base`` is the rotation about the vertical.
        """
        base = math.atan2(y_mm, x_mm)
        r = math.hypot(x_mm, y_mm)

        # Wrist point: back along the pen from the tip. With no tilt the pen
        # is vertical and this is simply (r, z + wrist_pen).
        theta3 = self.pen_elevation
        dx = r - self.wrist_pen * math.cos(theta3)
        dy = z_mm - self.wrist_pen * math.sin(theta3) - self.base_height
        d = math.hypot(dx, dy)

        if d > (self.l1 + self.l2) or d < abs(self.l1 - self.l2):
            raise UnreachableError(
                f"Target ({x_mm:.1f}, {y_mm:.1f}, {z_mm:.1f}) mm out of reach "
                f"(d={d:.1f}, span=[{abs(self.l1 - self.l2):.1f}, "
                f"{self.l1 + self.l2:.1f}])"
            )

        # Law of cosines for the elbow (elbow-up solution).
        cos_elbow = (self.l1 ** 2 + self.l2 ** 2 - d ** 2) / (2 * self.l1 * self.l2)
        cos_elbow = max(-1.0, min(1.0, cos_elbow))
        elbow_internal = math.acos(cos_elbow)

        # Shoulder angle = angle to wrist + interior triangle angle.
        cos_sh = (self.l1 ** 2 + d ** 2 - self.l2 ** 2) / (2 * self.l1 * d)
        cos_sh = max(-1.0, min(1.0, cos_sh))
        theta1 = math.atan2(dy, dx) + math.acos(cos_sh)

        # Forearm elevation: the upper arm's, closed down by the elbow bend.
        theta2 = theta1 - (math.pi - elbow_internal)
        return base, theta1, theta2

    def _raw(self, x_mm: float, y_mm: float, z_mm: float) -> Dict[str, float]:
        """Unclamped servo degrees for the four positioning joints."""
        base, theta1, theta2 = self.link_elevations(x_mm, y_mm, z_mm)
        theta3 = self.pen_elevation
        return {
            "base": self._servo("base", math.degrees(base)),
            "shoulder": self._servo("shoulder", math.degrees(theta1)),
            # Elbow and wrist servos measure the bend from the previous link.
            "elbow": self._servo("elbow", math.degrees(theta2 - theta1)),
            "wrist_vertical": self._servo("wrist_vertical",
                                          math.degrees(theta3 - theta2)),
        }

    def margin(self, x_mm: float, y_mm: float, z_mm: float) -> float:
        """Degrees of clearance to the nearest servo limit for a pose.

        Negative means the pose needs a joint outside its limits. Raises
        ``UnreachableError`` if the wrist point is beyond the arm entirely.
        """
        raw = self._raw(x_mm, y_mm, z_mm)
        return min(min(v - self.limits[j][0], self.limits[j][1] - v)
                   for j, v in raw.items())

    def solve(self, x_mm: float, y_mm: float, z_mm: float,
              gripper: int | None = None, strict: bool = False) -> ServoAngles:
        """Return servo angles that place the pen tip at (x, y, z) in mm.

        With ``strict`` the pose is rejected (``UnreachableError``) when a servo
        would have to be clamped into its limits, instead of silently drawing a
        distorted stroke.
        """
        raw = self._raw(x_mm, y_mm, z_mm)
        if strict:
            for joint, value in raw.items():
                lo, hi = self.limits[joint]
                if not (lo <= value <= hi):
                    raise UnreachableError(
                        f"Target ({x_mm:.1f}, {y_mm:.1f}, {z_mm:.1f}) mm needs "
                        f"{joint} servo {value:.1f} deg, outside {lo:g}-{hi:g}"
                    )

        g = self.gripper_down if gripper is None else int(gripper)

        def clamp(joint: str) -> float:
            lo, hi = self.limits[joint]
            return _clamp_servo(raw[joint], self.decimals, lo, hi)

        return ServoAngles(
            base=clamp("base"),
            shoulder=clamp("shoulder"),
            elbow=clamp("elbow"),
            wrist_vertical=clamp("wrist_vertical"),
            wrist_rotation=float(self.cal["wrist_rotation"].get("fixed", 90)),
            gripper=float(max(0, min(180, g))),
        )

    def _servo(self, joint: str, geometric_deg: float) -> float:
        """Servo degrees for a joint, before clamping into its limits."""
        c = self.cal[joint]
        return c.get("offset", 90) + c.get("sign", 1) * geometric_deg


def _clamp_servo(value: float, decimals: int = 1,
                 lo: float = SERVO_RANGE[0], hi: float = SERVO_RANGE[1]) -> float:
    """Clamp into ``[lo, hi]`` (default the 0-180 servo range), keeping
    ``decimals`` places.

    ``decimals=0`` returns a whole degree (as a float) and reproduces the
    original behaviour exactly.
    """
    return round(max(lo, min(hi, value)), decimals)
