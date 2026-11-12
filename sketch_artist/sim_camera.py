"""Simulated gripper camera and desk for the pick-and-place loop.

This is the camera's side of the software arm (:mod:`sketch_artist.sim`).
A :class:`PickPlaceWorld` holds bricks and a parts bin on the desk and
listens to the simulator's moves. :class:`SimCameraSource` looks at them
through a pinhole camera placed on top of the simulated gripper and emits
the detector's text lines, the same ``DET ...`` lines the real camera prints,
so the controller in :mod:`sketch_artist.pick_place` runs closed-loop with no
hardware: search, approach, grasp, lift, place.

What is modelled, and how simply:

* **Camera.** Pinhole, no distortion; field of view a parameter (default 66
  degrees diagonal, 4:3). A brick is reported at the picture position of its
  centre and the bin at the centre of its rim, when that point is inside the
  picture. Gaussian position noise, dropped detections (more often near the
  edge of the picture), spurious detections, whole frames lost, and a delay
  of a frame or more between the pose and the picture.
* **World and model apart.** The world can be built with a camera, a desk
  height and servo offsets that differ a little from what the controller
  believes, the way a real rig differs from its configuration.
* **Grasp.** When the claws close, a brick on the desk is held if the grasp
  point is at brick height and the brick is between the claws: inside the
  open gap across them and overlapping the claws by a few millimetres along
  them. A small chance of slipping. A brick that is touched but not held is
  nudged aside.
* **Release.** When the claws open, a held brick falls straight down. It is
  in the bin if it lands inside the bin's opening, otherwise it is back on
  the desk where it fell.

Not modelled: collisions of the arm, claws or held brick with anything, the
claws hiding part of the picture, lens blur at close range, lighting, servo
lag and backlash, cable drag. Results from this are simulated results.
"""

from __future__ import annotations

import copy
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from .detections import (BIN_LABEL, BRICK_LABELS, Detection, DetectionSource,
                         Frame, format_det_line, parse_det_line)
from .gripper_camera import GripperCamera
from .pick_place import (DEFAULTS, PickPlaceController, jaw_width,
                         load_settings, tool_workspace)
from .sim import SketchbotSimulator
from . import config as cfg

BRICK_SIZE_MM = (31.8, 15.8, 9.6)       # a 2x4 brick: length, width, body height


@dataclass
class SimBrick:
    label: str
    x: float
    y: float
    yaw_deg: float = 0.0
    state: str = "desk"                 # desk, held, bin
    z: float = BRICK_SIZE_MM[2] / 2.0

    def half_extent(self, direction: Tuple[float, float]) -> float:
        """Half the brick's size along a horizontal unit direction."""
        yaw = math.radians(self.yaw_deg)
        along = abs(direction[0] * math.cos(yaw) + direction[1] * math.sin(yaw))
        across = abs(-direction[0] * math.sin(yaw) + direction[1] * math.cos(yaw))
        return (BRICK_SIZE_MM[0] * along + BRICK_SIZE_MM[1] * across) / 2.0


@dataclass
class SimBin:
    x: float
    y: float
    yaw_deg: float = 0.0
    length_mm: float = 110.0            # inside opening
    width_mm: float = 80.0
    rim_height_mm: float = 40.0

    def holds(self, x: float, y: float, margin: float = 8.0) -> bool:
        yaw = math.radians(self.yaw_deg)
        dx, dy = x - self.x, y - self.y
        along = dx * math.cos(yaw) + dy * math.sin(yaw)
        across = -dx * math.sin(yaw) + dy * math.cos(yaw)
        return (abs(along) <= self.length_mm / 2.0 - margin
                and abs(across) <= self.width_mm / 2.0 - margin)


@dataclass
class CameraNoise:
    """How imperfect the simulated detector is."""
    position_sigma: float = 0.012       # of the picture width / height
    dropout: float = 0.08               # chance a visible object is not reported
    edge_dropout: float = 0.35          # the same within ``edge`` of the border
    edge: float = 0.05
    spurious: float = 0.03              # chance per frame of a false detection
    lost_frame: float = 0.04            # chance a whole line never arrives
    latency_frames: int = 1             # picture lags the pose by this many frames
    confidence: Tuple[float, float] = (0.86, 0.06)      # mean, sigma
    in_bin_visible: float = 0.6         # chance a brick in the bin is reported
    slip: float = 0.03                  # chance a good grasp lets go at once
    drop_sigma_mm: float = 3.0          # scatter of a released brick

    @classmethod
    def none(cls) -> "CameraNoise":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, (0.9, 0.0), 1.0, 0.0, 0.0)


