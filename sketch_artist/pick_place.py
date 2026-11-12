"""Colour pick and place with the camera on top of the gripper.

The arm looks for 2x4 bricks of the enabled colours, picks them up one at a
time and drops them in the parts bin. The only sensor is the gripper-top
camera, whose detector reports where each brick and the bin are in the
picture (:mod:`sketch_artist.detections`). There is no depth sensor: bricks
are taken to lie on the desk and the bin's rim to be at a known height, and
the camera's place on the gripper is known (:mod:`sketch_artist.gripper_camera`).

One cycle:

1. **Search.** Sweep the base at a safe height until a brick of an enabled
   colour is seen above the confidence threshold in several frames running.
2. **Approach.** Move the gripper to bring the brick to the point in the
   picture where the gripper centre line meets the desk, step down along the
   centre line, and centre again, until the claws are a short way above the
   brick. The last stretch is blind (the brick slides out of the bottom of
   the picture) and is a straight move down the centre line.
3. **Grasp and lift**, then look at where the brick was. If it is still
   there the grasp failed and the approach is tried again.
4. **Place.** Find the bin the same way (label ``bin``), centre on it, lower
   towards the rim and open the claws. If the bin is not seen in time, use
   the fixed bin position from the configuration.
5. Return to the search height and carry on until a whole sweep finds
   nothing to pick.

Every move is planned before anything is sent and goes through
:class:`MotionGuard`: the existing inverse kinematics in strict mode, the
Studio's joint limits, a bounded step per command, and a floor that keeps
the claw tips above the desk by a margin. A stop request, or the camera
falling silent for longer than the watchdog allows, halts the arm where it
is. See docs/pick-place.md and docs/safety.md.

Kinematics, joint limits and the tool model are the existing ones
(``sketch_artist.kinematics``, ``sketch_artist.fk``, ``web.control``).
"""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import config as cfg
from .detections import BIN_LABEL, BRICK_LABELS, DetectionSource, Frame
from .fk import BraccioForwardKinematics
from .gripper_camera import GripperCamera
from .kinematics import BraccioKinematics, UnreachableError

LOG = logging.getLogger("sketchbot.pick_place")
CONFIG_NAME = "pick_place.yaml"

# Documented in config/pick_place.yaml, which must list the same values
# (tests/test_pick_place.py compares the two).
DEFAULTS = {
    "colours": ["red", "yellow", "white"],
    "strict_order": False,
    "confidence": 0.6,
    "confirm_frames": 3,
    "max_attempts": 3,
    "max_picks": 12,
    "watchdog_s": 1.0,
    "tool": {
        "pitch_deg": -60.0,
        "mount_from_wrist_mm": 90.0,
        "grasp_from_mount_mm": 57.0,
        "tip_from_mount_mm": 61.4,
        "wrist_rotation_deg": 0.0,
    },
    "camera": {
        "tilt_deg": 13.3,
        "height_mm": 22.8,
        "lens_from_mount_mm": 23.1,
        "fov_diagonal_deg": 66.0,
        "aspect": [4, 3],
        "image_rotation_deg": 0.0,
        "mirror": False,
        "roll_zero_deg": 0.0,
        "roll_sign": 1.0,
    },
    "desk": {"z_mm": 0.0, "margin_mm": 3.0},
    "brick": {"grasp_height_mm": 8.0},
    "gripper": {
        "open_width_mm": 45.0,
        "close_width_mm": 13.0,
        "jaw_calibration": [
            {"deg": 10.0, "width_mm": 60.0},
            {"deg": 73.0, "width_mm": 0.0},
        ],
        "settle_s": 0.6,
    },
    "search": {
        "height_mm": 80.0,
        "radii_mm": [235.0],
        "base_min_deg": 20.0,
        "base_max_deg": 160.0,
        "step_deg": 2.0,
    },
    "approach": {
        "gain": 0.6,
        "max_step_mm": 15.0,
        "tolerance_mm": 3.0,
        "centre_frames": 2,
        "settle_frames": 2,
        "descent_step_mm": 15.0,
        "commit_distance_mm": 40.0,
        "lost_frames": 12,
        "track_gate_mm": 40.0,
        "timeout_s": 45.0,
    },
    "verify": {"frames": 5, "radius_mm": 18.0},
    "bin": {
        "rim_height_mm": 40.0,
        "release_clearance_mm": 20.0,
        "tolerance_mm": 6.0,
        "search_timeout_s": 30.0,
        "fallback_xy_mm": [130.0, 225.0],
        "ignore_radius_mm": 75.0,
        "remember": True,
    },
    "speed": {"max_step_deg": 2.0, "step_interval_s": 0.05, "slow_factor": 0.4},
}

IDLE, STARTING, SEARCH, APPROACH, GRASP, LIFT, VERIFY = (
    "idle", "starting", "search", "approach", "grasp", "lift", "verify")
BIN_SEARCH, BIN_APPROACH, PLACE, RETURN = (
    "bin-search", "bin-approach", "place", "return")
