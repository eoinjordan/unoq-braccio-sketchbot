"""Let the arm work behind its base instead of in front of it.

The kinematics here reach forward: base servo 90 points at the work. A
Braccio folded into its rest pose points its gripper the other way, and a
bench is often laid out on that side. Rather than turn the base round, the
arm can lean over its own shoulder: shoulder, elbow and wrist each at
``180 - angle`` put every link in the mirror-image position, which is the
forward pose turned half a turn about the base axis. Wrist roll needs the
same treatment, because the half turn would otherwise leave the camera on
the under side of the gripper.

``MirroredArm`` wraps anything with ``move`` and ``status_angles`` and applies
that mapping in both directions. The controller above it keeps planning in
its usual forward frame; what it calls straight ahead is physically straight
behind. Left and right as the camera sees them are unchanged, because the
mapping is a rotation, not a reflection.

The servo ends swap with it. The rest pose (elbow and wrist at 180) reads as
elbow and wrist at 0 through the wrapper, so limits measured for forward
reach do not carry over; see ``arm.reach_behind`` in config/pick_place.yaml.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

MIRRORED_JOINTS = (1, 2, 3, 4)     # shoulder, elbow, wrist pitch, wrist roll


def mirror(angles: Sequence[float]) -> Tuple[float, ...]:
    """Forward-frame servo angles to behind-the-base ones, and back again."""
    return tuple(round(180.0 - float(a), 2) if i in MIRRORED_JOINTS else float(a)
                 for i, a in enumerate(angles))


class MirroredArm:
    def __init__(self, arm):
        self.arm = arm

    def move(self, angles: Sequence[float]):
        return self.arm.move(mirror(angles))

    def status_angles(self) -> Optional[Tuple[float, ...]]:
        angles = self.arm.status_angles()
        return None if angles is None else mirror(angles)

    def __getattr__(self, name):
        return getattr(self.arm, name)
