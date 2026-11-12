"""Object detections from the gripper camera, one text line per frame.

The camera board (a Seeed XIAO ESP32S3 Sense on top of the gripper) runs a
detector and prints one line per frame on its USB serial port::

    DET n=2 yellow 0.42 0.61 0.93 red 0.70 0.33 0.88 bin 0.15 0.20 0.97 ms=41

That is a count, then one group per object (label, x, y, confidence) and the
inference time. x and y are the object's centre in normalised image
coordinates, 0..1, origin at the top left.

The firmware is written separately and the line format may still change, so
everything that knows the format is in this module:

* :func:`parse_det_line` reads a line and is tolerant of the changes that are
  likely: extra ``key=value`` fields anywhere, a count that is missing or does
  not match, commas instead of spaces, extra numbers after the confidence (a
  box size, say), upper case, and log prefixes in front of ``DET``.
* :func:`format_det_line` writes the same format (the simulated camera and the
  tests use it).

Three sources hand frames to the pick-and-place controller through the same
``read(timeout_s)`` call:

* :class:`SerialDetectionSource` reads the XIAO's USB serial port. The port
  is found by Espressif's USB vendor id (303A) unless one is named.
* :class:`ReplayDetectionSource` reads a log recorded earlier.
* ``sketch_artist.sim_camera.SimCameraSource`` renders the lines from the
  software arm (no hardware).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ESPRESSIF_VID = 0x303A
DEFAULT_BAUD = 115200
BRICK_LABELS = ("yellow", "white", "red")
BIN_LABEL = "bin"

_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DET_WORD = re.compile(r"(?:^|[\s:>\]])DET\d*(?=[\s,:]|$)", re.IGNORECASE)
_STAMP = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(?=\S)")


@dataclass(frozen=True)
class Detection:
    """One detected object: its label, image position and confidence."""
    label: str
    x: float
    y: float
    confidence: float
    extra: Tuple[float, ...] = ()


@dataclass
class Frame:
    """Everything the detector reported for one camera frame."""
    detections: List[Detection] = field(default_factory=list)
    inference_ms: Optional[float] = None
    declared_count: Optional[int] = None
    meta: Dict[str, str] = field(default_factory=dict)
    time_s: float = 0.0
    raw: str = ""

    def with_label(self, label: str, minimum: float = 0.0) -> List[Detection]:
        """Detections of one label at or above a confidence, best first."""
        found = [d for d in self.detections
                 if d.label == label and d.confidence >= minimum]
        return sorted(found, key=lambda d: -d.confidence)


def _is_number(token: str) -> bool:
    return bool(_NUMBER.match(token))


def parse_det_line(line: str, time_s: float = 0.0) -> Optional[Frame]:
    """Parse one ``DET`` line. Returns None for anything that is not one.

    A group that cannot be read (too few numbers, a position far outside the
    picture, a confidence that is not 0..1) is dropped on its own; the rest
    of the line is kept. Positions a hair outside 0..1 are clamped.
    """
    if not isinstance(line, str):
        return None
    match = _DET_WORD.search(line)
    if match is None:
        return None
    body = line[match.end():].replace(",", " ").replace(";", " ")
    frame = Frame(time_s=time_s, raw=line.strip())
    label: Optional[str] = None
    numbers: List[float] = []

    def close_group() -> None:
        if label is None or len(numbers) < 3:
            return
        x, y, confidence = numbers[0], numbers[1], numbers[2]
        if not (-0.05 <= x <= 1.05 and -0.05 <= y <= 1.05):
            return
        if not 0.0 <= confidence <= 1.0:
            return
        frame.detections.append(Detection(
            label, min(1.0, max(0.0, x)), min(1.0, max(0.0, y)), confidence,
            tuple(numbers[3:])))

    for token in body.split():
        if "=" in token:
            key, _, value = token.partition("=")
            key = key.strip().lower()
            value = value.strip()
            if key == "n" and value.isdigit():
                frame.declared_count = int(value)
            elif key == "ms" and _is_number(value):
                frame.inference_ms = float(value)
            elif key:
                frame.meta[key] = value
        elif _is_number(token):
            if label is not None:
                numbers.append(float(token))
        else:
            close_group()
            label, numbers = token.strip().lower(), []
    close_group()
    return frame


def format_det_line(detections: Sequence[Detection],
                    inference_ms: Optional[float] = None) -> str:
    """Write detections in the camera's line format."""
    parts = [f"DET n={len(detections)}"]
    for d in detections:
        parts.append(f"{d.label} {d.x:.2f} {d.y:.2f} {d.confidence:.2f}")
    if inference_ms is not None:
        parts.append(f"ms={inference_ms:.0f}")
    return " ".join(parts)


def split_log_line(line: str) -> Tuple[Optional[float], str]:
    """Split ``"12.345 DET ..."`` into its time stamp and the line itself.

    Recorded logs carry the arrival time in seconds in front of each line. A
    plain capture of the serial port, with no stamps, replays as well.
    """
    match = _STAMP.match(line)
    if match and _DET_WORD.search(line[match.end():]):
        return float(match.group(1)), line[match.end():]
    return None, line


def find_camera_port(ports=None) -> Optional[str]:
    """The serial port of the first USB device with Espressif's vendor id.

    ``ports`` is for tests: any iterable of objects with ``vid`` and
    ``device``. Left out, the system's ports are listed with pyserial.
    """
    if ports is None:
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError(
                "Reading the camera needs pyserial (it is in requirements.txt)."
            ) from exc
        ports = list_ports.comports()
    matches = sorted(str(p.device) for p in ports
                     if getattr(p, "vid", None) == ESPRESSIF_VID)
    return matches[0] if matches else None


