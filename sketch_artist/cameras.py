"""Resolve and open USB cameras by vendor:product ID.

/dev/videoN numbering is not stable across reboots or replugs, so we map a USB
``VID:PID`` (from ``lsusb``) to the correct capture node by walking sysfs.
"""

from __future__ import annotations

import glob
import os
import time
import urllib.error
import urllib.request
from typing import List, Optional

import cv2
import numpy as np


def _usb_ids_for_node(node_name: str) -> tuple[Optional[str], Optional[str]]:
    """Return (idVendor, idProduct) for a /dev/videoN node, or (None, None)."""
    device_link = f"/sys/class/video4linux/{node_name}/device"
    path = os.path.realpath(device_link)
    # Walk up the USB device tree until we find idVendor/idProduct.
    for _ in range(6):
        vid_file = os.path.join(path, "idVendor")
        pid_file = os.path.join(path, "idProduct")
        if os.path.exists(vid_file) and os.path.exists(pid_file):
            with open(vid_file, encoding="utf-8") as f:
                vid = f.read().strip().lower()
            with open(pid_file, encoding="utf-8") as f:
                pid = f.read().strip().lower()
            return vid, pid
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None, None


def list_video_nodes() -> List[str]:
    """List all /dev/video* nodes with their USB IDs (for diagnostics)."""
    rows = []
    for path in sorted(glob.glob("/sys/class/video4linux/video*")):
        name = os.path.basename(path)
        vid, pid = _usb_ids_for_node(name)
        rows.append(f"/dev/{name}\t{vid or '????'}:{pid or '????'}")
    return rows


def resolve_video_devices(usb_id: str) -> List[str]:
    """Return all video nodes for a ``VID:PID``, lowest-numbered first.

    A single UVC camera commonly exposes several nodes (e.g. one for video
    capture and one for metadata). We return every match so the opener can try
    each and keep whichever actually delivers frames.
    """
    want_vid, want_pid = usb_id.strip().lower().split(":")
    matches: List[str] = []
    for path in sorted(glob.glob("/sys/class/video4linux/video*")):
        name = os.path.basename(path)
        vid, pid = _usb_ids_for_node(name)
        if vid == want_vid and pid == want_pid:
            matches.append(f"/dev/{name}")
    if not matches:
        available = "\n  ".join(list_video_nodes()) or "(none)"
        raise RuntimeError(
            f"No /dev/video node found for USB id {usb_id}.\n"
            f"Available video nodes:\n  {available}"
        )
    matches.sort(key=lambda d: int(d.rsplit("video", 1)[1]))
    return matches


def resolve_video_device(usb_id: str) -> str:
    """Return the first (lowest-numbered) video node for a ``VID:PID``."""
    return resolve_video_devices(usb_id)[0]


def _open_capture(
    device: str, width: int, height: int, warmup_frames: int
) -> tuple[Optional["cv2.VideoCapture"], str]:
    """Open one node; return ``(capture, note)``.

    ``capture`` is ``None`` on failure and ``note`` says *why* so the caller can
    build a precise error (permission/busy vs. no usable format). We try MJPG
    (fast, what most UVC webcams want), then YUYV, then the driver default, at
    the requested size and a safe 640x480 fallback, keeping whichever first
    delivers a real frame.
    """
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None, "could not open (permission denied or device busy)"
    for fourcc in ("MJPG", "YUYV", None):
        for (w, h) in ((width, height), (640, 480)):
            if fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            for _ in range(max(0, warmup_frames)):
                cap.read()
            for _ in range(10):
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    note = f"{fourcc or 'default'} {frame.shape[1]}x{frame.shape[0]}"
                    return cap, note
    cap.release()
    return None, "opened but delivered no frames (no usable format/size)"


class Camera:
    """A single opened camera, selected by USB ID."""

    def __init__(self, usb_id: str, width: int, height: int, warmup_frames: int = 4):
        self.usb_id = usb_id
        self.width = width
        self.height = height
        self.warmup_frames = warmup_frames
        candidates = resolve_video_devices(usb_id)
        self.cap = None
        self.device = None
        notes = []
        for device in candidates:
            cap, note = _open_capture(device, width, height, warmup_frames)
            notes.append(f"{device}: {note}")
            if cap is not None:
                self.cap = cap
                self.device = device
                break
        if self.cap is None:
            detail = "\n  ".join(notes)
            raise RuntimeError(
                f"Camera {usb_id} could not deliver frames. Per node:\n  "
                f"{detail}\n"
                f"Checks: is this user in the 'video' group? "
                f"(`groups`; `ls -l {candidates[0]}`; fix with "
                f"`sudo usermod -aG video $USER` then re-login). "
                f"Is another process holding it? (`sudo fuser -v /dev/video*`). "
                f"What formats does it support? "
                f"(`v4l2-ctl --list-formats-ext -d {candidates[0]}`)."
            )

    def read(self) -> np.ndarray:
        """Grab a single BGR frame, retrying briefly before failing."""
        for _ in range(5):
            ok, frame = self.cap.read()
            if ok and frame is not None and frame.size > 0:
                return frame
        raise RuntimeError(f"Failed to read frame from {self.usb_id} ({self.device})")


    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self) -> "Camera":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _decode_jpeg(buf: bytes, source: str) -> np.ndarray:
    """Decode JPEG bytes to a BGR frame, or raise a helpful RuntimeError."""
    if not buf:
        raise RuntimeError(f"{source} returned no data")
    frame = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise RuntimeError(f"{source} returned data that is not a decodable JPEG")
    return frame


