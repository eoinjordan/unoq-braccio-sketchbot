"""Turn a portrait photo into clean line art suitable for pen drawing."""

from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np


def _find_face_cascade(explicit: str = "") -> Optional[str]:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    candidate = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    return candidate if os.path.exists(candidate) else None


def crop_to_face(bgr: np.ndarray, margin: float, cascade_path: str = "") -> np.ndarray:
    """Crop to the largest detected face with padding. Returns input if none."""
    cascade_file = _find_face_cascade(cascade_path)
    if not cascade_file:
        return bgr
    cascade = cv2.CascadeClassifier(cascade_file)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
    if len(faces) == 0:
        return bgr
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    pad_x, pad_y = int(w * margin), int(h * margin)
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(bgr.shape[1], x + w + pad_x)
    y1 = min(bgr.shape[0], y + h + pad_y)
    return bgr[y0:y1, x0:x1]


def _fit_square(bgr: np.ndarray, size: int) -> np.ndarray:
    """Resize preserving aspect ratio and pad to a white square canvas."""
    h, w = bgr.shape[:2]
    scale = size / max(h, w)
    resized = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    canvas = np.full((size, size, 3), 255, dtype=np.uint8)
    rh, rw = resized.shape[:2]
    y0 = (size - rh) // 2
    x0 = (size - rw) // 2
    canvas[y0:y0 + rh, x0:x0 + rw] = resized
    return canvas


def to_line_art(bgr: np.ndarray, drawing_cfg: dict) -> np.ndarray:
    """Convert a BGR photo to a binary edge image (uint8, 255 = ink).

    Returns a square image of side ``capture.target_px``.
    """
    cap_cfg = drawing_cfg.get("capture", {})
    portrait_cfg = drawing_cfg.get("portrait", {})
    edges_cfg = drawing_cfg.get("edges", {})
    size = int(cap_cfg.get("target_px", 512))

    if portrait_cfg.get("detect_face", True):
        bgr = crop_to_face(
            bgr,
            margin=float(portrait_cfg.get("crop_margin", 0.35)),
            cascade_path=str(portrait_cfg.get("face_cascade", "")),
        )

    square = _fit_square(bgr, size)
    gray = cv2.cvtColor(square, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(
        gray,
        d=int(edges_cfg.get("bilateral_d", 7)),
        sigmaColor=float(edges_cfg.get("bilateral_sigma", 75)),
        sigmaSpace=float(edges_cfg.get("bilateral_sigma", 75)),
    )

    method = str(edges_cfg.get("method", "canny")).lower()
    if method == "dog":
        s1 = float(edges_cfg.get("dog_sigma1", 1.0))
        s2 = float(edges_cfg.get("dog_sigma2", 2.4))
        g1 = cv2.GaussianBlur(gray, (0, 0), s1)
        g2 = cv2.GaussianBlur(gray, (0, 0), s2)
        dog = cv2.subtract(g1, g2)
        _, edges = cv2.threshold(dog, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        edges = cv2.Canny(
            gray,
            int(edges_cfg.get("canny_low", 60)),
            int(edges_cfg.get("canny_high", 160)),
        )
    return edges
