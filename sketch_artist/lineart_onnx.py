"""Neural line art: a small ONNX image-to-image model, run on the CPU.

The classic Canny/DoG path in :mod:`sketch_artist.portrait` traces whatever has
contrast, which on a real photo means it reliably finds the hair silhouette and
the glasses but misses the eyes, nose and mouth -- the features that actually
make a drawing look like someone. This module runs an *Informative Drawings*
generator (Chan et al., "Learning to generate line drawings that convey
geometry and semantics") instead, which was trained to produce exactly the
sparse, semantic strokes a person would draw.

It is deliberately small: a 17 MB ONNX file, ~4.5 M parameters, roughly a second
per frame on a laptop CPU and no GPU anywhere in the loop, so the same code path
runs on the UNO Q. Fetch it once with ``scripts/fetch_lineart_model.sh``.

Everything here degrades to ``None`` rather than raising -- missing
``onnxruntime``, missing model file, a face too small to crop -- so
:func:`sketch_artist.portrait.to_line_art` falls back to the classic edge
tracer and the pipeline keeps working with no model on disk.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import cv2
import numpy as np

# One cached session per model path: building it costs ~200 ms and the CLI
# converts several frames per run.
_SESSIONS: dict = {}


def _session(model_path: str):
    """Return a cached ONNX session, or None if it cannot be built."""
    if model_path in _SESSIONS:
        return _SESSIONS[model_path]
    if not os.path.isfile(model_path):
        _SESSIONS[model_path] = None
        return None
    try:
        import onnxruntime as ort
    except ImportError:
        _SESSIONS[model_path] = None
        return None
    try:
        sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    except Exception:
        sess = None
    _SESSIONS[model_path] = sess
    return sess


def available(model_path: str) -> bool:
    """True when the model can actually be run."""
    return _session(model_path) is not None


def _skeletonize(ink: np.ndarray) -> np.ndarray:
    """Morphological skeleton: reduce ink strokes to ~1 px wide.

    The vectorizer traces contours, so a 3 px line comes back as a loop *around*
    the line and the pen draws it twice. Thinning first makes one stroke one
    pen path.
    """
    img = (ink > 0).astype(np.uint8) * 255
    skel = np.zeros_like(img)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    # Bounded: a 512 px canvas skeletonises well inside 60 passes, and the loop
    # must not depend on the image emptying out exactly.
    for _ in range(60):
        opened = cv2.morphologyEx(img, cv2.MORPH_OPEN, element)
        skel = cv2.bitwise_or(skel, cv2.subtract(img, opened))
        img = cv2.erode(img, element)
        if cv2.countNonZero(img) == 0:
            break
    return skel


def _person_mask(crop: np.ndarray, seg_cfg: dict) -> Optional[np.ndarray]:
    """GrabCut the person out of the crop; returns 255 = person, or None."""
    ch, cw = crop.shape[:2]
    mask = np.zeros((ch, cw), np.uint8)
    inset_x = max(1, int(0.06 * cw))
    inset_y = max(1, int(0.04 * ch))
    rect = (inset_x, inset_y, cw - 2 * inset_x, ch - 2 * inset_y)
    try:
        cv2.grabCut(crop, mask, rect, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64),
                    int(seg_cfg.get("grabcut_iters", 5)), cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    # Open before picking the largest blob: GrabCut habitually leaves a lump of
    # background welded to the subject by a thin neck of pixels (a wall behind
    # the shoulder), and that lump survives a plain largest-component filter.
    open_px = int(seg_cfg.get("mask_open_px", 17))
    if open_px > 0:
        fg = cv2.morphologyEx(
            fg, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px, open_px)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = np.where(labels == largest, 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if fg.mean() / 255.0 < 0.05:
        return None
    return fg


def _crop_around_face(bgr: np.ndarray, rect: Tuple[int, int, int, int],
                      seg_cfg: dict) -> Optional[Tuple[np.ndarray, tuple]]:
    """Crop hair-to-shoulders around the detected face box."""
    x, y, w, h = rect
    fh, fw = bgr.shape[:2]
    top = float(seg_cfg.get("margin_top", 1.15))
    side = float(seg_cfg.get("margin_sides", 0.55))
    bottom = float(seg_cfg.get("margin_bottom", 0.95))
    x0 = max(0, int(x - side * w))
    y0 = max(0, int(y - top * h))
    x1 = min(fw, int(x + w + side * w))
    y1 = min(fh, int(y + h + bottom * h))
    crop = bgr[y0:y1, x0:x1]
    if crop.shape[0] < 40 or crop.shape[1] < 40:
        return None
    return crop, (x0, y0, x1, y1)


def line_art(bgr: np.ndarray, rect: Optional[Tuple[int, int, int, int]],
             drawing_cfg: dict, size: int) -> Optional[np.ndarray]:
    """Run the model and return a square binary edge image (255 = ink).

    ``rect`` is the detected face box, or None to use the whole frame.
    Returns None whenever the neural path is unavailable, so the caller can
    fall back.
    """
    cfg = drawing_cfg.get("neural_lineart", {})
    model_path = str(cfg.get("model_path", "models/lineart_informative.onnx"))
    if not os.path.isabs(model_path):
        from . import config as _cfg
        model_path = str(_cfg.resolve_path(model_path))
    sess = _session(model_path)
    if sess is None:
        return None

    seg_cfg = drawing_cfg.get("segment", {})
    if rect is not None:
        cropped = _crop_around_face(bgr, rect, seg_cfg)
        if cropped is None:
            return None
        crop, _ = cropped
    else:
        crop = bgr

    # --- the model itself -------------------------------------------------
    net_px = int(cfg.get("input_px", 512))
    inp = cv2.resize(crop, (net_px, net_px), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = rgb.transpose(2, 0, 1)[None]
    try:
        out = sess.run(None, {sess.get_inputs()[0].name: tensor})[0][0, 0]
    except Exception:
        return None
    # The generator emits 1.0 for blank paper and 0.0 for ink.
    out = np.clip(out, 0.0, 1.0)

    ink = (out < float(cfg.get("threshold", 0.55))).astype(np.uint8) * 255

    # --- drop the background ---------------------------------------------
    # Without this the model faithfully draws whatever is behind the subject,
    # which on a holiday photo is an entire building.
    silhouette = np.zeros_like(ink)
    if cfg.get("segment_person", True):
        fg = _person_mask(crop, seg_cfg)
        if fg is not None:
            fg_net = cv2.resize(fg, (net_px, net_px), interpolation=cv2.INTER_NEAREST)
            # Erode so the mask edge itself is not traced, and so the fringe of
            # background the mask always keeps around the hair is cut away.
            erode_px = max(1, int(cfg.get("erode_mask_px", 13)))
            inner = cv2.erode(fg_net, np.ones((erode_px, erode_px), np.uint8))
            ink = cv2.bitwise_and(ink, ink, mask=inner)
            if cfg.get("draw_outline", True):
                contours, _ = cv2.findContours(fg_net, cv2.RETR_EXTERNAL,
                                               cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    outline = cv2.approxPolyDP(
                        max(contours, key=cv2.contourArea),
                        float(seg_cfg.get("outline_simplify_px", 2.5)), True)
                    cv2.drawContours(silhouette, [outline], -1, 255, 1)

    if cfg.get("thin", True):
        ink = _skeletonize(ink)

    combined = cv2.max(ink, silhouette)

    # Drop specks the vectorizer would trace as noise dots.
    min_area = int(cfg.get("min_blob_px", 12))
    if min_area > 0:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(combined, 8)
        keep = np.zeros_like(combined)
        for i in range(1, count):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                keep[labels == i] = 255
        combined = keep

    from .portrait import _fit_square_edges
    return _fit_square_edges(combined, size)
