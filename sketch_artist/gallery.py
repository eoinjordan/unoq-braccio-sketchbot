"""Composite a finished sketch onto an Edge Impulse branded postcard and keep a
gallery manifest that the web server reads.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

from .config import ensure_dir, resolve_path
from .planner import Move
from .preview import _split_polylines


def _hex(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def render_postcard(moves: List[Move], workspace_cfg: dict, branding_cfg: dict,
                    out_path: str, title: str = "") -> str:
    """Render the drawing inside the branded postcard layout."""
    from PIL import Image, ImageDraw, ImageFont

    brand = branding_cfg["brand"]
    card = branding_cfg["postcard"]
    box = card["drawing_box"]

    W, H = int(card["width_px"]), int(card["height_px"])
    img = Image.new("RGB", (W, H), _hex(card.get("bg_hex", "#FFFFFF")))
    draw = ImageDraw.Draw(img)

    primary = _hex(brand["primary_hex"])
    ink = _hex(brand["ink_hex"])

    # Header band.
    hh = int(card["header_height_px"])
    draw.rectangle([0, 0, W, hh], fill=primary)

    # Optional logo (git-ignored asset; skipped if missing).
    logo_path = resolve_path(brand.get("logo_path", ""))
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((hh - 40, hh - 40))
            img.paste(logo, (30, (hh - logo.height) // 2), logo)
        except Exception:
            pass

    title_font = _font(64)
    tag_font = _font(30)
    draw.text((W - 30, hh // 2 - 40), f"{brand['name']} {brand['title']}",
              font=title_font, fill="white", anchor="rm")
    draw.text((W - 30, hh // 2 + 30), brand["tagline"],
              font=tag_font, fill="white", anchor="rm")

    # Map drawing (paper mm) into the postcard drawing box.
    paper = workspace_cfg["paper"]
    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    pw, ph = float(paper["width_mm"]), float(paper["height_mm"])
    sx = box["w"] / pw
    sy = box["h"] / ph

    def to_px(x_mm, y_mm):
        return (box["x"] + (x_mm - ox) * sx, box["y"] + (y_mm - oy) * sy)

    for line in _split_polylines(moves):
        pts = [to_px(x, y) for x, y in line]
        draw.line(pts, fill=ink, width=3, joint="curve")

    # Footer CTA + QR.
    fh = int(card["footer_height_px"])
    draw.text((40, H - fh + fh // 2), brand.get("cta", ""),
              font=_font(34), fill=ink, anchor="lm")
    qr_path = resolve_path(brand.get("qr_path", ""))
    if qr_path and Path(qr_path).exists():
        try:
            qr = Image.open(qr_path).convert("RGBA")
            qr.thumbnail((fh - 20, fh - 20))
            img.paste(qr, (W - qr.width - 30, H - fh + 10), qr)
        except Exception:
            pass

    if title:
        draw.text((box["x"], box["y"] - 30), title, font=_font(28), fill=ink, anchor="lb")

    ensure_dir(Path(out_path).parent)
    img.save(out_path)
    return out_path


def _font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def publish(out_path: str, branding_cfg: dict, title: str = "") -> dict:
    """Append the finished card to the gallery manifest."""
    gallery_dir = ensure_dir(resolve_path(branding_cfg["gallery"]["output_dir"]))
    manifest = Path(gallery_dir) / "manifest.json"

    items = []
    if manifest.exists():
        try:
            items = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            items = []

    entry = {
        "file": Path(out_path).name,
        "title": title or "Visitor",
        "ts": int(time.time()),
    }
    items.insert(0, entry)
    max_items = int(branding_cfg["gallery"].get("max_items", 24))
    items = items[:max_items]
    manifest.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return entry
