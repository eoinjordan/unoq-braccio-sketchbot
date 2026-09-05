"""Inverse kinematics for the Braccio drawing with a vertical pen.

The Braccio is treated as a planar 2-link arm (shoulder + elbow) that rotates
about a vertical base axis. The pen is kept vertical, so the wrist point sits
directly above the pen tip by ``wrist_pen_mm``.

    base_angle = atan2(Y, X)                 # which way to face
    r          = sqrt(X^2 + Y^2)             # in-plane reach to the tip
    W          = (r, Z + wrist_pen_mm)       # wrist point above the tip
    S          = (0, base_height_mm)         # shoulder point
    two-link law-of-cosines from S to W with links (shoulder_mm, elbow_mm)

That yields the *absolute* elevation of each link above horizontal (theta1 for
the upper arm, theta2 for the forearm, theta3 = -90 deg for the pen). The
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
from typing import Tuple

# The pen is held vertical, tip down: the last link's elevation above
# horizontal, in degrees.
PEN_ELEVATION_DEG = -90.0


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
        self.cal = workspace_cfg["servo_calibration"]
        self.gripper_down = int(workspace_cfg["pen"]["down_gripper"])
        # Decimal places kept on every emitted servo angle. 0 restores the old
        # whole-degree protocol for firmware that cannot accept fractions.
        self.decimals = int(
            workspace_cfg.get("motion", {}).get("servo_decimals", 1))

    def link_elevations(self, x_mm: float, y_mm: float,
                        z_mm: float) -> Tuple[float, float, float]:
        """Return (base, theta1, theta2) in radians for a pen tip at (x, y, z).

        ``theta1``/``theta2`` are the absolute elevations of the upper arm and
        forearm above horizontal; ``base`` is the rotation about the vertical.
        """
        base = math.atan2(y_mm, x_mm)
        r = math.hypot(x_mm, y_mm)

        # Wrist point sits above the pen tip (pen is vertical).
        dx = r
        dy = z_mm + self.wrist_pen - self.base_height
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

    def solve(self, x_mm: float, y_mm: float, z_mm: float,
              gripper: int | None = None, strict: bool = False) -> ServoAngles:
        """Return servo angles that place the pen tip at (x, y, z) in mm.

        With ``strict`` the pose is rejected (``UnreachableError``) when a servo
        would have to be clamped into range, instead of silently drawing a
        distorted stroke.
        """
        base, theta1, theta2 = self.link_elevations(x_mm, y_mm, z_mm)
        theta3 = math.radians(PEN_ELEVATION_DEG)

        raw = {
            "base": self._servo("base", math.degrees(base)),
            "shoulder": self._servo("shoulder", math.degrees(theta1)),
            # Elbow and wrist servos measure the bend from the previous link.
            "elbow": self._servo("elbow", math.degrees(theta2 - theta1)),
            "wrist_vertical": self._servo("wrist_vertical",
                                          math.degrees(theta3 - theta2)),
        }
        if strict:
            for joint, value in raw.items():
                if not (0.0 <= value <= 180.0):
                    raise UnreachableError(
                        f"Target ({x_mm:.1f}, {y_mm:.1f}, {z_mm:.1f}) mm needs "
                        f"{joint} servo {value:.1f} deg, outside 0-180"
                    )

        g = self.gripper_down if gripper is None else int(gripper)
        return ServoAngles(
            base=_clamp_servo(raw["base"], self.decimals),
            shoulder=_clamp_servo(raw["shoulder"], self.decimals),
            elbow=_clamp_servo(raw["elbow"], self.decimals),
            wrist_vertical=_clamp_servo(raw["wrist_vertical"], self.decimals),
            wrist_rotation=float(self.cal["wrist_rotation"].get("fixed", 90)),
            gripper=float(max(0, min(180, g))),
        )

    def _servo(self, joint: str, geometric_deg: float) -> float:
        """Servo degrees for a joint, before clamping into the 0-180 range."""
        c = self.cal[joint]
        return c.get("offset", 90) + c.get("sign", 1) * geometric_deg


def _clamp_servo(value: float, decimals: int = 1) -> float:
    """Clamp into the 0-180 servo range, keeping ``decimals`` places.

    ``decimals=0`` returns a whole degree (as a float) and reproduces the
    original behaviour exactly.
    """
    return round(max(0.0, min(180.0, value)), decimals)
