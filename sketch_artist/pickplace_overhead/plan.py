"""Turn detections into checked pick-and-place waypoints. No hardware.

Every waypoint is six servo angles. Between waypoints the arm moves on a
straight line in joint space, and that whole line is checked against the
envelope (joint limits, floor guard, keep-out volumes, allowed base sector)
before a brick is called reachable. A brick whose plan fails any check is
reported with the reason and never attempted.

Between the floor and the bin the arm folds into the rest posture, which
holds the tool high and close to the base, and only then turns. Turning
while stretched out is what sweeps things off the floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .detect import BIN, BRICK_LABELS, Detection, box_corners
from .geometry import (Angles, ArmGeometry, Envelope, KeepOut, REST_POSE, Unreachable,
                       back_project)


@dataclass
class PickConfig:
    brick_top_mm: float = 19.0        # height of the face the camera sees
    grasp_z_mm: float = 8.0           # fingertip height when the jaws close
    hover_z_mm: float = 50.0          # fingertip height over a brick before descending
    floor_guard_mm: float = 40.0      # lowest fingertip height outside a descent
    bin_rim_mm: float = 80.0          # height of the bin wall: MEASURE IT
    bin_margin_mm: float = 25.0       # keep-out margin around and above the rim
    release_above_rim_mm: float = 35.0
    jaws_open: float = 10.0
    jaws_closed: float = 60.0
    # Jaw line (fingertip to fingertip) relative to the arm's reach direction
    # at wrist roll 90 with the tool hanging down, and which way roll turns it.
    jaw_line_offset_deg: float = 90.0
    jaw_roll_sign: float = 1.0
    max_grasp_width_mm: float = 45.0  # widest thing the open jaws go around
    column_step_mm: float = 14.0      # spacing of poses between hover and grasp
    # Tool pitch range for a pick; below -90 the fingertips tuck toward the base.
    pitch_min_deg: float = -100.0
    pitch_max_deg: float = -30.0
    pitch_step_deg: float = 2.5
    max_pitch_change_deg: float = 12.0   # between neighbouring poses of a column


@dataclass
class Waypoint:
    label: str
    angles: Angles
    floor_guard_mm: float
    verify: str = ""                  # what the camera should confirm afterwards


@dataclass
class BrickPlan:
    index: int
    detection: Detection
    xy_mm: Tuple[float, float]
    reach_mm: float
    width_mm: float
    reachable: bool
    reason: str = ""
    pitch_deg: float = -90.0
    wrist_roll: float = 90.0
    waypoints: List[Waypoint] = field(default_factory=list)


def carry_pose(base: float, jaws: float) -> Angles:
    """The rest posture turned to a heading: tool folded high over the base."""
    return (float(base), REST_POSE[1], REST_POSE[2], REST_POSE[3], REST_POSE[4], float(jaws))


def bin_geometry(P: np.ndarray, bin_det: Detection, cfg: PickConfig):
    """Bin centre and rim outline in the base frame, from its outline in the image."""
    centre = back_project(P, (bin_det.x_px, bin_det.y_px), cfg.bin_rim_mm)
    outline = [back_project(P, tuple(c), cfg.bin_rim_mm) for c in box_corners(bin_det)]
    return centre, outline


def bin_keep_out(P: np.ndarray, bin_det: Detection, cfg: PickConfig) -> KeepOut:
    _, outline = bin_geometry(P, bin_det, cfg)
    return KeepOut("bin", outline, cfg.bin_rim_mm + cfg.bin_margin_mm, cfg.bin_margin_mm)


def brick_axis_deg(P: np.ndarray, det: Detection, z: float) -> float:
    """Long-axis direction of a brick in the base frame, degrees."""
    t = math.radians(-det.angle_deg)
    half = max(5.0, det.length_px / 2.0)
    a = back_project(P, (det.x_px - half * math.cos(t), det.y_px - half * math.sin(t)), z)
    b = back_project(P, (det.x_px + half * math.cos(t), det.y_px + half * math.sin(t)), z)
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def wrist_roll_for(axis_deg: float, reach_heading_deg: float, cfg: PickConfig) -> float:
    """Wrist roll that puts the jaw line across a brick's long axis."""
    want = axis_deg + 90.0
    delta = want - (reach_heading_deg + cfg.jaw_line_offset_deg)
    delta = (delta + 90.0) % 180.0 - 90.0           # a jaw line has no direction
    roll = 90.0 + cfg.jaw_roll_sign * delta
    return round(min(180.0, max(0.0, roll)), 1)


