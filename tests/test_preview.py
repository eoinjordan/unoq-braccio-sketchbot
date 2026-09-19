"""Preview PNG/SVG rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
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


@pytest.mark.parametrize("rotation", [60, -60, 180])
def test_preview_is_independent_of_paper_side(workspace_cfg, tmp_path, rotation):
    strokes = [[(0, 0), (100, 0), (100, 100)]]
    before = plan(strokes, workspace_cfg)
    render_png(before, workspace_cfg, str(tmp_path / "before.png"))
    render_svg(before, workspace_cfg, str(tmp_path / "before.svg"))
    workspace_cfg["paper"]["rotation_deg"] = rotation
    after = plan(strokes, workspace_cfg)
    render_png(after, workspace_cfg, str(tmp_path / "after.png"))
    render_svg(after, workspace_cfg, str(tmp_path / "after.svg"))
    assert Image.open(tmp_path / "before.png").tobytes() == Image.open(tmp_path / "after.png").tobytes()
    assert (tmp_path / "before.svg").read_text() == (tmp_path / "after.svg").read_text()
