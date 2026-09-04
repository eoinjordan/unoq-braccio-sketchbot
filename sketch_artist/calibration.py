"""Calibrate the drawing plane using the gripper-mounted camera.

Detects the (rectangular) paper sheet in the gripper camera view and computes a
homography from camera pixels to paper millimetres, saved to a JSON file. This
lets the app verify the paper is where ``workspace.yaml`` says it is and lands
drawings inside the branded box.

This is a *starting point*: it finds the largest 4-corner contour and assumes it
is the paper. Tune lighting / thresholds for your booth, or replace with an
ArUco/AprilTag marker for robustness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import config as cfg
from .arm_client import move_to_pose
from .cameras import open_camera


def find_paper_quad(bgr: np.ndarray) -> Optional[np.ndarray]:
    """Return the 4 corner points of the largest paper-like quad, or None."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(biggest, True)
    approx = cv2.approxPolyDP(biggest, 0.02 * peri, True)
    if len(approx) != 4:
        return None
    return _order_corners(approx.reshape(4, 2).astype(np.float32))


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order corners as [top-left, top-right, bottom-right, bottom-left]."""
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    return np.array([
        pts[np.argmin(s)],      # top-left
        pts[np.argmin(diff)],   # top-right
        pts[np.argmax(s)],      # bottom-right
        pts[np.argmax(diff)],   # bottom-left
    ], dtype=np.float32)


def compute_homography(quad: np.ndarray, paper: dict) -> np.ndarray:
    """Homography mapping camera pixels -> paper millimetres."""
    w = float(paper["width_mm"])
    h = float(paper["height_mm"])
    dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    H, _ = cv2.findHomography(quad, dst)
    return H


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate the paper plane.")
    parser.add_argument("--save", default="config/homography.json",
                        help="Where to write the homography JSON.")
    parser.add_argument("--image", help="Use a still image instead of the camera.")
    parser.add_argument("--host", default="127.0.0.1", help="Arm agent host (for --look).")
    parser.add_argument("--port", type=int, default=8765, help="Arm agent port (for --look).")
    parser.add_argument("--look", action="store_true",
                        help="Aim a single wrist camera at the paper first by "
                             "moving the arm to the workspace 'page' camera pose.")
    args = parser.parse_args(argv)

    conf = cfg.load_all()
    paper = conf["workspace"]["paper"]

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Could not read image: {args.image}")
            return 2
    else:
        if args.look:
            angles = (conf["workspace"].get("camera_poses", {}) or {}).get("page")
            if angles and move_to_pose(angles, host=args.host, port=args.port):
                print("Aimed the wrist camera at the paper.")
            else:
                print("Could not aim the arm; point the camera at the paper manually.")
        cam = open_camera(conf["cameras"], "gripper")
        try:
            frame = cam.read()
        finally:
            cam.close()

    quad = find_paper_quad(frame)
    if quad is None:
        print("Could not find a 4-corner paper outline. Improve contrast/lighting "
              "or use a marker-based target.")
        return 1

    H = compute_homography(quad, paper)
    out = cfg.resolve_path(args.save)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({
        "homography": H.tolist(),
        "corners_px": quad.tolist(),
        "paper_mm": {"width": paper["width_mm"], "height": paper["height_mm"]},
    }, indent=2), encoding="utf-8")
    print(f"Saved homography to {out}")
    print("Detected paper corners (px):", quad.tolist())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
