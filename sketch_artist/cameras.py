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


def resolve_video_device(usb_id: str) -> str:
    """Return the capture node (e.g. ``/dev/video2``) for a ``VID:PID``.

    A single camera often exposes several video nodes (capture + metadata);
    the lowest-numbered node is the capture interface on the Linux UVC driver.
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
    return matches[0]


class Camera:
    """A single opened camera, selected by USB ID."""

    def __init__(self, usb_id: str, width: int, height: int, warmup_frames: int = 4):
        self.usb_id = usb_id
        self.device = resolve_video_device(usb_id)
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {usb_id} at {self.device}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(max(0, warmup_frames)):
            self.cap.read()

    def read(self) -> np.ndarray:
        """Grab a single BGR frame, raising on failure."""
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame from {self.usb_id} ({self.device})")
        return frame

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