class PickPlaceWorld:
    """Bricks and a bin on the desk, moved by the simulated gripper.

    ``workspace`` and ``settings`` describe the rig as it really is in this
    world. Pass the controller a different copy to model calibration error.
    """

    def __init__(self, workspace: dict, settings: dict, bricks: Sequence[SimBrick],
                 parts_bin: Optional[SimBin], noise: Optional[CameraNoise] = None,
                 seed: int = 0, start_pose: Optional[Sequence[float]] = None,
                 simulator: Optional[SketchbotSimulator] = None):
        from web.control import REST_POSE

        self.settings = settings
        self.workspace_tool = tool_workspace(workspace, settings)
        # ``simulator`` lets the world ride on a running SimArmAgent, so the
        # controller can reach it over the M/S protocol like the real arm.
        self.simulator = simulator or SketchbotSimulator(self.workspace_tool)
        self.camera = GripperCamera(self.workspace_tool, settings["tool"],
                                    settings["camera"])
        self.desk_z = float(settings["desk"]["z_mm"])
        self.bricks = list(bricks)
        for brick in self.bricks:
            brick.z = self.desk_z + BRICK_SIZE_MM[2] / 2.0
        self.bin = parts_bin
        self.noise = noise or CameraNoise()
        self.rng = random.Random(seed)
        self.events: List[str] = []
        self._calibration = settings["gripper"]["jaw_calibration"]
        self._width = jaw_width(REST_POSE[5], self._calibration)
        self.held: Optional[SimBrick] = None
        self.lowest_mm = float("inf")
        self.simulator.listeners.append(self._moved)
        self.simulator.apply_move(tuple(start_pose or REST_POSE))

    # The arm interface the controller needs (move, status_angles).
    def move(self, angles: Sequence[float]) -> str:
        self.simulator.apply_move(tuple(angles))
        return "OK"

    def status_angles(self) -> Tuple[float, ...]:
        return tuple(self.simulator.last_angles)

    @property
    def angles(self) -> Tuple[float, ...]:
        return tuple(self.simulator.last_angles)

    def _moved(self, angles: Tuple[float, ...]) -> None:
        pose = self.camera.pose(angles)
        tip_extra = (float(self.settings["tool"]["tip_from_mount_mm"])
                     - float(self.settings["tool"]["grasp_from_mount_mm"]))
        self.lowest_mm = min(self.lowest_mm, pose.grasp[2] - self.desk_z,
                             pose.grasp[2] + tip_extra * pose.tool[2] - self.desk_z)
        width = jaw_width(angles[5], self._calibration)
        closing = self._width >= 20.0 > width
        opening = self._width <= 25.0 < width
        self._width = width
        if closing and self.held is None:
            self._close(pose)
        elif opening and self.held is not None:
            self._release(pose)
        if self.held is not None:
            self.held.x, self.held.y, self.held.z = pose.grasp

    def _close(self, pose) -> None:
        gap = float(self.settings["gripper"]["open_width_mm"])
        height = pose.grasp[2] - self.desk_z
        jaw = (pose.jaw[0], pose.jaw[1])
        size = math.hypot(*jaw) or 1.0
        jaw = (jaw[0] / size, jaw[1] / size)
        depth = (-jaw[1], jaw[0])
        for brick in self.bricks:
            if brick.state != "desk":
                continue
            dx, dy = brick.x - pose.grasp[0], brick.y - pose.grasp[1]
            across = abs(dx * jaw[0] + dy * jaw[1])
            along = abs(dx * depth[0] + dy * depth[1])
            if math.hypot(dx, dy) > 30.0 or not 1.0 <= height <= 11.5:
                continue
            between = across + brick.half_extent(jaw) <= gap / 2.0
            overlap = along <= max(4.0, brick.half_extent(depth) - 3.0)
            if between and overlap and self.rng.random() >= self.noise.slip:
                brick.state = "held"
                self.held = brick
                self.events.append(f"held {brick.label}")
                return
            # Touched but not held: pushed aside a little.
            angle = self.rng.uniform(0.0, 2.0 * math.pi)
            push = self.rng.uniform(2.0, 8.0)
            brick.x += push * math.cos(angle)
            brick.y += push * math.sin(angle)
            brick.yaw_deg += self.rng.uniform(-25.0, 25.0)
            self.events.append(f"missed {brick.label}")
            return

    def _release(self, pose) -> None:
        brick, self.held = self.held, None
        brick.x = pose.grasp[0] + self.rng.gauss(0.0, self.noise.drop_sigma_mm)
        brick.y = pose.grasp[1] + self.rng.gauss(0.0, self.noise.drop_sigma_mm)
        brick.z = BRICK_SIZE_MM[2] / 2.0 + self.desk_z
        over_rim = (self.bin is not None and pose.grasp[2] - self.desk_z
                    >= self.bin.rim_height_mm)
        if over_rim and self.bin.holds(brick.x, brick.y):
            brick.state = "bin"
            self.events.append(f"binned {brick.label}")
        else:
            brick.state = "desk"
            self.events.append(f"dropped {brick.label} outside the bin")

    def render(self, angles: Sequence[float]) -> List[Detection]:
        """What the detector reports for the arm at ``angles``."""
        noise, rng = self.noise, self.rng
        pose = self.camera.pose(angles)
        found: List[Detection] = []

        def report(label: str, point, chance: float, sigma: float) -> None:
            image = self.camera.project(point, angles, pose)
            if not self.camera.in_picture(image):
                return
            margin = min(image[0], image[1], 1.0 - image[0], 1.0 - image[1])
            drop = noise.edge_dropout if margin < noise.edge else noise.dropout
            if rng.random() < drop or rng.random() >= chance:
                return
            x = image[0] + rng.gauss(0.0, sigma)
            y = image[1] + rng.gauss(0.0, sigma)
            confidence = rng.gauss(*noise.confidence)
            found.append(Detection(label, min(1.0, max(0.0, x)),
                                   min(1.0, max(0.0, y)),
                                   min(0.99, max(0.05, confidence))))

        for brick in self.bricks:
            chance = noise.in_bin_visible if brick.state == "bin" else 1.0
            report(brick.label, (brick.x, brick.y, brick.z), chance,
                   noise.position_sigma)
        if self.bin is not None:
            report(BIN_LABEL, (self.bin.x, self.bin.y,
                               self.desk_z + self.bin.rim_height_mm), 1.0,
                   noise.position_sigma * 1.5)
        if rng.random() < noise.spurious:
            found.append(Detection(rng.choice(BRICK_LABELS + (BIN_LABEL,)),
                                   rng.random(), rng.random(),
                                   rng.uniform(0.3, 0.8)))
        return found

    def counts(self) -> Dict[str, int]:
        result = {"desk": 0, "held": 0, "bin": 0}
        for brick in self.bricks:
            result[brick.state] += 1
        return result


