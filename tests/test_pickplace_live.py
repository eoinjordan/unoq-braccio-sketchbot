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