def steepest(arm: ArmGeometry, x: float, y: float, z: float, roll: float, jaws: float,
             cfg: PickConfig, near_pitch: Optional[float] = None) -> Tuple[Angles, float]:
    """Pose at (x, y, z) with the tool as close to straight down as it goes.

    With ``near_pitch`` the search stays within ``max_pitch_change_deg`` of it,
    so neighbouring poses of a column do not swing the tool about.
    """
    n = int(round((cfg.pitch_max_deg - cfg.pitch_min_deg) / cfg.pitch_step_deg))
    pitches = [cfg.pitch_min_deg + i * cfg.pitch_step_deg for i in range(n + 1)]
    if near_pitch is not None:
        pitches = [p for p in pitches if abs(p - near_pitch) <= cfg.max_pitch_change_deg + 1e-9]
    pitches.sort(key=lambda p: abs(p + 90.0))
    last: Optional[Exception] = None
    for pitch in pitches:
        try:
            return arm.solve(x, y, z, pitch, roll, jaws), pitch
        except Unreachable as exc:
            last = last or exc
    raise Unreachable(str(last) if last else "no pitch to try")


def plan_brick(index: int, det: Detection, P: np.ndarray, arm: ArmGeometry, env: Envelope,
               cfg: PickConfig, bin_det: Optional[Detection]) -> BrickPlan:
    x, y = back_project(P, (det.x_px, det.y_px), cfg.brick_top_mm)
    reach = math.hypot(x, y)
    a = back_project(P, (det.x_px, det.y_px), cfg.brick_top_mm)
    b = back_project(P, (det.x_px + 1.0, det.y_px), cfg.brick_top_mm)
    scale = math.hypot(b[0] - a[0], b[1] - a[1])
    width = det.width_px * scale
    plan = BrickPlan(index, det, (round(x, 1), round(y, 1)), round(reach, 1), round(width, 1), False)

    if bin_det is None:
        plan.reason = "no bin detected"
        return plan
    if det.width_px > 0 and width > cfg.max_grasp_width_mm:
        plan.reason = "narrow side %.0f mm is wider than the jaws open" % width
        return plan
    for k in env.keep_outs:
        if k.violated(x, y, cfg.grasp_z_mm):
            plan.reason = "inside keep-out '%s'" % k.name
            return plan

    heading = math.degrees(math.atan2(y, x))
    roll = wrist_roll_for(brick_axis_deg(P, det, cfg.brick_top_mm), heading, cfg) \
        if det.length_px > 0 else 90.0
    plan.wrist_roll = roll

    # A column of poses straight above the brick, one every few millimetres,
    # each at the steepest tool pitch the joints allow at that height. With a
    # long gripper the usable pitch changes with height, so one fixed pitch
    # from hover to grasp does not exist for most of the floor.
    column: List[Tuple[float, Angles, float]] = []
    z = cfg.grasp_z_mm
    previous_pitch: Optional[float] = None
    try:
        while True:
            angles, pitch = steepest(arm, x, y, z, roll, cfg.jaws_open, cfg, previous_pitch)
            column.append((z, angles, pitch))
            previous_pitch = pitch
            if z >= cfg.hover_z_mm - 1e-6:
                break
            z = min(cfg.hover_z_mm, z + cfg.column_step_mm)
    except Unreachable as exc:
        plan.reason = "out of reach at %.0f mm, z=%.0f: %s" % (reach, z, exc)
        return plan
    grasp, plan.pitch_deg = column[0][1], column[0][2]
    hover = column[-1][1]

    (bx, by), _ = bin_geometry(P, bin_det, cfg)
    release_z = cfg.bin_rim_mm + cfg.release_above_rim_mm
    try:
        release, _ = steepest(arm, bx, by, release_z, 90.0, cfg.jaws_closed, cfg)
    except Unreachable as exc:
        plan.reason = "bin out of reach: %s" % exc
        return plan

    closed = lambda p: p[:5] + (cfg.jaws_closed,)        # noqa: E731
    opened = lambda p: p[:5] + (cfg.jaws_open,)          # noqa: E731
    g = cfg.floor_guard_mm
    wps = [
        Waypoint("turn to brick", carry_pose(grasp[0], cfg.jaws_open), g, "arm"),
        Waypoint("hover over brick", hover, g, "arm over brick"),
    ]
    low = cfg.grasp_z_mm - 0.5
    for z, angles, _ in reversed(column[:-1]):
        wps.append(Waypoint("descend to %.0f mm" % z, angles, low,
                            "brick not pushed" if z == cfg.grasp_z_mm else ""))
    wps.append(Waypoint("close jaws", closed(grasp), low, ""))
    for z, angles, _ in column[1:]:
        wps.append(Waypoint("lift to %.0f mm" % z, closed(angles), low,
                            "brick left the floor" if z >= cfg.hover_z_mm - 1e-6 else ""))
    wps += [
        Waypoint("fold up", carry_pose(grasp[0], cfg.jaws_closed), g, ""),
        Waypoint("turn to bin", carry_pose(release[0], cfg.jaws_closed), g, "arm"),
        Waypoint("over bin", release, g, "arm over bin"),
        Waypoint("open jaws", opened(release), g, "brick in bin"),
        Waypoint("fold up", carry_pose(release[0], cfg.jaws_open), g, ""),
        Waypoint("park", REST_POSE[:5] + (cfg.jaws_open,), g, "arm parked"),
    ]
    previous: Angles = REST_POSE[:5] + (cfg.jaws_open,)
    for wp in wps:
        fault = env.check_path(previous, wp.angles, wp.floor_guard_mm)
        if fault:
            plan.reason = "%s: %s" % (wp.label, fault)
            return plan
        previous = wp.angles
    plan.reachable = True
    plan.waypoints = wps
    return plan


