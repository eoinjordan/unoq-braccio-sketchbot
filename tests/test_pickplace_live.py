"""The live driver's model: the Studio gripper solve, mirrored behind the base."""

from __future__ import annotations

import pytest

from sketch_artist.mirrored_arm import mirror
from sketch_artist.pickplace_overhead.live import Model, fit_circle
from sketch_artist.pickplace_overhead.rig import Halt


def test_solve_is_the_studio_pose_mirrored():
    model = Model()
    behind, _ = model.solve_steepest(90.0, 200.0, 90.0)
    assert behind[1] > 90.0                      # leaning over the shoulder
    forward = mirror(behind)
    assert forward[0] == 90.0 and forward[5] == model.open


def test_steepest_reaches_the_floor_and_refuses_the_impossible():
    model = Model()
    angles, pitch = model.solve_steepest(149.0, 204.0, 8.0)
    assert -90.0 <= pitch <= -55.0
    with pytest.raises(Halt):
        model.solve_steepest(90.0, 600.0, 8.0)


def test_fit_circle():
    cx, cy, r = fit_circle([(10, 0), (0, 10), (-10, 0), (0, -10)])
    assert (cx, cy, r) == pytest.approx((0.0, 0.0, 10.0), abs=1e-6)


def test_bin_pose_comes_from_the_rig_file():
    from sketch_artist.pickplace_overhead.live import bin_pose, load_rig
    base, reach, z = bin_pose(load_rig("config/rigs/floor-rig-2026-11-12.yaml"))
    assert base == pytest.approx(56.0, abs=0.2)
    assert reach == pytest.approx(231.0, abs=0.5)
    assert z == pytest.approx(130.0)
    Model().solve_steepest(base, reach, z)          # reachable with the owner's model


def test_gripper_camera_bin_detections_are_ignored():
    from sketch_artist.detections import parse_det_line
    from sketch_artist.pickplace_overhead.live import bricks_only
    notes = []
    frame = parse_det_line("DET n=3 bin 0.43 0.58 0.99 yellow 0.34 0.42 0.93 red 0.7 0.3 0.6 ms=61")
    found = bricks_only(frame, notes.append)
    assert [d.label for d in found] == ["yellow", "red"]
    assert len(notes) == 1 and "ignored 1 bin" in notes[0]
    assert bricks_only(parse_det_line("DET n=1 yellow 0.5 0.5 0.9 ms=60"), notes.append)[0].label == "yellow"
    assert len(notes) == 1
    assert bricks_only(None) == []
