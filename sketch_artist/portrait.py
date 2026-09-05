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


def detect_face_rect(
    bgr: np.ndarray,
    cascade_path: str = "",
    scale_factor: float = 1.1,
    min_neighbors: int = 4,
    min_size_px: int = 60,
) -> Optional[tuple]:
    """Return ``(x, y, w, h)`` of the largest detected face, or None."""
    cascade_file = _find_face_cascade(cascade_path)
    if not cascade_file:
        return None
    cascade = cv2.CascadeClassifier(cascade_file)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=(min_size_px, min_size_px),
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return int(x), int(y), int(w), int(h)


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
    rect = detect_face_rect(bgr, cascade_path, scale_factor, min_neighbors, min_size_px)
    if rect is None:
        return bgr, False
    x, y, w, h = rect
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


def _fit_square_edges(edges: np.ndarray, size: int) -> np.ndarray:
    """Fit a binary edge image into a square canvas, padding with black.

    Unlike ``_fit_square`` (white padding for photos), edge images are white
    lines on black, so the padding must be black or it would be traced as ink.
    """
    h, w = edges.shape[:2]
    scale = size / max(h, w)
    resized = cv2.resize(edges, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((size, size), dtype=np.uint8)
    rh, rw = resized.shape[:2]
    y0 = (size - rh) // 2
    x0 = (size - rw) // 2
    canvas[y0:y0 + rh, x0:x0 + rw] = resized
    _, out = cv2.threshold(canvas, 127, 255, cv2.THRESH_BINARY)
    return out


def _caricature_line_art(bgr: np.ndarray, rect: tuple, drawing_cfg: dict,
                         size: int) -> Optional[np.ndarray]:
    """Caricature line art via person segmentation.

    GrabCut isolates the head + hair + shoulders from the background; the
    silhouette becomes the hair/face outline and interior Canny edges add the
    glasses and features. Returns a square binary image, or None if
    segmentation fails (the caller then falls back to plain edge tracing).
    """
    seg = drawing_cfg.get("segment", {})
    x, y, w, h = rect
    frame_h, frame_w = bgr.shape[:2]
    top = float(seg.get("margin_top", 1.15))
    side = float(seg.get("margin_sides", 0.55))
    bottom = float(seg.get("margin_bottom", 0.95))
    x0 = max(0, int(x - side * w))
    y0 = max(0, int(y - top * h))
    x1 = min(frame_w, int(x + w + side * w))
    y1 = min(frame_h, int(y + h + bottom * h))
    crop = bgr[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]
    if ch < 40 or cw < 40:
        return None

    mask = np.zeros((ch, cw), np.uint8)
    inset_x = max(1, int(0.06 * cw))
    inset_y = max(1, int(0.04 * ch))
    grab_rect = (inset_x, inset_y, cw - 2 * inset_x, ch - 2 * inset_y)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(crop, mask, grab_rect, bgd, fgd,
                    int(seg.get("grabcut_iters", 5)), cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    # Keep only the largest blob so stray background patches are dropped.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = np.where(labels == largest, 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if fg.mean() / 255.0 < 0.05:
        return None

    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    outline = cv2.approxPolyDP(max(contours, key=cv2.contourArea),
                               float(seg.get("outline_simplify_px", 2.5)), True)
    silhouette = np.zeros((ch, cw), np.uint8)
    cv2.drawContours(silhouette, [outline], -1, 255, 2)

    # Interior features (glasses, eyes, beard), kept inside an eroded mask so
    # neither the outline nor the background is retraced.
    inner = cv2.erode(fg, np.ones((7, 7), np.uint8))
    gray = cv2.bilateralFilter(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 9, 75, 75)
    interior = cv2.Canny(gray, int(seg.get("interior_canny_low", 40)),
                         int(seg.get("interior_canny_high", 120)))
    interior = cv2.bitwise_and(interior, interior, mask=inner)
    # Bridge broken Canny fragments so the glasses/eyes trace as whole strokes
    # (short fragments are otherwise dropped by the vectorizer length filter).
    interior = cv2.morphologyEx(interior, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    combined = cv2.max(silhouette, interior)
    return _fit_square_edges(combined, size)


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

    # Best path when the model is on disk: a small ONNX line-art generator that
    # draws the eyes, nose and mouth the edge detectors miss. Falls through to
    # the classic tracers when onnxruntime or the model file is absent.
    neural_cfg = drawing_cfg.get("neural_lineart", {})
    if neural_cfg.get("enabled", True):
        from . import lineart_onnx
        rect = detect_face_rect(
            bgr,
            cascade_path=str(portrait_cfg.get("face_cascade", "")),
            scale_factor=float(portrait_cfg.get("scale_factor", 1.1)),
            min_neighbors=int(portrait_cfg.get("min_neighbors", 4)),
            min_size_px=int(portrait_cfg.get("min_size_px", 60)),
        ) if portrait_cfg.get("detect_face", True) else None
        art = lineart_onnx.line_art(bgr, rect, drawing_cfg, size)
        if art is not None:
            return art

    # Preferred path: segment the person so the hair/head outline is drawn and a
    # busy background is removed. Falls back to plain edge tracing on failure.
    if portrait_cfg.get("detect_face", True) and portrait_cfg.get("segment_person", True):
        rect = detect_face_rect(
            bgr,
            cascade_path=str(portrait_cfg.get("face_cascade", "")),
            scale_factor=float(portrait_cfg.get("scale_factor", 1.1)),
            min_neighbors=int(portrait_cfg.get("min_neighbors", 4)),
            min_size_px=int(portrait_cfg.get("min_size_px", 60)),
        )
        if rect is not None:
            art = _caricature_line_art(bgr, rect, drawing_cfg, size)
            if art is not None:
                return art

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
