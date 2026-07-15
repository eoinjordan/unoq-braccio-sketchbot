"""Turn a portrait photo into clean line art suitable for pen drawing."""

from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np


def _find_face_cascade(explicit: str = "") -> Optional[str]:
    if explicit:
        return explicit if os.path.exists(explicit) else None

    name = "haarcascade_frontalface_default.xml"
    candidates = []
    # pip opencv-python* bundle the cascades and expose cv2.data.haarcascades;
    # Debian's python3-opencv does not, so also probe the system data dirs.
    data = getattr(cv2, "data", None)
    if data is not None and getattr(data, "haarcascades", None):
        candidates.append(os.path.join(data.haarcascades, name))
    candidates += [
        os.path.join(p, name)
        for p in (
            "/usr/share/opencv4/haarcascades",
            "/usr/share/opencv/haarcascades",
            "/usr/local/share/opencv4/haarcascades",
        )
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def crop_to_face(
    bgr: np.ndarray,
    margin: float,
    cascade_path: str = "",
    scale_factor: float = 1.1,
    min_neighbors: int = 4,
    min_size_px: int = 60,
) -> tuple[np.ndarray, bool]:
    """Crop to the largest detected face with padding.

    Returns ``(image, found)``. When no face is detected ``found`` is False and
    the original image is returned unchanged.
    """
    cascade_file = _find_face_cascade(cascade_path)
    if not cascade_file:
        return bgr, False
    cascade = cv2.CascadeClassifier(cascade_file)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=(min_size_px, min_size_px),
    )
    if len(faces) == 0:
        return bgr, False
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    pad_x, pad_y = int(w * margin), int(h * margin)
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(bgr.shape[1], x + w + pad_x)
    y1 = min(bgr.shape[0], y + h + pad_y)
    return bgr[y0:y1, x0:x1], True


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


def caricature_warp(
    bgr: np.ndarray,
    strength: float,
    center_x: float = 0.5,
    center_y: float = 0.42,
) -> np.ndarray:
    """Radially enlarge the centre of the image for a caricature 'big features'
    look (bigger eyes/nose/mouth, compressed outline).

    ``strength`` 0 returns the input unchanged; ~0.3-0.6 is a gentle-to-strong
    caricature. ``center_x``/``center_y`` are fractions of width/height; the
    default puts the centre slightly high, over the eyes. Dependency-free
    (OpenCV remap only), so no landmark model is required.
    """
    if strength <= 0:
        return bgr
    h, w = bgr.shape[:2]
    cx, cy = w * center_x, h * center_y
    corners = [(0, 0), (w, 0), (0, h), (w, h)]
    max_r = max(np.hypot(px - cx, py - cy) for px, py in corners)
    ys, xs = np.indices((h, w), dtype=np.float32)
    dx = xs - cx
    dy = ys - cy
    r_norm = np.sqrt(dx * dx + dy * dy) / max(max_r, 1e-6)
    # Sample nearer the centre for central pixels => magnifies the middle.
    factor = np.power(np.clip(r_norm, 0.0, 1.0), float(strength))
    map_x = (cx + dx * factor).astype(np.float32)
    map_y = (cy + dy * factor).astype(np.float32)
    return cv2.remap(
        bgr, map_x, map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def to_line_art(bgr: np.ndarray, drawing_cfg: dict) -> np.ndarray:
    """Convert a BGR photo to a binary edge image (uint8, 255 = ink).

    Returns a square image of side ``capture.target_px``.
    """
    cap_cfg = drawing_cfg.get("capture", {})
    portrait_cfg = drawing_cfg.get("portrait", {})
    edges_cfg = drawing_cfg.get("edges", {})
    caricature_cfg = drawing_cfg.get("caricature", {})
    size = int(cap_cfg.get("target_px", 512))

    if portrait_cfg.get("detect_face", True):
        cropped, found = crop_to_face(
            bgr,
            margin=float(portrait_cfg.get("crop_margin", 0.35)),
            cascade_path=str(portrait_cfg.get("face_cascade", "")),
            scale_factor=float(portrait_cfg.get("scale_factor", 1.1)),
            min_neighbors=int(portrait_cfg.get("min_neighbors", 4)),
            min_size_px=int(portrait_cfg.get("min_size_px", 60)),
        )
        if not found:
            print("  ! No face detected; tracing the full frame. Move closer, "
                  "add front lighting, or lower drawing.yaml portrait.min_size_px.")
        bgr = cropped

    # Caricature exaggeration (enlarge central features) before edge tracing.
    if caricature_cfg.get("enabled", True):
        bgr = caricature_warp(
            bgr,
            strength=float(caricature_cfg.get("strength", 0.35)),
            center_x=float(caricature_cfg.get("center_x", 0.5)),
            center_y=float(caricature_cfg.get("center_y", 0.42)),
        )

    square = _fit_square(bgr, size)
    gray = cv2.cvtColor(square, cv2.COLOR_BGR2GRAY)

    # Edge-preserving smoothing. Multiple bilateral passes flatten skin/wall
    # texture (the main source of speckly line art) while keeping strong edges.
    passes = max(1, int(edges_cfg.get("bilateral_passes", 1)))
    for _ in range(passes):
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
        # A fixed threshold drops weak texture; Otsu (threshold <= 0) keeps ~half
        # the image as ink and is far noisier for portraits.
        dog_threshold = int(edges_cfg.get("dog_threshold", 0))
        if dog_threshold > 0:
            _, edges = cv2.threshold(dog, dog_threshold, 255, cv2.THRESH_BINARY)
        else:
            _, edges = cv2.threshold(dog, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        edges = cv2.Canny(
            gray,
            int(edges_cfg.get("canny_low", 60)),
            int(edges_cfg.get("canny_high", 160)),
        )

    # Remove isolated speckle so the vectorizer doesn't trace noise dots.
    open_px = int(edges_cfg.get("despeckle_px", 0))
    if open_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px, open_px))
        edges = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kernel)

    return edges
