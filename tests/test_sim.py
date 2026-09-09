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
    # Box-relative and strictly reachable, for the reason given in
    # test_pen_up_breaks_strokes below.
    paper = workspace_cfg["paper"]
    x0, y0 = float(paper["origin_x_mm"]) + 6.0, float(paper["origin_y_mm"]) + 6.0
    points = [(x0, y0), (x0 + 8.0, y0 + 8.0), (x0 + 16.0, y0 + 16.0)]

    # Pen up to the start, draw the three points, then lift.
    sim.apply_move(kin.solve(points[0][0], points[0][1], up_z, strict=True).as_tuple())
    for x, y in points:
        sim.apply_move(kin.solve(x, y, down_z, strict=True).as_tuple())
    sim.apply_move(kin.solve(points[-1][0], points[-1][1], up_z, strict=True).as_tuple())
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

    # Two separate down-strokes with a lift between them, placed relative to
    # the configured paper box so the test survives a re-calibrated rig. The
    # points must be strictly reachable: a non-strict solve silently clamps an
    # out-of-reach point to a pose that is not pen-down at all, which turns
    # this into a test of the geometry rather than of stroke segmentation.
    paper = workspace_cfg["paper"]
    x0 = float(paper["origin_x_mm"]) + 6.0
    x1 = x0 + 10.0
    ya = float(paper["origin_y_mm"]) + 6.0
    yb = float(paper["origin_y_mm"]) + float(paper["height_mm"]) - 6.0
    for x, y in [(x0, ya), (x1, ya)]:
        sim.apply_move(kin.solve(x, y, down_z, strict=True).as_tuple())
    sim.apply_move(kin.solve(x1, ya, up_z, strict=True).as_tuple())
    for x, y in [(x0, yb), (x1, yb)]:
        sim.apply_move(kin.solve(x, y, down_z, strict=True).as_tuple())
    sim.finish()

    assert len(sim.polylines) == 2
