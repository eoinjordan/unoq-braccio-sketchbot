"""Preview PNG/SVG rendering."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from sketch_artist.planner import plan
from sketch_artist.preview import render_png, render_svg


def test_render_png_and_svg(workspace_cfg, tmp_path):
    strokes = [[(0, 0), (100, 0), (100, 100)]]
    moves = plan(strokes, workspace_cfg)

    png = render_png(moves, workspace_cfg, str(tmp_path / "preview.png"))
    svg = render_svg(moves, workspace_cfg, str(tmp_path / "preview.svg"))

    assert Path(png).exists()
    assert Image.open(png).size[0] > 0
    assert "<polyline" in Path(svg).read_text(encoding="utf-8")