class SimCameraSource(DetectionSource):
    """The simulated camera as a detection source, on a clock of its own.

    Every ``read`` advances the clock by one frame period, renders the world
    from the gripper camera, writes the detector's text line and parses it
    again, so the line format is part of the loop. ``stall_after`` makes the
    camera fall silent after that many frames (for the watchdog test).
    """

    def __init__(self, world: PickPlaceWorld, period_s: float = 0.05,
                 stall_after: Optional[int] = None, record: Optional[list] = None):
        self.world = world
        self.period = float(period_s)
        self.stall_after = stall_after
        self.record = record
        self._clock = 0.0
        self._poses: Deque[Tuple[float, ...]] = deque(
            maxlen=max(1, world.noise.latency_frames + 1))
        self.frames = 0
        self.last_line = ""

    def now(self) -> float:
        return self._clock

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._clock += seconds

    def read(self, timeout_s: float) -> Optional[Frame]:
        waited = 0.0
        while True:
            self._clock += self.period
            waited += self.period
            self._poses.append(self.world.angles)
            stalled = self.stall_after is not None and self.frames >= self.stall_after
            if not stalled and self.world.rng.random() >= self.world.noise.lost_frame:
                break
            if waited >= timeout_s:
                return None
        self.frames += 1
        detections = self.world.render(self._poses[0])
        self.last_line = format_det_line(detections, inference_ms=41)
        if self.record is not None:
            self.record.append(f"{self._clock:.3f} {self.last_line}")
        return parse_det_line(self.last_line, self._clock)


# ------------------------------------------------------- randomised trials

@dataclass
class TrialResult:
    seed: int
    bricks: int
    binned: int
    state: str
    elapsed_s: float
    lowest_mm: float
    reasons: Dict[str, int] = field(default_factory=dict)
    world_events: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def success(self) -> bool:
        return self.state == "done" and self.binned == self.bricks


def random_layout(rng: random.Random, count: int = 3,
                  colours: Sequence[str] = BRICK_LABELS,
                  radius_mm: Tuple[float, float] = (262.0, 305.0),
                  bearing_deg: Tuple[float, float] = (-60.0, 60.0),
                  bin_radius_mm: Tuple[float, float] = (245.0, 285.0)):
    """A bin and ``count`` bricks at random on the reachable part of the desk,
    bricks at least 45 mm apart and 95 mm from the middle of the bin."""
    def place(radius):
        r = rng.uniform(*radius)
        a = math.radians(rng.uniform(*bearing_deg))
        return r * math.cos(a), r * math.sin(a)

    bx, by = place(bin_radius_mm)
    parts_bin = SimBin(bx, by, rng.uniform(0.0, 180.0))
    bricks: List[SimBrick] = []
    while len(bricks) < count:
        x, y = place(radius_mm)
        if math.dist((x, y), (bx, by)) < 95.0:
            continue
        if any(math.dist((x, y), (b.x, b.y)) < 45.0 for b in bricks):
            continue
        bricks.append(SimBrick(colours[len(bricks) % len(colours)], x, y,
                               rng.uniform(0.0, 180.0)))
    return bricks, parts_bin