class HttpCamera:
    """Network camera that fetches JPEG frames over HTTP (e.g. an ESP-EYE).

    ``url`` should return one JPEG per GET (the ESP-EYE firmware's ``/capture``).
    Constructing it does no network I/O; frames are fetched on ``read()``.
    """

    def __init__(self, url: str, width: int = 0, height: int = 0,
                 warmup_frames: int = 0, timeout: float = 5.0, **_):
        self.url = url
        self.timeout = float(timeout)
        self.width = width
        self.height = height
        for _ in range(max(0, int(warmup_frames))):
            try:
                self._grab()
            except RuntimeError:
                break

    def _grab(self) -> np.ndarray:
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                data = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"Could not fetch a frame from {self.url}: {exc}. Is the ESP-EYE "
                f"powered and on the same network? Try opening {self.url} in a "
                f"browser."
            ) from exc
        return _decode_jpeg(data, self.url)

    def read(self) -> np.ndarray:
        last: Optional[RuntimeError] = None
        for _ in range(3):
            try:
                return self._grab()
            except RuntimeError as exc:
                last = exc
        assert last is not None
        raise last

    def close(self) -> None:
        pass

    def __enter__(self) -> "HttpCamera":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class SerialCamera:
    """Camera that pulls framed JPEGs from an ESP-EYE over USB serial.

    Protocol: send ``b"C"``; read the ``0xA5 0x5A`` magic, a uint32
    little-endian length, then that many JPEG bytes. See
    ``firmware/esp_eye_camera/README.md``.
    """

    def __init__(self, port: str = "auto", baud: int = 921600,
                 width: int = 0, height: int = 0, warmup_frames: int = 0,
                 timeout: float = 6.0, **_):
        try:
            import serial  # pyserial
        except ImportError as exc:
            raise RuntimeError(
                "The USB (serial) camera needs pyserial. Install it with "
                "`.venv/bin/pip install pyserial` (it is in requirements.txt)."
            ) from exc
        self.baud = int(baud)
        self.timeout = float(timeout)
        self.width = width
        self.height = height
        self.port = self._resolve_port(port)
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.2)  # let the board settle after the port opens
        for _ in range(max(0, int(warmup_frames))):
            try:
                self._grab()
            except RuntimeError:
                break

    @staticmethod
    def _resolve_port(port: str) -> str:
        if port and port != "auto":
            return port
        candidates = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        if not candidates:
            raise RuntimeError(
                "No /dev/ttyUSB*/ttyACM* port found for the ESP-EYE. Is it "
                "plugged into the UNO Q's USB-C? Set an explicit 'serial:' path "
                "in config/cameras.yaml if needed."
            )
        return candidates[0]

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        deadline = time.monotonic() + self.timeout
        while len(buf) < n:
            chunk = self.ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
            elif time.monotonic() > deadline:
                raise RuntimeError(
                    f"Timed out reading from the ESP-EYE on {self.port}")
        return bytes(buf)

    def _grab(self) -> np.ndarray:
        self.ser.reset_input_buffer()
        self.ser.write(b"C")
        self.ser.flush()
        # Scan for the magic so boot-log text on the same UART cannot desync us.
        deadline = time.monotonic() + self.timeout
        prev = b""
        while True:
            b = self.ser.read(1)
            if not b:
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"No response from the ESP-EYE on {self.port}. Is "
                        f"esp_eye_camera flashed and the baud {self.baud}?")
                continue
            if prev == b"\xa5" and b == b"\x5a":
                break
            prev = b
        length = int.from_bytes(self._read_exact(4), "little")
        if length == 0:
            raise RuntimeError("ESP-EYE reported no frame (camera not ready)")
        if length > 2_000_000:
            raise RuntimeError(
                f"ESP-EYE frame length {length} looks wrong; check the baud "
                f"rate ({self.baud}).")
        return _decode_jpeg(self._read_exact(length), f"{self.port} (serial)")

    def read(self) -> np.ndarray:
        last: Optional[RuntimeError] = None
        for _ in range(3):
            try:
                return self._grab()
            except RuntimeError as exc:
                last = exc
        assert last is not None
        raise last

    def close(self) -> None:
        if getattr(self, "ser", None) is not None:
            self.ser.close()
            self.ser = None

    def __enter__(self) -> "SerialCamera":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def resolve_camera_spec(cameras_cfg: dict, role: str) -> dict:
    """Return the camera spec for a ``role`` (``face``/``gripper``).

    Supports a **one-camera rig**: if the role has no dedicated entry, fall back
    to a shared ``single`` (or ``wrist``) camera, or to the sole camera when
    exactly one is configured. That lets a single wrist-mounted camera serve
    both the portrait capture and the paper calibration.
    """
    cams = cameras_cfg.get("cameras", {}) or {}

    def usable(spec) -> bool:
        return isinstance(spec, dict) and bool(
            spec.get("usb_id") or spec.get("url") or spec.get("serial"))

    if usable(cams.get(role)):
        return cams[role]
    for shared in ("single", "wrist"):
        if usable(cams.get(shared)):
            return cams[shared]
    only = [s for s in cams.values() if usable(s)]
    if len(only) == 1:
        return only[0]
    raise KeyError(
        f"No camera configured for role '{role}'. Add a 'cameras.{role}' entry, "
        f"or a shared 'cameras.single' camera for a one-camera (wrist) rig. A "
        f"camera entry needs a 'usb_id' (USB webcam), a 'url' (ESP-EYE over "
        f"Wi-Fi) or a 'serial' path (ESP-EYE over USB).")


