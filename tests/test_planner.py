"""Planner: pixel strokes -> ordered pen moves in paper millimetres."""

from __future__ import annotations

import copy

import pytest

from scripts.prepare_contact_portrait import prepare
from sketch_artist.fk import BraccioForwardKinematics
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


def _contact_path_inputs(workspace_cfg):
    workspace_cfg["links"].update(base_height_mm=82, shoulder_mm=125,
                                  elbow_mm=125, wrist_pen_mm=163)
    workspace_cfg["servo_calibration"].update({
        "base": {"offset": 90, "sign": 1},
        "shoulder": {"offset": 180, "sign": -1},
        "elbow": {"offset": 90, "sign": -1},
        "wrist_vertical": {"offset": 90, "sign": -1},
    })
    forward = BraccioForwardKinematics(workspace_cfg)
    contact = [90, 45.9, 47, 17, 90, 90]
    tip = forward.solve(contact)
    commands = []
    for base, shoulder, pen_down in ((90, 48.9, False), (90, 45.9, True),
                                      (90.2, 45.9, True), (91, 45.9, True),
                                      (91, 48.9, False), (89, 45.9, True),
                                      (90, 45.9, True), (90, 48.9, False)):
        angles = [base, shoulder, *contact[2:]]
        commands.append({"angles": angles, "tip_mm": forward.solve(angles).as_tuple(),
                         "pen_down": pen_down})
    candidate = {
        "source": "fixture.png", "source_sha256": "fixture", "source_strokes": 2,
        "contact_model_z_mm": tip.z_mm, "drawing_area_mm": [30, 30],
        "paper": {"origin_x_mm": tip.x_mm - 15, "origin_y_mm": -15,
                  "width_mm": 30, "height_mm": 30, "rotation_deg": 0},
        "commands": commands,
    }
    state = {"armed": False, "arm": {"connected": True, "pose": [92.5, *contact[1:]]},
             "tools": {"active": "sketch"}, "controls": {"child_mode": False},
             "workspace": workspace_cfg,
             "limits": [[0, 180], [15, 165], [3, 180], [17, 180], [0, 180], [10, 110]]}
    return candidate, {"contact": {"servo_deg": contact}}, state


def test_contact_portrait_preserves_plane_lift_and_tool(workspace_cfg):
    candidate, reference, state = _contact_path_inputs(workspace_cfg)
    original = copy.deepcopy(candidate)
    prepared = prepare(candidate, reference, state)
    assert candidate == original
    assert prepared["planned_strokes"] == 2
    assert prepared["base_shift_deg"] == 2.5
    assert prepared["checks"]["minimum_model_travel_clearance_mm"] >= 8
    assert prepared["checks"]["maximum_model_draw_height_error_mm"] <= 0.1
    previous = prepared["expected_start_servo_deg"]
    for command in prepared["commands"]:
        assert command["angles"][3:] == [17, 90, 90]
        assert max(abs(end - start) for start, end in zip(previous, command["angles"])) <= 0.702
        previous = command["angles"]
    assert prepared["commands"][-1]["phase"] == "lift"
    assert prepared["stroke_checkpoints"][-1] == len(prepared["commands"])


@pytest.mark.parametrize("condition", ["armed", "disconnected", "child", "gripper"])
def test_contact_portrait_rejects_unsafe_start(workspace_cfg, condition):
    candidate, reference, state = _contact_path_inputs(workspace_cfg)
    if condition == "armed":
        state["armed"] = True
    elif condition == "disconnected":
        state["arm"]["connected"] = False
    elif condition == "child":
        state["controls"]["child_mode"] = True
    else:
        state["tools"]["active"] = "gripper"
    with pytest.raises(ValueError):
        prepare(candidate, reference, state)


@pytest.mark.parametrize("condition", ["contact", "geometry", "limit", "empty"])
def test_contact_portrait_rejects_changed_path(workspace_cfg, condition):
    candidate, reference, state = _contact_path_inputs(workspace_cfg)
    if condition == "contact":
        state["arm"]["pose"][1] += 1
    elif condition == "geometry":
        candidate["commands"][1]["tip_mm"] = (0, 0, 0)
    elif condition == "limit":
        state["limits"][1][1] = 47
    else:
        candidate["commands"] = []
    with pytest.raises(ValueError):
        prepare(candidate, reference, state)
