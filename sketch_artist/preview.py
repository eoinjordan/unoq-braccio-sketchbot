"""Render a planned drawing to a preview PNG and SVG (for dry runs)."""

from __future__ import annotations

from pathlib import Path
from typing import List

from .planner import Move


def _split_polylines(moves: List[Move]):
    """Group pen-down moves into polylines (each a list of (x, y) mm)."""
    lines = []
    current = []
    for m in moves:
        if m.pen_down:
            current.append((m.x_mm, m.y_mm))
        else:
            if len(current) > 1:
                lines.append(current)
            current = []
    if len(current) > 1:
        lines.append(current)
    return lines


def render_png(moves: List[Move], workspace_cfg: dict, out_path: str,
               px_per_mm: float = 4.0) -> str:
    """Draw the toolpath (ink black, pen-up travel light grey) to a PNG."""
    from PIL import Image, ImageDraw

    paper = workspace_cfg["paper"]
    ox = float(paper["origin_x_mm"])
    oy = float(paper["origin_y_mm"])
    w = float(paper["width_mm"])
    h = float(paper["height_mm"])

    W = int(w * px_per_mm) + 20
    H = int(h * px_per_mm) + 20

    def to_px(x_mm, y_mm):
        return (10 + (x_mm - ox) * px_per_mm, 10 + (y_mm - oy) * px_per_mm)

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    # Paper border.
    draw.rectangle([to_px(ox, oy), to_px(ox + w, oy + h)], outline="#cccccc")

    # Pen-up travel in light grey.
    prev = None
    for m in moves:
        p = to_px(m.x_mm, m.y_mm)
        if prev is not None and not m.pen_down:
            draw.line([prev, p], fill="#e0e0e0", width=1)
        prev = p

    # Ink strokes.
    for line in _split_polylines(moves):
        pts = [to_px(x, y) for x, y in line]
        draw.line(pts, fill="#0b1221", width=2, joint="curve")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_svg(moves: List[Move], workspace_cfg: dict, out_path: str) -> str:
    """Write the ink strokes to an SVG (millimetre units)."""
    paper = workspace_cfg["paper"]
    ox = float(paper["origin_x_mm"])
    oy = float(paper["origin_y_mm"])
    w = float(paper["width_mm"])
    h = float(paper["height_mm"])

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" '
        f'viewBox="0 0 {w} {h}">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="white" '
        f'stroke="#cccccc" stroke-width="0.3"/>',
    ]
    for line in _split_polylines(moves):
        pts = " ".join(f"{x - ox:.2f},{y - oy:.2f}" for x, y in line)
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="#0b1221" '
            f'stroke-width="0.6" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    parts.append("</svg>")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")
    return out_path