def open_camera(cameras_cfg: dict, role: str):
    """Open the camera for a role (``face``/``gripper``), or the shared
    single/wrist camera on a one-camera rig.

    Supports three sources, chosen by the config entry: a USB webcam
    (``usb_id``), an ESP-EYE over Wi-Fi (``url``) or an ESP-EYE over USB serial
    (``serial``). All return an object with ``read() -> BGR frame`` / ``close()``.
    """
    spec = resolve_camera_spec(cameras_cfg, role)
    if spec.get("url"):
        return HttpCamera(
            url=str(spec["url"]),
            width=int(spec.get("width", 0)),
            height=int(spec.get("height", 0)),
            warmup_frames=int(spec.get("warmup_frames", 0)),
            timeout=float(spec.get("timeout", 5.0)),
        )
    if spec.get("serial"):
        return SerialCamera(
            port=str(spec.get("serial", "auto")),
            baud=int(spec.get("baud", 921600)),
            width=int(spec.get("width", 0)),
            height=int(spec.get("height", 0)),
            warmup_frames=int(spec.get("warmup_frames", 0)),
            timeout=float(spec.get("timeout", 6.0)),
        )
    return Camera(
        usb_id=spec["usb_id"],
        width=int(spec.get("width", 1280)),
        height=int(spec.get("height", 720)),
        warmup_frames=int(spec.get("warmup_frames", 4)),
    )


def _diagnose() -> int:
    """Print all video nodes and try to open each configured camera role.

    Run with ``python -m sketch_artist.cameras`` to see exactly which node a
    role resolves to, which format/size worked, or the precise failure.
    """
    print("Video nodes (USB id):")
    for row in list_video_nodes():
        print("  " + row)

    from .config import load_yaml

    cams = load_yaml("cameras.yaml").get("cameras", {})
    if not cams:
        print("\nNo cameras configured in config/cameras.yaml")
        return 1

    failures = 0
    for role, spec in cams.items():
        if spec.get("url") or spec.get("serial"):
            kind = "url" if spec.get("url") else "serial"
            print(f"\n[{role}] {kind}={spec.get('url') or spec.get('serial')}")
            try:
                cam = open_camera({"cameras": {role: spec}}, role)
                frame = cam.read()
                print(f"  OK -> frame {frame.shape[1]}x{frame.shape[0]}")
                cam.close()
            except RuntimeError as exc:
                print("  FAIL: " + str(exc).replace("\n", "\n  "))
                failures += 1
            continue
        usb = spec.get("usb_id", "")
        print(f"\n[{role}] usb_id={usb}")
        try:
            print("  nodes: " + ", ".join(resolve_video_devices(usb)))
        except RuntimeError as exc:
            print("  " + str(exc).replace("\n", "\n  "))
            failures += 1
            continue
        try:
            cam = Camera(
                usb_id=usb,
                width=int(spec.get("width", 1280)),
                height=int(spec.get("height", 720)),
                warmup_frames=int(spec.get("warmup_frames", 4)),
            )
            frame = cam.read()
            print(f"  OK -> {cam.device}, frame {frame.shape[1]}x{frame.shape[0]}")
            cam.close()
        except RuntimeError as exc:
            print("  FAIL: " + str(exc).replace("\n", "\n  "))
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_diagnose())