DONE, STOPPED, FAULT = "done", "stopped", "fault"


class Stopped(Exception):
    """A stop was requested. Nothing further is sent to the arm."""


class Fault(Exception):
    """The run cannot continue safely (watchdog, arm error)."""


class MotionRefused(ValueError):
    """A planned move failed a limit check. Nothing was sent."""


class ApproachFailed(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason


# --------------------------------------------------------------- settings

def load_settings(config_dir=None, overrides: Optional[dict] = None) -> dict:
    """Defaults, then config/pick_place.yaml, then the ``pick_place`` block
    of config/runtime.yaml, then ``overrides``. Validated."""
    directory = Path(config_dir or cfg.CONFIG_DIR)
    settings = cfg.merge_config(DEFAULTS, {})
    if (directory / CONFIG_NAME).exists():
        settings = cfg.merge_config(settings, cfg.load_yaml(CONFIG_NAME, directory))
    if (directory / "runtime.yaml").exists():
        runtime = cfg.load_yaml("runtime.yaml", directory).get("pick_place") or {}
        settings = cfg.merge_config(settings, runtime)
    if overrides:
        settings = cfg.merge_config(settings, overrides)
    validate_settings(settings)
    return settings


def validate_settings(settings: dict) -> None:
    unknown = set(settings) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown pick-and-place settings: {sorted(unknown)}")
    for block, defaults in DEFAULTS.items():
        if isinstance(defaults, dict):
            extra = set(settings[block]) - set(defaults)
            if extra:
                raise ValueError(f"Unknown {block} settings: {sorted(extra)}")
    colours = settings["colours"]
    if not colours or any(c not in BRICK_LABELS for c in colours):
        raise ValueError(f"colours must be chosen from {list(BRICK_LABELS)}")
    if len(set(colours)) != len(colours):
        raise ValueError("colours lists a colour twice")
    if not 0.0 < float(settings["confidence"]) <= 1.0:
        raise ValueError("confidence must be above 0 and at most 1")
    for name in ("confirm_frames", "max_attempts", "max_picks"):
        if int(settings[name]) < 1:
            raise ValueError(f"{name} must be at least 1")
    if not 0.2 <= float(settings["watchdog_s"]) <= 5.0:
        raise ValueError("watchdog_s must be between 0.2 and 5 seconds")
    tool = settings["tool"]
    if not -89.0 <= float(tool["pitch_deg"]) <= -30.0:
        raise ValueError("tool.pitch_deg must be between -89 and -30 "
                         "(the gripper has to point down at the desk)")
    if float(tool["tip_from_mount_mm"]) < float(tool["grasp_from_mount_mm"]):
        raise ValueError("The grasp point cannot be beyond the claw tips")
    if float(settings["desk"]["margin_mm"]) < 0.5:
        raise ValueError("desk.margin_mm must be at least 0.5 mm")
    gripper = settings["gripper"]
    if float(gripper["open_width_mm"]) <= float(gripper["close_width_mm"]):
        raise ValueError("gripper.open_width_mm must exceed close_width_mm")
    points = gripper["jaw_calibration"]
    if len(points) != 2 or abs(points[0]["deg"] - points[1]["deg"]) < 5 \
            or abs(points[0]["width_mm"] - points[1]["width_mm"]) < 5:
        raise ValueError("gripper.jaw_calibration needs two well separated "
                         "(deg, width_mm) points")
    search = settings["search"]
    if not 0.0 <= search["base_min_deg"] < search["base_max_deg"] <= 180.0:
        raise ValueError("search base range must satisfy 0 <= min < max <= 180")
    if not search["radii_mm"]:
        raise ValueError("search.radii_mm needs at least one radius")
    if not 0.2 <= float(search["step_deg"]) <= 5.0:
        raise ValueError("search.step_deg must be between 0.2 and 5")
    approach = settings["approach"]
    if not 0.1 <= float(approach["gain"]) <= 1.0:
        raise ValueError("approach.gain must be between 0.1 and 1")
    speed = settings["speed"]
    if not 0.1 <= float(speed["max_step_deg"]) <= 5.0:
        raise ValueError("speed.max_step_deg must be between 0.1 and 5")
    if not 0.05 <= float(speed["slow_factor"]) <= 1.0:
        raise ValueError("speed.slow_factor must be between 0.05 and 1")


def jaw_angle(width_mm: float, calibration: Sequence[dict]) -> float:
    """Gripper servo angle for a gap between the claws, on the straight line
    through the two measured calibration points."""
    first, second = calibration[0], calibration[1]
    slope = (second["deg"] - first["deg"]) / (second["width_mm"] - first["width_mm"])
    return first["deg"] + slope * (float(width_mm) - first["width_mm"])


def jaw_width(angle_deg: float, calibration: Sequence[dict]) -> float:
    first, second = calibration[0], calibration[1]
    slope = (second["width_mm"] - first["width_mm"]) / (second["deg"] - first["deg"])
    return first["width_mm"] + slope * (float(angle_deg) - first["deg"])


def tool_workspace(workspace: dict, settings: dict) -> dict:
    """The workspace with the gripper as the tool, built the way the Studio
    builds it for its Gripper mode, so the existing IK and FK place the grasp
    point instead of the pen tip."""
    from web.control import workspace_for_tool

    tool, gripper = settings["tool"], settings["gripper"]
    return workspace_for_tool(workspace, {"active": "gripper", "gripper": {
        "length_mm": float(tool["mount_from_wrist_mm"]) + float(tool["grasp_from_mount_mm"]),
        "pitch_deg": float(tool["pitch_deg"]),
        "open_deg": round(jaw_angle(gripper["open_width_mm"],
                                    gripper["jaw_calibration"])),
    }})


# ------------------------------------------------------------ motion guard

class MotionGuard:
    """The only thing that sends moves. Plans, checks, then steps.

    A move is refused as a whole, before its first step is sent, when the
    target or any step on the way to it

    * cannot be solved by the inverse kinematics in strict mode,
    * puts a joint outside the Studio's limits (``web.control.joint_limits``:
      the hard limits narrowed by ``servo_limits`` in workspace.yaml), or
    * brings the grasp point or the claw tips below the desk plus the margin.

    Steps are at most ``max_step_deg`` on any joint, never more than
    ``motion.max_step_deg`` in workspace.yaml, with ``step_interval_s``
    between them. In dry-run nothing is sent; the pose is tracked so that
    the plan can still be followed and logged.
    """

    def __init__(self, workspace_tool: dict, settings: dict, arm=None,
                 dry_run: bool = True, sleep: Callable[[float], None] = None,
                 slow: bool = False):
        from web.control import JOINTS, REST_POSE, joint_limits

        self.joints = JOINTS
        self.rest_pose = tuple(float(a) for a in REST_POSE)
        self.limits = joint_limits(workspace_tool)
        self.kin = BraccioKinematics(workspace_tool)
        self.fk = BraccioForwardKinematics(workspace_tool)
        tool, speed = settings["tool"], settings["speed"]
        self.tip_extra = float(tool["tip_from_mount_mm"]) - float(tool["grasp_from_mount_mm"])
        self.wrist_rotation = float(tool["wrist_rotation_deg"])
        self.floor = float(settings["desk"]["z_mm"]) + float(settings["desk"]["margin_mm"])
        factor = float(speed["slow_factor"]) if slow else 1.0
        ceiling = float(workspace_tool.get("motion", {}).get("max_step_deg", 2.5))
        self.max_step = min(float(speed["max_step_deg"]), ceiling) * factor
        self.interval = float(speed["step_interval_s"]) / factor
        self.arm = arm
        self.dry_run = dry_run
        self.sleep = sleep or (lambda seconds: None)
        self.pose: Tuple[float, ...] = self.rest_pose
        self.jaw = self.pose[5]
        self.steps_sent = 0
        self.steps_planned = 0

    def start(self) -> Tuple[float, ...]:
        """Read where the arm is. In dry-run without an arm, assume rest."""
        if self.arm is not None:
            pose = self.arm.status_angles()
            if pose is None or len(pose) != 6 or not all(math.isfinite(v) for v in pose):
                raise Fault("The arm did not report six commanded joint angles")
            self.pose = tuple(float(v) for v in pose)
        self.jaw = self.pose[5]
        return self.pose

    def lowest_mm(self, angles: Sequence[float]) -> float:
        """Height of the lower of the grasp point and the claw tips."""
        tip = self.fk.solve(tuple(angles))
        pitch = self.fk.joint_radians(tuple(angles))[3]
        return min(tip.z_mm, tip.z_mm + self.tip_extra * math.sin(pitch))

    def check(self, angles: Sequence[float], what: str = "move") -> None:
        for name, value, (low, high) in zip(self.joints, angles, self.limits):
            if not (math.isfinite(value) and low - 1e-6 <= value <= high + 1e-6):
                raise MotionRefused(
                    f"{what}: {name} at {value:.1f} deg is outside {low:g}..{high:g}")
        lowest = self.lowest_mm(angles)
        if lowest < self.floor - 1e-6:
            raise MotionRefused(
                f"{what}: the gripper would be {lowest:.1f} mm above the desk "
                f"datum, below the {self.floor:.1f} mm floor")

    def solve(self, x: float, y: float, z: float, jaw: Optional[float] = None,
              what: str = "move") -> Tuple[float, ...]:
        """Servo angles that put the grasp point at (x, y, z), checked."""
        try:
            solved = self.kin.solve(x, y, z, strict=True).as_tuple()
        except UnreachableError as exc:
            raise MotionRefused(f"{what}: {exc}") from exc
        angles = (solved[0], solved[1], solved[2], solved[3],
                  self.wrist_rotation, self.jaw if jaw is None else float(jaw))
        self.check(angles, what)
        return angles

    def plan(self, target: Sequence[float], max_step: Optional[float] = None,
             what: str = "move") -> List[Tuple[float, ...]]:
        """The checked steps from the current pose to ``target``."""
        target = tuple(float(a) for a in target)
        self.check(target, what)
        limit = min(max_step or self.max_step, self.max_step)
        span = max(abs(t - c) for t, c in zip(target, self.pose))
        count = max(1, math.ceil(span / limit - 1e-9))
        steps = []
        for index in range(1, count + 1):
            fraction = index / count
            step = tuple(round(c + (t - c) * fraction, 2)
                         for c, t in zip(self.pose, target))
            self.check(step, what)
            steps.append(step)
        return steps

    def move_joints(self, target: Sequence[float], on_step=None,
                    max_step: Optional[float] = None, what: str = "move") -> bool:
        """Step to ``target``. ``on_step`` runs after every step and may
        return False to end the move early. Returns True if it finished."""
        steps = self.plan(target, max_step, what)
        self.steps_planned += len(steps)
        for step in steps:
            self._send(step)
            if on_step is not None and on_step() is False:
                return False
        return True

    def _send(self, step: Tuple[float, ...]) -> None:
        if self.dry_run or self.arm is None:
            LOG.debug("dry-run M %s", " ".join(f"{a:g}" for a in step))
        else:
            reply = self.arm.move(step)
            if not str(reply).startswith("OK"):
                raise Fault(f"The arm rejected a move: {reply!r}")
            self.steps_sent += 1
        self.pose = step
        self.jaw = step[5]
        self.sleep(self.interval)

    def grasp_point(self) -> Tuple[float, float, float]:
        return self.fk.solve(self.pose).as_tuple()


# -------------------------------------------------------------- controller

class PickPlaceController:
    """Runs the pick-and-place cycle against a detection source and an arm.

    ``arm`` is anything with ``move(angles)`` and ``status_angles()``: an
    :class:`~sketch_artist.arm_client.ArmClient` for the real arm agent or
    the software arm. With ``dry_run`` nothing is sent to it. The clock and
    the pauses come from the detection source, so the simulated camera can
    run the whole loop on a clock of its own.
    """

    def __init__(self, workspace: dict, settings: dict, source: DetectionSource,
                 arm=None, dry_run: bool = True, slow: bool = False):
        validate_settings(settings)
        self.settings = settings
        self.source = source
        self.dry_run = dry_run
        self.workspace_tool = tool_workspace(workspace, settings)
        self.camera = GripperCamera(self.workspace_tool, settings["tool"],
                                    settings["camera"])
        self.guard = MotionGuard(self.workspace_tool, settings, arm, dry_run,
                                 source.sleep, slow)
        self.clock = source.now
        self.pitch = math.radians(float(settings["tool"]["pitch_deg"]))
        desk = float(settings["desk"]["z_mm"])
        self.grasp_z = desk + float(settings["brick"]["grasp_height_mm"])
        self.rim_z = desk + float(settings["bin"]["rim_height_mm"])
        self.travel_z = desk + float(settings["search"]["height_mm"])
        calibration = settings["gripper"]["jaw_calibration"]
        self.jaw_open = jaw_angle(settings["gripper"]["open_width_mm"], calibration)
        self.jaw_closed = jaw_angle(settings["gripper"]["close_width_mm"], calibration)
        base = self.workspace_tool["servo_calibration"]["base"]
        self._base_offset = float(base.get("offset", 90))
        self._base_sign = float(base.get("sign", 1)) or 1.0

        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self.state = IDLE
        self.message = ""
        self.frame: Optional[Frame] = None
        self.frame_time: Optional[float] = None
        self.frames_read = 0
        self.target: Optional[dict] = None
        self.aim_xy: Optional[Tuple[float, float]] = None
        self.picked = 0
        self.placed = 0
        self.failures: List[dict] = []
        self.history: List[str] = []
        self.blocked: List[Tuple[float, float]] = []
        self.bin_xy: Optional[Tuple[float, float]] = None
        self.bin_seen = False
        self._streak: Optional[list] = None

    # ----------------------------------------------------------- reporting

    def stop(self) -> None:
        """Ask the run to halt. Safe from any thread."""
        self.stop_event.set()

    def _set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self.state, self.message = state, message
        self._note(f"[{state}] {message}" if message else f"[{state}]")

    def _note(self, text: str) -> None:
        line = f"{self.clock():8.2f}s {text}"
        with self._lock:
            self.history.append(line)
            del self.history[:-200]
        LOG.info("%s", text)

    def _fail(self, reason: str, label: str, detail: str = "") -> None:
        self.failures.append({"reason": reason, "label": label, "detail": detail})
        self._note(f"failure: {reason} ({label}) {detail}".rstrip())

    def snapshot(self) -> dict:
        """State for the monitor page. Safe from any thread."""
        with self._lock:
            frame = self.frame
            age = None if self.frame_time is None else max(
                0.0, self.clock() - self.frame_time)
            return {
                "state": self.state, "message": self.message,
                "dry_run": self.dry_run,
                "stop_requested": self.stop_event.is_set(),
                "detections": [] if frame is None else [
                    {"label": d.label, "x": d.x, "y": d.y,
                     "confidence": d.confidence} for d in frame.detections],
                "inference_ms": None if frame is None else frame.inference_ms,
                "frame_age_s": None if age is None else round(age, 2),
                "frames": self.frames_read,
                "aim": None if self.aim_xy is None else list(self.aim_xy),
                "target": self.target,
                "pose": list(self.guard.pose),
                "grasp_point_mm": [round(v, 1) for v in self.guard.grasp_point()],
                "picked": self.picked, "placed": self.placed,
                "failures": list(self.failures),
                "moves_sent": self.guard.steps_sent,
                "moves_planned": self.guard.steps_planned,
                "colours": list(self.settings["colours"]),
                "confidence": self.settings["confidence"],
                "log": self.history[-40:],
            }

    # ------------------------------------------------------- frames, moves

    def _next_frame(self) -> Frame:
        """The next camera frame. Raises on a stop request, and trips the
        watchdog when no frame arrives in time."""
        if self.stop_event.is_set():
            raise Stopped()
        limit = float(self.settings["watchdog_s"])
        frame = self.source.read(limit)
        if self.stop_event.is_set():
            raise Stopped()
        if frame is None:
            raise Fault(f"Watchdog: no detections from the camera for {limit:g} s")
        with self._lock:
            self.frame, self.frame_time = frame, self.clock()
            self.frames_read += 1
        return frame

    def _pump(self) -> bool:
        self._next_frame()
        return True

    def _station(self, radius: float, base_servo_deg: float, z: float):
        angle = math.radians((base_servo_deg - self._base_offset) / self._base_sign)
        return (radius * math.cos(angle), radius * math.sin(angle), z)

    def _aim_station(self, xy: Tuple[float, float], plane_z: float, z: float):
        """Grasp-point position at height z whose centre line passes through
        the point ``xy`` on the plane z = plane_z."""
        back = (z - plane_z) / math.tan(-self.pitch)
        distance = math.hypot(xy[0], xy[1])
        scale = (distance - back) / distance
        return (xy[0] * scale, xy[1] * scale, z)

    def _tool_direction(self) -> Tuple[float, float, float]:
        x, y, _ = self.guard.grasp_point()
        distance = math.hypot(x, y) or 1.0
        return (math.cos(self.pitch) * x / distance,
                math.cos(self.pitch) * y / distance, math.sin(self.pitch))

    def _goto(self, position, on_step=None, max_step=None, what="move") -> bool:
        """Joint-space move of the grasp point to a base-frame position."""
        target = self.guard.solve(*position, what=what)
        return self.guard.move_joints(target, on_step or self._pump, max_step, what)

    def _line(self, position, what="move") -> None:
        """Straight-line move of the grasp point, in pieces of 5 mm or less.
        Planned and checked as a whole before the first piece is sent."""
        start = self.guard.grasp_point()
        length = math.dist(start, position)
        pieces = max(1, math.ceil(length / 5.0))
        targets = [self.guard.solve(*(s + (p - s) * i / pieces
                                     for s, p in zip(start, position)), what=what)
                   for i in range(1, pieces + 1)]
        for target in targets:
            self.guard.move_joints(target, self._pump, what=what)

    def _along_tool(self, distance: float, what="move") -> None:
        """Move the grasp point along the gripper centre line (+ is forward,
        towards the desk)."""
        direction = self._tool_direction()
        start = self.guard.grasp_point()
        self._line(tuple(s + distance * d for s, d in zip(start, direction)), what)

    def _to_travel_height(self, what="lift") -> None:
        """Back up along the centre line to the travel height. If that is
        refused, try straight up instead."""
        x, y, z = self.guard.grasp_point()
        if z >= self.travel_z - 0.5:
            return
        try:
            self._along_tool(-(self.travel_z - z) / math.sin(-self.pitch), what)
        except MotionRefused:
            self._line((x, y, self.travel_z), what)

    def _set_jaw(self, angle: float, what: str) -> None:
        target = self.guard.pose[:5] + (round(float(angle), 1),)
        self.guard.move_joints(target, self._pump, what=what)
        settle = float(self.settings["gripper"]["settle_s"])
        waited = 0.0
        while waited < settle:      # keep the watchdog fed while waiting
            before = self.clock()
            self._next_frame()
            waited += max(0.01, self.clock() - before)

    # ----------------------------------------------------- reading frames

    def _candidates(self, frame: Frame, labels: Sequence[str], plane_z: float):
        """Usable detections of ``labels``: (rank, detection, base-frame xy)."""
        threshold = float(self.settings["confidence"])
        pose = self.camera.pose(self.guard.pose)
        ignore = float(self.settings["bin"]["ignore_radius_mm"])
        found = []
        for detection in frame.detections:
            if detection.label not in labels or detection.confidence < threshold:
                continue
            xy = self.camera.ray_to_plane(detection.x, detection.y,
                                          self.guard.pose, plane_z, pose)
            if xy is None:
                continue
            if detection.label != BIN_LABEL:
                if any(math.dist(xy, spot) < 30.0 for spot in self.blocked):
                    continue
                if self.bin_xy is not None and math.dist(xy, self.bin_xy) < ignore:
                    continue        # a brick already in the bin
            found.append((labels.index(detection.label), detection, xy))
        found.sort(key=lambda item: (item[0], -item[1].confidence))
        return found

    def _watch(self, frame: Frame, labels: Sequence[str], plane_z: float):
        """Count frames in a row that show the same thing in the same place.
        Returns (label, xy) once it has been seen often enough."""
        found = self._candidates(frame, labels, plane_z)
        if not found:
            self._streak = None
            return None
        _, detection, xy = found[0]
        streak = self._streak
        if (streak and streak[0] == detection.label
                and math.dist(streak[1], xy) < 40.0):
            streak[1], streak[2] = xy, streak[2] + 1
        else:
            streak = self._streak = [detection.label, xy, 1]
        with self._lock:
            self.target = {"label": detection.label, "x": detection.x,
                           "y": detection.y, "confirmed": False}
        if streak[2] >= int(self.settings["confirm_frames"]):
            self._streak = None
            return detection.label, xy
        return None

    # --------------------------------------------------------------- search

    def _search(self, labels: Sequence[str], plane_z: float,
                deadline: Optional[float] = None):
        """Sweep the base at the travel height. Returns (label, xy) for the
        first thing seen steadily, or None after a whole sweep (or at the
        deadline)."""
        search = self.settings["search"]
        low, high = float(search["base_min_deg"]), float(search["base_max_deg"])
        result: list = []
        self._streak = None

        def look() -> bool:
            frame = self._next_frame()
            seen = self._watch(frame, labels, plane_z)
            if seen is not None:
                result.append(seen)
                return False
            return deadline is None or self.clock() < deadline

        here = min(high, max(low, self.guard.pose[0]))
        ends = [low, high] if abs(here - low) <= abs(here - high) else [high, low]
        for radius in search["radii_mm"]:
            for base in [here] + ends:
                done = self._goto(self._station(float(radius), base, self.travel_z),
                                  look, float(search["step_deg"]), "search")
                if result:
                    return result[0]
                if not done:
                    return None
            here = ends[-1]
            ends.reverse()
        return None

    # ------------------------------------------------------------- approach

    def _track(self, frame: Frame, label: str, estimate, plane_z: float):
        """The detection of ``label`` nearest to where the target was."""
        gate = float(self.settings["approach"]["track_gate_mm"])
        best = None
        for _, detection, xy in self._candidates(frame, [label], plane_z):
            distance = math.dist(xy, estimate)
            if distance <= gate and (best is None or distance < best[2]):
                best = (detection, xy, distance)
        return best

    def _centre_on(self, label: str, estimate, plane_z: float, tolerance: float,
                   stop_distance: Optional[float]):
        """Bring ``label`` to the aim point: where the gripper centre line
        meets the plane it lies on. With ``stop_distance`` set, step down
        the centre line and centre again until the grasp point is that far
        from the plane. Returns the target's base-frame position."""
        approach = self.settings["approach"]
        deadline = self.clock() + float(approach["timeout_s"])
        settle = int(approach["settle_frames"])
        lost = centred = 0
        while True:
            if self.clock() > deadline:
                raise ApproachFailed("approach_timeout")
            frame = self._next_frame()
            if settle > 0:
                settle -= 1
                continue
            pose = self.camera.pose(self.guard.pose)
            aim = self.camera.aim_point(self.guard.pose, plane_z, pose)
            if aim is None:
                raise ApproachFailed("approach_geometry")
            aim_image, aim_xy, distance = aim
            tracked = self._track(frame, label, estimate, plane_z)
            with self._lock:
                self.aim_xy = aim_image
            if tracked is None:
                lost += 1
                if lost > int(approach["lost_frames"]):
                    raise ApproachFailed("approach_lost")
                continue
            lost = 0
            detection, estimate, _ = tracked
            with self._lock:
                self.target = {"label": label, "x": detection.x,
                               "y": detection.y, "confirmed": True}
            error = (estimate[0] - aim_xy[0], estimate[1] - aim_xy[1])
            size = math.hypot(*error)
            if size <= tolerance:
                centred += 1
                if centred < int(approach["centre_frames"]):
                    continue
                centred = 0
                if stop_distance is None:
                    return estimate
                remaining = distance - stop_distance
                if remaining <= 0.5:
                    return estimate
                self._along_tool(min(float(approach["descent_step_mm"]), remaining),
                                 "descend")
            else:
                centred = 0
                scale = float(approach["gain"])
                reach = float(approach["max_step_mm"])
                if size * scale > reach:
                    scale = reach / size
                x, y, z = self.guard.grasp_point()
                self._line((x + error[0] * scale, y + error[1] * scale, z),
                           "centre")
            settle = int(approach["settle_frames"])

    # ----------------------------------------------------------------- pick

    def _still_there(self, label: str, estimate) -> bool:
        """After the lift: is a brick of this colour still where it was?"""
        verify = self.settings["verify"]
        for _ in range(int(self.settings["approach"]["settle_frames"])):
            self._next_frame()
        seen = 0
        frames = int(verify["frames"])
        for _ in range(frames):
            frame = self._next_frame()
            for _, _, xy in self._candidates(frame, [label], self.grasp_z):
                if math.dist(xy, estimate) <= float(verify["radius_mm"]):
                    seen += 1
                    break
        return seen * 2 >= frames

    def _pick(self, label: str, estimate) -> bool:
        commit = float(self.settings["approach"]["commit_distance_mm"])
        tolerance = float(self.settings["approach"]["tolerance_mm"])
        for attempt in range(1, int(self.settings["max_attempts"]) + 1):
            self._set_state(APPROACH, f"{label}, attempt {attempt}")
            try:
                self._set_jaw(self.jaw_open, "open")
                # Point the claws at where the brick is thought to be, then
                # let the picture take over.
                self._goto(self._aim_station(estimate, self.grasp_z, self.travel_z),
                           what="aim")
                estimate = self._centre_on(label, estimate, self.grasp_z,
                                           tolerance, commit)
                aim = self.camera.aim_point(self.guard.pose, self.grasp_z)
                self._along_tool(aim[2], "commit")
            except ApproachFailed as exc:
                self._fail(exc.reason, label, str(exc))
                self._to_travel_height()
                continue
            except MotionRefused as exc:
                self._fail("unreachable", label, str(exc))
                self._to_travel_height()
                break
            self._set_state(GRASP, label)
            self._set_jaw(self.jaw_closed, "grasp")
            self._set_state(LIFT, label)
            self._to_travel_height()
            self._set_state(VERIFY, label)
            if not self._still_there(label, estimate):
                self.picked += 1
                return True
            self._fail("grasp_failed", label, f"attempt {attempt}")
        self.blocked.append(tuple(estimate))
        self._set_jaw(self.jaw_open, "open")
        return False

    # ---------------------------------------------------------------- place

    def _lower_to_release(self) -> None:
        clearance = float(self.settings["bin"]["release_clearance_mm"])
        _, _, z = self.guard.grasp_point()
        drop = z - (self.rim_z + clearance)
        if drop <= 0.5:
            return
        try:
            self._along_tool(drop / math.sin(-self.pitch), "lower to bin")
        except MotionRefused as exc:
            self._note(f"releasing from the travel height: {exc}")

    def _place(self) -> None:
        settings = self.settings["bin"]
        tolerance = float(settings["tolerance_mm"])
        found = None
        if self.bin_seen and settings["remember"]:
            self._set_state(BIN_APPROACH, "returning to where the bin was")
            try:
                self._goto(self._aim_station(self.bin_xy, self.rim_z, self.travel_z),
                           what="to bin")
                found = self._centre_on(BIN_LABEL, self.bin_xy, self.rim_z,
                                        tolerance, None)
            except (ApproachFailed, MotionRefused) as exc:
                self._note(f"bin not where it was: {exc}")
        if found is None:
            self._set_state(BIN_SEARCH, "")
            deadline = self.clock() + float(settings["search_timeout_s"])
            seen = self._search([BIN_LABEL], self.rim_z, deadline)
            if seen is not None:
                self._set_state(BIN_APPROACH, "")
                try:
                    self._goto(self._aim_station(seen[1], self.rim_z, self.travel_z),
                               what="to bin")
                    found = self._centre_on(BIN_LABEL, seen[1], self.rim_z,
                                            tolerance, None)
                except (ApproachFailed, MotionRefused) as exc:
                    self._note(f"could not centre on the bin: {exc}")
        if found is not None:
            self.bin_xy, self.bin_seen = tuple(found), True
        else:
            fallback = tuple(float(v) for v in settings["fallback_xy_mm"])
            self._set_state(PLACE, "bin not seen, using the configured position")
            self._fail("bin_not_seen", BIN_LABEL, "used bin.fallback_xy_mm")
            self._goto(self._aim_station(fallback, self.rim_z, self.travel_z),
                       what="to fallback bin")
            if self.bin_xy is None:
                self.bin_xy = fallback
        self._set_state(PLACE, "")
        self._lower_to_release()
        self._set_jaw(self.jaw_open, "release")
        self.placed += 1
        self._to_travel_height()

    # ------------------------------------------------------------------ run

    def check_plan(self) -> List[str]:
        """Check everything that can be checked before moving, and describe
        the plan. Raises ValueError if the configuration cannot be run."""
        search, settings = self.settings["search"], self.settings
        notes = []
        tip_drop = self.guard.tip_extra * math.sin(-self.pitch)
        if self.grasp_z - tip_drop < self.guard.floor:
            raise ValueError(
                f"brick.grasp_height_mm puts the claw tips "
                f"{self.grasp_z - tip_drop - float(settings['desk']['z_mm']):.1f} mm "
                f"above the desk, less than desk.margin_mm")
        for name, angle in (("open", self.jaw_open), ("closed", self.jaw_closed)):
            low, high = self.guard.limits[5]
            if not low <= angle <= high:
                raise ValueError(f"The {name} claw angle {angle:.1f} deg is "
                                 f"outside {low:g}..{high:g}")
        try:
            for radius in search["radii_mm"]:
                for base in (search["base_min_deg"], search["base_max_deg"],
                             (search["base_min_deg"] + search["base_max_deg"]) / 2):
                    self.guard.solve(*self._station(float(radius), float(base),
                                                    self.travel_z), what="search pose")
            fallback = tuple(float(v) for v in settings["bin"]["fallback_xy_mm"])
            self.guard.solve(*self._aim_station(fallback, self.rim_z, self.travel_z),
                             what="fallback bin pose")
        except MotionRefused as exc:
            raise ValueError(str(exc)) from exc
        aim = self.camera.aim_point(
            self.guard.solve(*self._station(float(search["radii_mm"][0]), 90.0,
                                            self.travel_z)), self.grasp_z)
        notes.append(f"colours, in order: {', '.join(settings['colours'])}; "
                     f"confidence {settings['confidence']:g}, "
                     f"{settings['confirm_frames']} frames to confirm")
        notes.append(f"search: grasp point {search['height_mm']:g} mm above the "
                     f"desk, base {search['base_min_deg']:g}..{search['base_max_deg']:g} "
                     f"deg at {', '.join(f'{r:g}' for r in search['radii_mm'])} mm")
        if aim is not None and aim[0] is not None:
            notes.append(f"aim point in the picture at the search height: "
                         f"x {aim[0][0]:.2f}, y {aim[0][1]:.2f}; the centre line "
                         f"meets the desk {aim[2]:.0f} mm ahead of the claws")
        notes.append(f"grasp: grasp point {settings['brick']['grasp_height_mm']:g} mm "
                     f"above the desk, claw tips {self.grasp_z - tip_drop - settings['desk']['z_mm']:.1f} mm; "
                     f"claws {self.jaw_open:.1f} deg open, {self.jaw_closed:.1f} deg closed")
        notes.append(f"steps of at most {self.guard.max_step:g} deg every "
                     f"{self.guard.interval:g} s; watchdog {settings['watchdog_s']:g} s")
        notes.append("dry-run: nothing is sent to the arm" if self.dry_run
                     else "LIVE: moves are sent to the arm")
        return notes

    def run(self) -> dict:
        """Run until nothing is left to pick, a stop, or a fault. Returns a
        summary; never raises for those three endings."""
        try:
            self._set_state(STARTING, "")
            for note in self.check_plan():
                self._note(note)
            self.guard.start()
            self._next_frame()
            search = self.settings["search"]
            home = self._station(float(search["radii_mm"][0]), 90.0, self.travel_z)
            self._goto(home, what="to the search pose")
            self._set_jaw(self.jaw_open, "open")
            colours = list(self.settings["colours"])
            wanted = colours[:1] if self.settings["strict_order"] else colours
            while self.picked + len(self.blocked) < int(self.settings["max_picks"]):
                self._set_state(SEARCH, ", ".join(wanted))
                seen = self._search(wanted, self.grasp_z)
                if seen is None:
                    remaining = colours[colours.index(wanted[-1]) + 1:]
                    if self.settings["strict_order"] and remaining:
                        wanted = remaining[:1]
                        continue
                    break
                if self._pick(*seen):
                    self._place()
            self._set_state(RETURN, "")
            self._goto(home, what="to the search pose")
            self._set_state(DONE, f"{self.placed} placed")
        except Stopped:
            self._set_state(STOPPED, "stop requested; the arm holds its pose")
        except KeyboardInterrupt:
            self.stop_event.set()
            self._set_state(STOPPED, "interrupted; the arm holds its pose")
        except (Fault, ValueError, OSError, RuntimeError) as exc:
            self._set_state(FAULT, str(exc))
        return self.summary()

    def summary(self) -> dict:
        reasons: Dict[str, int] = {}
        for failure in self.failures:
            reasons[failure["reason"]] = reasons.get(failure["reason"], 0) + 1
        return {"state": self.state, "message": self.message,
                "picked": self.picked, "placed": self.placed,
                "failures": reasons, "frames": self.frames_read,
                "moves_sent": self.guard.steps_sent,
                "moves_planned": self.guard.steps_planned,
                "elapsed_s": round(self.clock(), 1), "dry_run": self.dry_run}