def miscalibrate(workspace: dict, settings: dict, rng: random.Random,
                 scale: float = 1.0) -> Tuple[dict, dict]:
    """A copy of the rig that is slightly off from its configuration: camera
    tilt, height and field of view, servo zero positions and the desk."""
    world_workspace = copy.deepcopy(workspace)
    world_settings = copy.deepcopy(settings)
    camera = world_settings["camera"]
    camera["tilt_deg"] += rng.gauss(0.0, 1.0) * scale
    camera["height_mm"] += rng.gauss(0.0, 1.0) * scale
    camera["lens_from_mount_mm"] += rng.gauss(0.0, 1.0) * scale
    camera["fov_diagonal_deg"] += rng.gauss(0.0, 2.0) * scale
    camera["image_rotation_deg"] += rng.gauss(0.0, 1.0) * scale
    world_settings["desk"]["z_mm"] += rng.gauss(0.0, 0.8) * scale
    for joint in ("base", "shoulder", "elbow", "wrist_vertical"):
        world_workspace["servo_calibration"][joint]["offset"] += \
            rng.gauss(0.0, 0.4) * scale
    return world_workspace, world_settings


def run_trial(seed: int, workspace: Optional[dict] = None,
              settings: Optional[dict] = None, count: int = 3,
              noise: Optional[CameraNoise] = None, calibration_error: float = 1.0,
              fallback_error_mm: float = 5.0) -> TrialResult:
    """One randomised layout, run to the end on the simulated arm."""
    rng = random.Random(seed)
    workspace = workspace or cfg.load_all()["workspace"]
    settings = copy.deepcopy(settings or load_settings())
    bricks, parts_bin = random_layout(rng, count, settings["colours"])
    parts_bin.rim_height_mm = float(settings["bin"]["rim_height_mm"])
    # The owner measures the bin's place for the fallback, give or take.
    settings["bin"]["fallback_xy_mm"] = [
        parts_bin.x + rng.gauss(0.0, fallback_error_mm),
        parts_bin.y + rng.gauss(0.0, fallback_error_mm)]
    world_workspace, world_settings = miscalibrate(workspace, settings, rng,
                                                   calibration_error)
    world = PickPlaceWorld(world_workspace, world_settings, bricks, parts_bin,
                           noise, seed=rng.randrange(1 << 30))
    source = SimCameraSource(world)
    controller = PickPlaceController(workspace, settings, source, arm=world,
                                     dry_run=False)
    summary = controller.run()
    return TrialResult(seed, len(bricks), world.counts()["bin"], summary["state"],
                       summary["elapsed_s"], world.lowest_mm,
                       summary["failures"], world.events, summary["message"])


def run_trials(trials: int, seed: int = 0, **options) -> dict:
    """Run ``trials`` layouts and add them up."""
    results = [run_trial(seed + index, **options) for index in range(trials)]
    reasons: Dict[str, int] = {}
    failed: Dict[str, int] = {}
    for result in results:
        for reason, number in result.reasons.items():
            reasons[reason] = reasons.get(reason, 0) + number
        if not result.success:
            cause = classify_failure(result)
            failed[cause] = failed.get(cause, 0) + 1
    bricks = sum(r.bricks for r in results)
    return {
        "trials": trials, "seed": seed,
        "layouts_cleared": sum(r.success for r in results),
        "bricks": bricks, "bricks_binned": sum(r.binned for r in results),
        "success_rate": sum(r.success for r in results) / max(1, trials),
        "brick_rate": sum(r.binned for r in results) / max(1, bricks),
        "controller_events": dict(sorted(reasons.items())),
        "failed_layouts": dict(sorted(failed.items())),
        "mean_elapsed_s": sum(r.elapsed_s for r in results) / max(1, trials),
        "lowest_mm": min(r.lowest_mm for r in results),
        "results": results,
    }


def classify_failure(result: TrialResult) -> str:
    """One cause for a layout that was not cleared."""
    if result.state == "fault":
        return "fault: " + result.message.split(":")[0]
    if result.state != "done":
        return result.state
    if any("outside the bin" in event for event in result.world_events):
        return "released outside the bin"
    for reason in ("unreachable", "approach_lost", "approach_timeout",
                   "grasp_failed"):
        if result.reasons.get(reason):
            return reason
    return "brick never found"


__all__ = ["BRICK_SIZE_MM", "CameraNoise", "PickPlaceWorld", "SimBin",
           "SimBrick", "SimCameraSource", "TrialResult", "DEFAULTS",
           "random_layout", "run_trial", "run_trials"]
