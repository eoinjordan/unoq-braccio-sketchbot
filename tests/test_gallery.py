"""Branded postcard rendering + gallery manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from sketch_artist.gallery import publish, render_postcard
from sketch_artist.planner import plan


def test_postcard_and_publish(conf, workspace_cfg, tmp_path):
    strokes = [[(0, 0), (100, 0), (100, 100)]]
    moves = plan(strokes, workspace_cfg)

    branding = copy.deepcopy(conf["branding"])
    gallery_dir = tmp_path / "gallery"
    branding["gallery"]["output_dir"] = str(gallery_dir)
    card = str(gallery_dir / "card.png")

    render_postcard(moves, workspace_cfg, branding, card, title="Test")
    assert Path(card).exists()

    entry = publish(card, branding, title="Test")
    assert entry["title"] == "Test"

    manifest = gallery_dir / "manifest.json"
    assert manifest.exists()
    items = json.loads(manifest.read_text(encoding="utf-8"))
    assert items[0]["file"] == "card.png"
