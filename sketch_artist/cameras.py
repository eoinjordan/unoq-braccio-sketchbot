"""Resolve and open USB cameras by vendor:product ID.

/dev/videoN numbering is not stable across reboots or replugs, so we map a USB
``VID:PID`` (from ``lsusb``) to the correct capture node by walking sysfs.
"""

from __future__ import annotations

import glob
import os
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


def open_camera(cameras_cfg: dict, role: str) -> Camera:
    """Open the camera configured for a role (``face`` or ``gripper``)."""
    spec = cameras_cfg["cameras"][role]
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
