"""Forward kinematics for the Braccio drawing arm.

This is the inverse of :mod:`sketch_artist.kinematics`: given the six servo
angles (integer degrees, exactly as sent over the ``M``/``S`` arm protocol) it
returns the pen-tip position in the arm/paper base frame, in millimetres.

It powers the software arm simulator (:mod:`sketch_artist.sim`), the IK/FK
round-trip tests, and the Gazebo bridge (which needs the same servo -> joint
mapping to pose the model).

The pen is kept vertical, so the tip sits ``wrist_pen_mm`` directly below the
wrist point. The per-joint servo mapping in ``kinematics._map`` is::

    servo = clamp(round(offset + sign * geometric_deg), 0, 180)

which this module inverts as ``geometric_deg = (servo - offset) / sign``. Servo
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
        """Return geometric (base, shoulder, elbow, wrist_vertical) in radians."""
        base, shoulder, elbow, wrist_v = angles[0], angles[1], angles[2], angles[3]
        return (
            math.radians(self._geom_deg("base", base)),
            math.radians(self._geom_deg("shoulder", shoulder)),
            math.radians(self._geom_deg("elbow", elbow)),
            math.radians(self._geom_deg("wrist_vertical", wrist_v)),
        )

    def command_radians(self, angles: ServoTuple) -> Tuple[float, float, float, float, float, float]:
        """All six joint angles in radians, in URDF/Gazebo model order:
        ``(base, shoulder, elbow, wrist_vertical, wrist_rotation, gripper)``.

        The four planar joints use the geometric inverse; wrist_rotation and
        gripper are treated as neutral-at-90 revolute joints (used only to pose
        the simulated model, not for the pen tip).
        """
        base, shoulder, elbow, wrist_v = self.joint_radians(angles)
        wrist_rot = math.radians(angles[4] - 90)
        gripper = math.radians(angles[5] - 90)
        return (base, shoulder, elbow, wrist_v, wrist_rot, gripper)

    def solve(self, angles: ServoTuple) -> PenTip:
        """Return the pen-tip position (mm) for the six servo angles."""
        base, shoulder, elbow, _wrist_v = self.joint_radians(angles)

        # Two-link arm in the (in-plane reach r, height) plane, from the
        # shoulder at (0, base_height). shoulder/elbow are absolute link angles.
        dx = self.l1 * math.cos(shoulder) + self.l2 * math.cos(elbow)
        dy = self.l1 * math.sin(shoulder) + self.l2 * math.sin(elbow)

        r = dx
        wrist_height = self.base_height + dy
        z = wrist_height - self.wrist_pen
        x = r * math.cos(base)
        y = r * math.sin(base)
        return PenTip(x, y, z)
