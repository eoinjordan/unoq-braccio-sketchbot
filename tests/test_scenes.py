"""Caricature scene composition."""

from __future__ import annotations

from sketch_artist.scenes import (available_styles, compose, default_style,
                                  resolve_style)


def test_available_styles_include_engineer(conf):
    styles = dict(available_styles(conf["scenes"]))
    assert "engineer" in styles
    assert "none" in styles


def test_resolve_style(conf):
    scenes = conf["scenes"]
    assert resolve_style(scenes, "engineer", interactive=False) == "engineer"
    assert resolve_style(scenes, "nonexistent", interactive=False) == default_style(scenes)


def test_compose_none_keeps_face(conf):
    face = [[(0.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    assert compose(face, "none", conf["scenes"], 512) == face


def test_compose_scene_adds_strokes(conf):
    face = [[(0.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    out = compose(face, "engineer", conf["scenes"], 512)
    assert len(out) > len(face)
