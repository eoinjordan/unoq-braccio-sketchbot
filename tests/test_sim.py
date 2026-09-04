"""Software simulator: forward kinematics + stroke recording + rendering."""

from __future__ import annotations

from pathlib import Path

from sketch_artist.kinematics import BraccioKinematics
from sketch_artist.sim import SketchbotSimulator


def test_records_single_stroke_and_renders(workspace_cfg, tmp_path):
    kin = BraccioKinematics(workspace_cfg)
    sim = SketchbotSimulator(workspace_cfg)
    pen = workspace_cfg["pen"]
    down_z, up_z = float(pen["down_z_mm"]), float(pen["up_z_mm"])
    points = [(150, -20), (160, -10), (170, 0)]

    # Pen up to the start, draw the three points, then lift.
    sim.apply_move(kin.solve(points[0][0], points[0][1], up_z).as_tuple())
    for x, y in points:
        sim.apply_move(kin.solve(x, y, down_z).as_tuple())
    sim.apply_move(kin.solve(points[-1][0], points[-1][1], up_z).as_tuple())
    sim.finish()

    assert len(sim.polylines) == 1
    assert len(sim.polylines[0]) == len(points)

    out = sim.render(str(tmp_path / "drawing.png"))
    assert Path(out).exists()


def test_apply_move_matches_commanded_point(workspace_cfg):
    kin = BraccioKinematics(workspace_cfg)
    sim = SketchbotSimulator(workspace_cfg)
    tip = sim.apply_move(kin.solve(175, 0, 2).as_tuple())
    assert abs(tip.x_mm - 175) < 5
    assert abs(tip.y_mm - 0) < 5
    assert abs(tip.z_mm - 2) < 3


def test_pen_up_breaks_strokes(workspace_cfg):
    kin = BraccioKinematics(workspace_cfg)
    sim = SketchbotSimulator(workspace_cfg)
    pen = workspace_cfg["pen"]
    down_z, up_z = float(pen["down_z_mm"]), float(pen["up_z_mm"])

    # Two separate down-strokes with a lift between them.
    for x, y in [(150, -20), (160, -20)]:
        sim.apply_move(kin.solve(x, y, down_z).as_tuple())
    sim.apply_move(kin.solve(160, -20, up_z).as_tuple())
    for x, y in [(150, 20), (160, 20)]:
        sim.apply_move(kin.solve(x, y, down_z).as_tuple())
    sim.finish()

    assert len(sim.polylines) == 2
