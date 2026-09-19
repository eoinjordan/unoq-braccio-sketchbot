"""Planner: pixel strokes -> ordered pen moves in paper millimetres."""

from __future__ import annotations

import copy

import pytest

from sketch_artist.paper import paper_to_world, world_to_paper
from sketch_artist.planner import Move, move_count, plan


def test_empty_strokes(workspace_cfg):
    assert plan([], workspace_cfg) == []


def test_penup_pendown_structure(workspace_cfg):
    strokes = [[(0, 0), (10, 0), (10, 10)]]
    moves = plan(strokes, workspace_cfg)
    assert moves[0].pen_down is False     # travel to the first point
    assert moves[1].pen_down is True      # pen down to start drawing
    assert moves[-1].pen_down is False    # final lift
    down, up = move_count(moves)
    assert down >= 3
    assert up >= 1


def test_moves_stay_within_paper(workspace_cfg):
    strokes = [[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]]
    moves = plan(strokes, workspace_cfg)
    paper = workspace_cfg["paper"]
    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])
    eps = 1e-6
    for m in moves:
        assert ox - eps <= m.x_mm <= ox + w + eps
        assert oy - eps <= m.y_mm <= oy + h + eps


def test_join_gap_keeps_pen_down(workspace_cfg):
    cfg = copy.deepcopy(workspace_cfg)
    cfg["planner"] = {"join_gap_mm": 1000.0}  # merge everything
    strokes = [[(0, 0), (10, 0)], [(11, 0), (20, 0)]]
    moves = plan(strokes, cfg)
    # One pen-up to reach the first point + one final lift = 2 total.
    ups = sum(1 for m in moves if not m.pen_down)
    assert ups == 2


@pytest.mark.parametrize("rotation", [0, 60, -60, 90, 180])
def test_rotated_paper_plan_and_inverse(workspace_cfg, rotation):
    strokes = [[(0, 0), (10, 0), (10, 10), (0, 10)]]
    original = plan(strokes, workspace_cfg)
    workspace_cfg["paper"]["rotation_deg"] = rotation
    rotated = plan(strokes, workspace_cfg)
    paper = workspace_cfg["paper"]
    for before, after in zip(original, rotated):
        local_x = before.x_mm - paper["origin_x_mm"]
        local_y = before.y_mm - paper["origin_y_mm"]
        assert (after.x_mm, after.y_mm) == pytest.approx(paper_to_world(paper, local_x, local_y))
        assert world_to_paper(paper, after.x_mm, after.y_mm) == pytest.approx((local_x, local_y))
        assert after.pen_down == before.pen_down