def plan_all(detections: Sequence[Detection], P: np.ndarray, arm: ArmGeometry,
             cfg: PickConfig, base_range: Tuple[float, float] = (0.0, 180.0),
             extra_keep_outs: Sequence[KeepOut] = (),
             max_front_reach_mm: float = 1e9) -> Tuple[List[BrickPlan], Envelope]:
    """Plan every brick. Nearest first, so the arm never reaches over one."""
    bins = [d for d in detections if d.label == BIN]
    bin_det = max(bins, key=lambda d: d.area_px) if bins else None
    env = Envelope(arm, floor_clearance_mm=cfg.floor_guard_mm, base_range=base_range,
                   keep_outs=list(extra_keep_outs), max_front_reach_mm=max_front_reach_mm)
    if bin_det is not None:
        env.keep_outs.append(bin_keep_out(P, bin_det, cfg))
    plans = [plan_brick(i, d, P, arm, env, cfg, bin_det)
             for i, d in enumerate(detections) if d.label in BRICK_LABELS]
    plans.sort(key=lambda p: p.reach_mm)
    return plans, env


def describe(plans: Sequence[BrickPlan]) -> str:
    lines = ["idx label         x_mm   y_mm reach width  pitch roll  result"]
    for p in plans:
        lines.append("%3d %-12s %6.0f %6.0f %5.0f %5.0f  %5.0f %4.0f  %s" % (
            p.index, p.detection.label, p.xy_mm[0], p.xy_mm[1], p.reach_mm, p.width_mm,
            p.pitch_deg, p.wrist_roll, "reachable" if p.reachable else "SKIP: " + p.reason))
    return "\n".join(lines)
