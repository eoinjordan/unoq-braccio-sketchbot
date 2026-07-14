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
) -> Optional["cv2.VideoCapture"]:
    """Open one node and return the capture only if it delivers a real frame.

    Forces MJPG, which most UVC webcams need to stream at speed; a node that
    opens but only yields empty frames (e.g. a metadata node, or an
    unsupported format) is released and ``None`` is returned.
    """
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    # Warm up, then give the sensor several attempts to produce a valid frame.
    for _ in range(max(0, warmup_frames)):
        cap.read()
    for _ in range(10):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size > 0:
            return cap
    cap.release()
    return None


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
        for device in candidates:
            cap = _open_capture(device, width, height, warmup_frames)
            if cap is not None:
                self.cap = cap
                self.device = device
                break
        if self.cap is None:
            tried = ", ".join(candidates)
            raise RuntimeError(
                f"Camera {usb_id} opened but produced no frames on any of its "
                f"nodes ({tried}). If another process is using it (e.g. an App "
                f"Lab camera streamer), stop it; otherwise check the cable and "
                f"that the container is privileged with /dev/video* access."
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
