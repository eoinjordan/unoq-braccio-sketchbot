"""The real rig: one overhead camera, the arm agent, and a move that is
checked before it is sent and looked at after it has run.

Nothing here moves the arm except ``Rig.move``. It refuses a target whose
whole joint-space path is not inside the envelope, sends the path in small
steps with a dwell, waits, takes a frame and runs the frame checks. Any
failed check raises ``Halt`` and the arm stays where it is: the caller is
expected to stop, not to retry.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..arm_client import ArmClient
from . import watch
from .geometry import Angles, ArmGeometry, Envelope, interpolate


class Halt(RuntimeError):
    """A check failed. Motion stops; the arm is left where it is."""


# -- camera ---------------------------------------------------------------

def directshow_index(usb_id: str) -> Optional[int]:
    """DirectShow index of the camera with this USB id, e.g. ``vid_1532&pid_0e03``.

    Indexes move when a camera is plugged in or a laptop lid closes, so the
    camera is found by what it is, never by a remembered number. Uses
    ``ffmpeg -list_devices``, which lists without opening anything.
    """
    try:
        r = subprocess.run("ffmpeg -hide_banner -list_devices true -f dshow -i dummy",
                           capture_output=True, text=True, shell=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    index = -1
    lines = r.stderr.splitlines()
    for i, line in enumerate(lines):
        if "(video)" in line:
            index += 1
            alt = lines[i + 1].lower() if i + 1 < len(lines) else ""
            if usb_id.lower() in alt:
                return index
    return None


class OverheadCamera:
    """Keeps the camera open, focus locked, and hands out fresh frames."""

    def __init__(self, usb_id: Optional[str] = None, index: Optional[int] = None,
                 width: int = 1920, height: int = 1080, focus: Optional[float] = None):
        if usb_id:
            index = directshow_index(usb_id)
            if index is None:
                raise RuntimeError("no camera with USB id %s" % usb_id)
        if index is None:
            raise ValueError("give a USB id or an index")
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(int(index), backend)
        if not self.cap.isOpened():
            raise RuntimeError("camera %s did not open" % index)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if focus is not None:
            # Autofocus refocuses on the arm whenever it rises toward the lens
            # and the floor goes soft, so it is turned off and focus is fixed.
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self.cap.set(cv2.CAP_PROP_FOCUS, focus)
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._stamp = 0.0
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        deadline = time.time() + 12.0
        while self._frame is None and time.time() < deadline:
            time.sleep(0.05)
        if self._frame is None:
            self.close()
            raise RuntimeError("camera opened but gave no frames")
        time.sleep(1.0)

    def _run(self) -> None:
        while self._alive:
            ok, frame = self.cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._frame, self._stamp = frame, time.time()
            else:
                time.sleep(0.02)

    def frame(self, average: int = 3, timeout: float = 6.0) -> np.ndarray:
        """Median of a few frames, all captured after this call."""
        start = time.time()
        frames: List[np.ndarray] = []
        last = 0.0
        while len(frames) < average:
            if time.time() - start > timeout:
                raise Halt("camera stopped delivering frames")
            with self._lock:
                stamp, frame = self._stamp, self._frame
            if stamp > start + 0.15 and stamp != last and frame is not None:
                frames.append(frame.copy())
                last = stamp
            time.sleep(0.02)
        if average == 1:
            return frames[0]
        return np.median(np.stack(frames), axis=0).astype(np.uint8)

    def close(self) -> None:
        self._alive = False
        self._thread.join(2.0)
        self.cap.release()


def sweep_focus(camera: OverheadCamera, roi: Tuple[int, int, int, int],
                values: Sequence[float]) -> Tuple[float, float]:
    """Try each manual focus value; return the sharpest and its score."""
    camera.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    best = (float(values[0]), -1.0)
    for value in values:
        camera.cap.set(cv2.CAP_PROP_FOCUS, float(value))
        time.sleep(0.5)
        score = watch.sharpness(camera.frame(average=1), roi)
        if score > best[1]:
            best = (float(value), score)
    camera.cap.set(cv2.CAP_PROP_FOCUS, best[0])
    return best


# -- arm link ---------------------------------------------------------------

class ArmLink:
    """Short-lived connections to the arm agent, one per move.

    The agent drops a client that is silent for 30 s, and a run spends longer
    than that looking at pictures between moves.
    """

    def __init__(self, host: str, port: int = 8765, timeout: float = 8.0):
        self.host, self.port, self.timeout = host, port, timeout

    def pose(self) -> Angles:
        with ArmClient(self.host, self.port, self.timeout) as arm:
            angles = arm.status_angles()
        if angles is None:
            raise Halt("arm agent did not report its pose")
        return angles  # type: ignore[return-value]

    def send(self, steps: Sequence[Angles], dwell_s: float) -> None:
        with ArmClient(self.host, self.port, self.timeout) as arm:
            for i, step in enumerate(steps):
                reply = arm.move(step)
                if reply != "OK":
                    raise Halt("arm agent answered %r at step %d" % (reply, i))
                time.sleep(dwell_s)


# -- checked move -------------------------------------------------------------

@dataclass
class RigConfig:
    max_step_deg: float = 2.5
    dwell_s: float = 0.08
    settle_s: float = 0.7
    min_sharpness: float = 60.0
    sharpness_roi: Optional[Tuple[int, int, int, int]] = None
    watch_margin_px: int = 150          # about 115 mm on the floor
    sheet_radius_px: float = 175.0
    arm_mask_px: int = 130
    min_intruder_px: int = 1500
    check_arm: bool = True


@dataclass
class Rig:
    camera: OverheadCamera
    link: ArmLink
    arm: ArmGeometry
    env: Envelope
    P: np.ndarray                      # camera model used for the arm silhouette
    cfg: RigConfig = field(default_factory=RigConfig)
    log: Callable[[str], None] = print
    frames_dir: Optional[str] = None
    reference: Optional[np.ndarray] = None
    reference_pose: Optional[Angles] = None
    expected_spots: List[Tuple[float, float, float]] = field(default_factory=list)
    _count: int = 0

    def base_px(self) -> Tuple[float, float]:
        from .geometry import project
        return project(self.P, (0.0, 0.0, 0.0))

    def take_reference(self) -> np.ndarray:
        """Remember the scene as it is now, with the arm where it is now."""
        self.reference = self.camera.frame()
        self.reference_pose = self.link.pose()
        self.expected_spots = []
        self.save(self.reference, "reference")
        return self.reference

    def save(self, frame: np.ndarray, label: str) -> None:
        if self.frames_dir:
            name = "%04d_%s.jpg" % (self._count, re.sub(r"[^a-z0-9]+", "_", label.lower()))
            cv2.imwrite(os.path.join(self.frames_dir, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        self._count += 1

    def look(self, pose: Angles, label: str) -> np.ndarray:
        """Take a frame and run every check against the reference."""
        frame = self.camera.frame()
        self.save(frame, label)
        score = watch.sharpness(frame, self.cfg.sharpness_roi)
        if score < self.cfg.min_sharpness:
            raise Halt("frame out of focus after '%s' (sharpness %.0f)" % (label, score))
        if self.reference is None or self.reference_pose is None:
            return frame
        shape = frame.shape
        if self.cfg.check_arm:
            seen = watch.arm_where_expected(frame, self.P, self.arm, pose)
            if not seen.ok:
                raise Halt("arm is not where the pose puts it after '%s' (arm colour at the "
                           "forearm points: %s): base moved or a joint stalled"
                           % (label, seen.fractions))
        covered = watch.arm_mask(shape, self.P, self.arm, pose, self.cfg.arm_mask_px)             | watch.arm_mask(shape, self.P, self.arm, self.reference_pose, self.cfg.arm_mask_px)
        centre = self.base_px()
        # The sheet outline is compared only when the arm is back in the pose
        # of the reference frame. Anywhere else the arm, its shadow and the
        # servo leads cross the sheet and the outline says nothing.
        same_pose = max(abs(a - b) for a, b in zip(pose[:4], self.reference_pose[:4])) < 0.6
        if same_pose:
            shift = watch.base_shift(self.reference, frame, centre, self.cfg.sheet_radius_px)
            if shift.moved:
                raise Halt("base sheet outline changed after '%s' (%d px, %.0f%% of the sheet)"
                           % (label, shift.changed_px, 100 * shift.fraction))
        # The watched zone is the arm's silhouette at both poses, grown by a
        # margin: where the arm is, was, or passed, plus a body width. A
        # person sitting further off than that is not in the arm's way and
        # does not stop the run; one who comes closer does.
        zone = watch.grow(covered, self.cfg.watch_margin_px)
        explained = covered | watch.spots_mask(shape, self.expected_spots)
        found = watch.unexplained_changes(self.reference, frame, zone, explained,
                                          self.cfg.min_intruder_px)
        if found:
            raise Halt("unexplained change after '%s': %s" % (
                label, ", ".join("%d px at (%d, %d)" % (r.area_px, r.x_px, r.y_px) for r in found)))
        return frame

    def move(self, target: Sequence[float], label: str,
             floor_guard_mm: Optional[float] = None, check: bool = True) -> np.ndarray:
        """Checked, ramped move to ``target``; returns the frame taken after it."""
        target = tuple(round(float(a), 1) for a in target)
        start = self.link.pose()
        fault = self.env.check_path(start, target, floor_guard_mm)
        if fault:
            raise Halt("refused '%s': %s" % (label, fault))
        steps = interpolate(start, target, self.cfg.max_step_deg)
        tip = self.arm.chain(target)["tip"]
        self.log("MOVE %-22s %s -> %s  (%d steps, tip r=%.0f z=%.0f)"
                 % (label, _fmt(start), _fmt(target), len(steps), tip[0], tip[1]))
        try:
            self.link.send(steps, self.cfg.dwell_s)
        except OSError as exc:
            raise Halt("lost the arm agent during '%s': %s" % (label, exc))
        time.sleep(self.cfg.settle_s)
        if not check:
            frame = self.camera.frame()
            self.save(frame, label)
            return frame
        return self.look(target, label)  # type: ignore[arg-type]


def _fmt(angles: Sequence[float]) -> str:
    return "(" + ",".join("%g" % a for a in angles) + ")"
