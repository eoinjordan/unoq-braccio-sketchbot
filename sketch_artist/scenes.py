"""Caricature scene templates.

The detected face becomes the head of a themed line-art scene (an engineer at
the bench, a cyclist, a driver, ...). Face strokes are fitted into the scene's
``head_box`` and the scene's own strokes are drawn around them.

Templates live in ``config/scenes.yaml``. All coordinates are fractions of the
square line-art canvas (top-left origin, +y down); this module scales them to
pixels so the result feeds straight into the planner.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Tuple

from .vectorize import Stroke, bounding_box

Box = Tuple[float, float, float, float]  # x, y, w, h in canvas fractions


def available_styles(scenes_cfg: dict) -> List[Tuple[str, str]]:
    """Return ``(name, label)`` for every configured style."""
    styles = scenes_cfg.get("styles", {})
    out: List[Tuple[str, str]] = []
    for name, spec in styles.items():
        label = str((spec or {}).get("label", name))
        out.append((name, label))
    return out


def default_style(scenes_cfg: dict) -> str:
    styles = scenes_cfg.get("styles", {})
    fallback = next(iter(styles), "none")
    return str(scenes_cfg.get("default", fallback))


def resolve_style(scenes_cfg: dict, requested: str | None,
                  interactive: bool) -> str:
    """Pick the style to use.

    Uses ``requested`` if valid; otherwise prompts when ``interactive`` and a
    TTY is present, else falls back to the configured default.
    """
    styles = scenes_cfg.get("styles", {})
    if requested and requested in styles:
        return requested
    if requested:
        print(f"  ! Unknown style '{requested}'; using the default.")
    if interactive and sys.stdin.isatty():
        return _prompt_for_style(scenes_cfg)
    return default_style(scenes_cfg)


def _prompt_for_style(scenes_cfg: dict) -> str:
    options = available_styles(scenes_cfg)
    default = default_style(scenes_cfg)
    print("\nChoose a caricature style:")
    for i, (name, label) in enumerate(options, start=1):
        marker = " (default)" if name == default else ""
        print(f"  {i}. {label}{marker}")
    try:
        choice = input("Style number [Enter for default]: ").strip()
    except EOFError:
        return default
    if not choice:
        return default
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    # Allow typing the style name directly.
    names = {name for name, _ in options}
    if choice in names:
        return choice
    print("  ! Not a valid choice; using the default.")
    return default


def _scale_template_strokes(strokes_cfg: List, canvas_px: int) -> List[Stroke]:
    scaled: List[Stroke] = []
    for poly in strokes_cfg or []:
        pts = [(float(x) * canvas_px, float(y) * canvas_px) for x, y in poly]
        if len(pts) >= 2:
            scaled.append(pts)
    return scaled


def _fit_face_into_box(face_strokes: List[Stroke], box: Box,
                       canvas_px: int) -> List[Stroke]:
    """Scale + translate the face strokes to fit inside ``box`` (fractions)."""
    if not face_strokes:
        return []
    bx, by, bw, bh = box
    tx, ty = bx * canvas_px, by * canvas_px
    tw, th = bw * canvas_px, bh * canvas_px

    min_x, min_y, max_x, max_y = bounding_box(face_strokes)
    src_w = max(1e-6, max_x - min_x)
    src_h = max(1e-6, max_y - min_y)
    scale = min(tw / src_w, th / src_h)

    drawn_w = src_w * scale
    drawn_h = src_h * scale
    off_x = tx + (tw - drawn_w) / 2.0
    off_y = ty + (th - drawn_h) / 2.0

    placed: List[Stroke] = []
    for stroke in face_strokes:
        placed.append([
            (off_x + (x - min_x) * scale, off_y + (y - min_y) * scale)
            for x, y in stroke
        ])
    return placed


def compose(face_strokes: List[Stroke], style: str, scenes_cfg: dict,
            canvas_px: int) -> List[Stroke]:
    """Combine the face line-art with the chosen scene template.

    ``style`` of ``none`` (or an all-canvas head_box) returns the face strokes
    unchanged. Otherwise the face is fitted into the scene's head slot and the
    scene strokes are appended.
    """
    spec: Dict = (scenes_cfg.get("styles", {}) or {}).get(style) or {}
    box: Box = tuple(spec.get("head_box", [0.0, 0.0, 1.0, 1.0]))  # type: ignore[assignment]

    # Full-canvas head box means "no scene": keep the portrait as-is.
    if tuple(box) == (0.0, 0.0, 1.0, 1.0) and not spec.get("strokes"):
        return face_strokes

    placed_face = _fit_face_into_box(face_strokes, box, canvas_px)
    template = _scale_template_strokes(spec.get("strokes", []), canvas_px)
    return template + placed_face
