"""Where the gripper-top camera is and what it sees, from the servo angles.

The camera holders in ``hardware/pencil-grip`` stand a camera on the flat
face of the gripper block. The lens is on the gripper's plane of symmetry,
``height_mm`` above the gripper centre line, looking forward along the
fingers and tilted ``tilt_deg`` towards the centre line so that the two meet
at the holder's pick distance. It turns with wrist roll.

This module adds only that fixed offset to the arm's existing forward
kinematics (:mod:`sketch_artist.fk`, run with the gripper as the tool); it
has no joint maths of its own. From six servo angles it gives:

* the lens position and the camera axes in the arm base frame;
* :meth:`GripperCamera.project`, a base-frame point to image coordinates
  (pinhole, no lens distortion);
* :meth:`GripperCamera.ray_to_plane`, an image point back onto a horizontal
  plane such as the desk. This is how a camera with no depth sensor places a
  brick: the brick is known to be lying on the desk;
* :meth:`GripperCamera.aim_point`, the point where the gripper centre line
  meets such a plane, and where that point appears in the picture. Bringing
  a brick to that image point puts it straight ahead of the claws.

Image coordinates are the detector's: 0..1, origin top left, x to the right
and y down. Lengths are millimetres, angles degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .fk import BraccioForwardKinematics

Vec = Tuple[float, float, float]


def _add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + scale * b[0], a[1] + scale * b[1], a[2] + scale * b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _mix(a: Vec, wa: float, b: Vec, wb: float) -> Vec:
    return (wa * a[0] + wb * b[0], wa * a[1] + wb * b[1], wa * a[2] + wb * b[2])


def field_of_view(diagonal_deg: float, aspect: Sequence[float]) -> Tuple[float, float]:
    """Half-width and half-height of the picture at unit distance."""
    wide, high = float(aspect[0]), float(aspect[1])
    half_diagonal = math.tan(math.radians(diagonal_deg) / 2.0)
    diagonal = math.hypot(wide, high)
    return half_diagonal * wide / diagonal, half_diagonal * high / diagonal


@dataclass
class CameraPose:
    """The gripper and its camera in the arm base frame."""
    grasp: Vec          # the grasp point between the claws (the tool point)
    tool: Vec           # unit vector along the gripper centre line
    lens: Vec
    forward: Vec        # optical axis
    right: Vec          # towards the right of the picture
    up: Vec             # towards the top of the picture
    jaw: Vec            # unit vector across the claws, the way they close


class GripperCamera:
    """Pinhole model of a camera on top of the gripper.

    ``tool_workspace`` is the workspace with the gripper as the tool (see
    ``pick_place.tool_workspace``), ``tool`` and ``camera`` the blocks of the
    same names in ``config/pick_place.yaml``.
    """

    def __init__(self, tool_workspace: dict, tool: dict, camera: dict):
        self.fk = BraccioForwardKinematics(tool_workspace)
        self.length = float(tool_workspace["links"]["wrist_pen_mm"])
        self.lens_along = (float(tool["mount_from_wrist_mm"])
                           + float(camera["lens_from_mount_mm"]))
        self.height = float(camera["height_mm"])
        self.tilt = math.radians(float(camera["tilt_deg"]))
        self.half_w, self.half_h = field_of_view(
            float(camera["fov_diagonal_deg"]), camera.get("aspect", (4, 3)))
        self.image_rotation = math.radians(float(camera.get("image_rotation_deg", 0)))
        self.mirror = bool(camera.get("mirror", False))
        self.roll_zero = float(camera.get("roll_zero_deg", 0.0))
        self.roll_sign = float(camera.get("roll_sign", 1.0))

    def pose(self, angles: Sequence[float]) -> CameraPose:
        base, _, _, pitch = self.fk.joint_radians(tuple(angles))
        tip = self.fk.solve(tuple(angles))
        grasp = (tip.x_mm, tip.y_mm, tip.z_mm)
        radial = (math.cos(base), math.sin(base), 0.0)
        left = (-math.sin(base), math.cos(base), 0.0)
        vertical = (0.0, 0.0, 1.0)
        tool = _mix(radial, math.cos(pitch), vertical, math.sin(pitch))
        # The face of the gripper block that looks away from the base when
        # the gripper points outwards and down.
        outer = _mix(radial, -math.sin(pitch), vertical, math.cos(pitch))
        # Wrist roll carries the camera face round the centre line.
        turn = math.radians(self.roll_sign * (float(angles[4]) - self.roll_zero))
        face = _mix(outer, math.cos(turn), left, math.sin(turn))
        lens = _add(_add(grasp, tool, self.lens_along - self.length),
                    face, self.height)
        forward = _mix(tool, math.cos(self.tilt), face, -math.sin(self.tilt))
        holder_up = _mix(tool, math.sin(self.tilt), face, math.cos(self.tilt))
        holder_right = _cross(forward, holder_up)
        c, s = math.cos(self.image_rotation), math.sin(self.image_rotation)
        right = _mix(holder_right, c, holder_up, s)
        up = _mix(holder_right, -s, holder_up, c)
        return CameraPose(grasp, tool, lens, forward, right, up,
                          _cross(tool, face))

    def project(self, point: Vec, angles: Sequence[float],
                pose: Optional[CameraPose] = None) -> Optional[Tuple[float, float]]:
        """Image coordinates of a base-frame point, or None if it is behind
        the lens. The result may lie outside 0..1 (out of the picture)."""
        pose = pose or self.pose(angles)
        offset = (point[0] - pose.lens[0], point[1] - pose.lens[1],
                  point[2] - pose.lens[2])
        depth = _dot(offset, pose.forward)
        if depth <= 1.0:
            return None
        x = 0.5 + _dot(offset, pose.right) / depth / (2.0 * self.half_w)
        y = 0.5 - _dot(offset, pose.up) / depth / (2.0 * self.half_h)
        return ((1.0 - x) if self.mirror else x, y)

    def ray_to_plane(self, x: float, y: float, angles: Sequence[float],
                     plane_z: float,
                     pose: Optional[CameraPose] = None) -> Optional[Tuple[float, float]]:
        """Where the ray through an image point meets the plane z = plane_z,
        as base-frame (x, y). None if the ray does not reach the plane."""
        pose = pose or self.pose(angles)
        if self.mirror:
            x = 1.0 - x
        across = (x - 0.5) * 2.0 * self.half_w
        upward = (0.5 - y) * 2.0 * self.half_h
        ray = _add(_add(pose.forward, pose.right, across), pose.up, upward)
        if ray[2] >= -1e-6:
            return None
        travel = (plane_z - pose.lens[2]) / ray[2]
        if travel <= 0:
            return None
        return (pose.lens[0] + travel * ray[0], pose.lens[1] + travel * ray[1])

    def aim_point(self, angles: Sequence[float], plane_z: float,
                  pose: Optional[CameraPose] = None):
        """Where the gripper centre line meets the plane z = plane_z.

        Returns ``(image_xy, base_xy, distance)``: the point in the picture
        (None if out of sight), the point on the plane, and how far the
        grasp point still is from the plane along the centre line. Returns
        None when the gripper does not point down at the plane.
        """
        pose = pose or self.pose(angles)
        if pose.tool[2] >= -1e-6:
            return None
        distance = (plane_z - pose.grasp[2]) / pose.tool[2]
        point = _add(pose.grasp, pose.tool, distance)
        return (self.project(point, angles, pose), (point[0], point[1]),
                distance)

    def in_picture(self, image_xy, inset: float = 0.0) -> bool:
        return (image_xy is not None
                and inset <= image_xy[0] <= 1.0 - inset
                and inset <= image_xy[1] <= 1.0 - inset)
