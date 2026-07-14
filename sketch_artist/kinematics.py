"""Inverse kinematics for the Braccio drawing with a vertical pen.

The Braccio is treated as a planar 2-link arm (shoulder + elbow) that rotates
about a vertical base axis. The pen is kept vertical, so the wrist point sits
directly above the pen tip by ``wrist_pen_mm``.

    base_angle = atan2(Y, X)                 # which way to face
    r          = sqrt(X^2 + Y^2)             # in-plane reach to the tip
    W          = (r, Z + wrist_pen_mm)       # wrist point above the tip
    S          = (0, base_height_mm)         # shoulder point
    two-link law-of-cosines from S to W with links (shoulder_mm, elbow_mm)

Geometric joint angles are converted to servo degrees using the per-joint
offset/sign in ``config/workspace.yaml`` — these MUST be tuned to your servos'
zero positions (see docs/calibration.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple


class UnreachableError(ValueError):
    """Raised when a target point is outside the arm's workspace."""


@dataclass
class ServoAngles:
    base: int
    shoulder: int
    elbow: int
    wrist_vertical: int
    wrist_rotation: int
    gripper: int

    def as_tuple(self) -> Tuple[int, int, int, int, int, int]:
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

    def solve(self, x_mm: float, y_mm: float, z_mm: float,
              gripper: int | None = None) -> ServoAngles:
        """Return servo angles that place the pen tip at (x, y, z) in mm."""
        base = math.atan2(y_mm, x_mm)
        r = math.hypot(x_mm, y_mm)

        # Wrist point sits above the pen tip (pen is vertical).
        wx = r
        wy = z_mm + self.wrist_pen

        # Vector from shoulder to wrist.
        dx = wx
        dy = wy - self.base_height
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
        shoulder = math.atan2(dy, dx) + math.acos(cos_sh)

        elbow = shoulder - (math.pi - elbow_internal)

        # Keep the pen vertical: wrist compensates shoulder+elbow so the last
        # link points straight down.
        wrist_vertical = -(shoulder + (elbow - shoulder)) - math.pi / 2

        g = self.gripper_down if gripper is None else int(gripper)
        return ServoAngles(
            base=self._map("base", math.degrees(base)),
            shoulder=self._map("shoulder", math.degrees(shoulder)),
            elbow=self._map("elbow", math.degrees(elbow)),
            wrist_vertical=self._map("wrist_vertical", math.degrees(wrist_vertical)),
            wrist_rotation=int(self.cal["wrist_rotation"].get("fixed", 90)),
            gripper=max(0, min(180, g)),
        )

    def _map(self, joint: str, geometric_deg: float) -> int:
        c = self.cal[joint]
        servo = c.get("offset", 90) + c.get("sign", 1) * geometric_deg
        return int(round(max(0, min(180, servo))))