class DetectionSource:
    """Common interface: ``read`` blocks for the next frame or times out."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def read(self, timeout_s: float) -> Optional[Frame]:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class SerialDetectionSource(DetectionSource):
    """Frames from the camera's USB serial port, newest first.

    A reader thread keeps only the latest frame, so a controller that is busy
    moving the arm never works through a backlog of stale pictures. ``read``
    returns a frame that arrived after the previous one it returned.

    ``opener`` is for tests: a callable returning an object with
    ``readline()`` and ``close()``.
    """

    def __init__(self, port: str = "auto", baud: int = DEFAULT_BAUD,
                 record_path: Optional[str] = None,
                 opener: Optional[Callable[[], object]] = None):
        self.port = port
        self.baud = int(baud)
        self._opener = opener
        self._record_path = record_path
        self._record = None
        self._handle = None
        self._thread: Optional[threading.Thread] = None
        self._condition = threading.Condition()
        self._latest: Optional[Frame] = None
        self._sequence = 0
        self._returned = 0
        self._closed = False
        self.error: Optional[str] = None
        self.lines_seen = 0
        self.lines_parsed = 0

    def open(self) -> "SerialDetectionSource":
        if self._opener is not None:
            self._handle = self._opener()
        else:
            try:
                import serial
            except ImportError as exc:
                raise RuntimeError(
                    "Reading the camera needs pyserial (it is in "
                    "requirements.txt).") from exc
            port = self.port
            if port in (None, "", "auto"):
                port = find_camera_port()
                if port is None:
                    raise RuntimeError(
                        "No USB serial device with Espressif's vendor id "
                        "(303A) was found. Plug the XIAO into the UNO Q, or "
                        "name the port with --port.")
            self.port = port
            self._handle = serial.Serial(port, self.baud, timeout=0.2)
        if self._record_path:
            Path(self._record_path).parent.mkdir(parents=True, exist_ok=True)
            self._record = open(self._record_path, "a", encoding="ascii",
                                errors="replace")
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="detection-serial")
        self._thread.start()
        return self

    def _pump(self) -> None:
        while not self._closed:
            try:
                raw = self._handle.readline()
            except Exception as exc:  # the port went away
                self.error = str(exc)
                break
            if not raw:
                if self._opener is not None:
                    break       # a test stream that has run out
                continue
            text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)
            self.lines_seen += 1
            stamp = time.monotonic()
            frame = parse_det_line(text, stamp)
            if frame is None:
                continue
            self.lines_parsed += 1
            if self._record is not None:
                self._record.write(f"{stamp:.3f} {frame.raw}\n")
                self._record.flush()
            with self._condition:
                self._latest = frame
                self._sequence += 1
                self._condition.notify_all()

    def read(self, timeout_s: float) -> Optional[Frame]:
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while self._sequence == self._returned:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._closed:
                    return None
                self._condition.wait(min(remaining, 0.1))
            self._returned = self._sequence
            return self._latest

    def close(self) -> None:
        self._closed = True
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        for handle in (self._handle, self._record):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
        self._handle = self._record = None

    def __enter__(self):
        return self.open()


class ReplayDetectionSource(DetectionSource):
    """Frames from a recorded log, with their recorded spacing.

    Each line is ``<seconds> DET ...`` as written by ``--record``, or a bare
    ``DET ...`` line, in which case frames are spaced ``period_s`` apart.
    Lines that are not detections are skipped. With ``realtime`` false the
    spacing is kept on a clock of its own and nothing sleeps, which is what
    the tests use; ``read`` returns None once the log has run out or when
    the gap to the next line is longer than the timeout.
    """

    def __init__(self, path: str, realtime: bool = True,
                 period_s: float = 0.05, loop: bool = False):
        self.path = str(path)
        self.realtime = realtime
        self.loop = loop
        self._frames: List[Frame] = []
        clock = 0.0
        first: Optional[float] = None
        with open(self.path, "r", encoding="ascii", errors="replace") as handle:
            for text in handle:
                stamp, line = split_log_line(text)
                frame = parse_det_line(line)
                if frame is None:
                    continue
                if stamp is None:
                    clock += period_s
                else:
                    first = stamp if first is None else first
                    clock = max(clock, stamp - first)
                frame.time_s = clock
                self._frames.append(frame)
        self._index = 0
        self._clock = 0.0
        self._offset = 0.0
        self._started = time.monotonic()

    def __len__(self) -> int:
        return len(self._frames)

    def now(self) -> float:
        if self.realtime:
            return time.monotonic() - self._started
        return self._clock

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.realtime:
            time.sleep(seconds)
        else:
            self._clock += seconds

    def read(self, timeout_s: float) -> Optional[Frame]:
        if self._index >= len(self._frames):
            if not self.loop or not self._frames:
                self.sleep(timeout_s)
                return None
            self._offset = self.now()
            self._index = 0
        frame = self._frames[self._index]
        due = self._offset + frame.time_s
        now = self.now()
        # Frames that fell due while the arm was moving are stale: skip to
        # the newest one that is due, as the serial source does.
        while (self._index + 1 < len(self._frames)
               and self._offset + self._frames[self._index + 1].time_s <= now):
            self._index += 1
            frame = self._frames[self._index]
            due = self._offset + frame.time_s
        wait = due - now
        if wait > timeout_s:
            self.sleep(timeout_s)
            return None
        self.sleep(wait)
        self._index += 1
        stamped = Frame(list(frame.detections), frame.inference_ms,
                        frame.declared_count, dict(frame.meta), self.now(),
                        frame.raw)
        return stamped
