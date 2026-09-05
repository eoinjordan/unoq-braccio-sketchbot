"""Forward kinematics for the Braccio drawing arm.

This is the inverse of :mod:`sketch_artist.kinematics`: given the six servo
angles (integer degrees, exactly as sent over the ``M``/``S`` arm protocol) it
returns the pen-tip position in the arm/paper base frame, in millimetres.

It powers the software arm simulator (:mod:`sketch_artist.sim`), the IK/FK
round-trip tests, and the Gazebo bridge (which needs the same servo -> joint
mapping to pose the model).

The Braccio is a serial arm, so the elbow and wrist servos measure the bend
*relative to the previous link* (90 deg = in line with it) while the shoulder is
absolute. Undoing ``kinematics._servo`` gives those bends back::

    geometric_deg = (servo - offset) / sign
    theta1 = geometric(shoulder)                     # upper arm above horizontal
    theta2 = theta1 + geometric(elbow)               # forearm
    theta3 = theta2 + geometric(wrist_vertical)      # pen

and the tip is ``wrist_pen_mm`` along ``theta3`` from the wrist point. Servo
values that were clamped in the forward direction cannot be recovered, so a
round trip is exact only for poses whose servos land inside ``[0, 180]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

ServoTuple = Tuple[int, int, int, int, int, int]


@dataclass
class PenTip:
    x_mm: float
    y_mm: float
    z_mm: float

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x_mm, self.y_mm, self.z_mm)


class BraccioForwardKinematics:
    def __init__(self, workspace_cfg: dict):
        links = workspace_cfg["links"]
        self.base_height = float(links["base_height_mm"])
        self.l1 = float(links["shoulder_mm"])
        self.l2 = float(links["elbow_mm"])
        self.wrist_pen = float(links["wrist_pen_mm"])
        self.cal = workspace_cfg["servo_calibration"]

    def _geom_deg(self, joint: str, servo: float) -> float:
        c = self.cal[joint]
        sign = c.get("sign", 1)
        offset = c.get("offset", 90)
        if not sign:
            return 0.0
        return (servo - offset) / sign

    def joint_radians(self, angles: ServoTuple) -> Tuple[float, float, float, float]:
        """Return (base, theta1, theta2, theta3) in radians.

        ``theta1``/``theta2``/``theta3`` are the absolute elevations above
        horizontal of the upper arm, forearm and pen, accumulated through the
        serial chain.
        """
        base, shoulder, elbow, wrist_v = angles[0], angles[1], angles[2], angles[3]
        base_rad = math.radians(self._geom_deg("base", base))
        theta1 = math.radians(self._geom_deg("shoulder", shoulder))
        theta2 = theta1 + math.radians(self._geom_deg("elbow", elbow))
        theta3 = theta2 + math.radians(self._geom_deg("wrist_vertical", wrist_v))
        return base_rad, theta1, theta2, theta3

    def command_radians(self, angles: ServoTuple) -> Tuple[float, float, float, float, float, float]:
        """All six joint angles in radians, in URDF/Gazebo model order:
        ``(base, shoulder, elbow, wrist_vertical, wrist_rotation, gripper)``.

        These are the *joint* rotations the model needs, so the elbow and wrist
        stay relative; wrist_rotation and gripper are treated as neutral-at-90
        revolute joints (used only to pose the simulated model, not for the pen
        tip).
        """
        base, shoulder, elbow, wrist_v = angles[0], angles[1], angles[2], angles[3]
        return (
            math.radians(self._geom_deg("base", base)),
            math.radians(self._geom_deg("shoulder", shoulder)),
            math.radians(self._geom_deg("elbow", elbow)),
            math.radians(self._geom_deg("wrist_vertical", wrist_v)),
            math.radians(angles[4] - 90),
            math.radians(angles[5] - 90),
        )

    def solve(self, angles: ServoTuple) -> PenTip:
        """Return the pen-tip position (mm) for the six servo angles."""
        base, theta1, theta2, theta3 = self.joint_radians(angles)

        # Walk the chain in the (in-plane reach r, height) plane, starting at
        # the shoulder at (0, base_height).
        r = self.l1 * math.cos(theta1) + self.l2 * math.cos(theta2) \
            + self.wrist_pen * math.cos(theta3)
        height = self.base_height + self.l1 * math.sin(theta1) \
            + self.l2 * math.sin(theta2) + self.wrist_pen * math.sin(theta3)

        return PenTip(r * math.cos(base), r * math.sin(base), height)
