"""Inverse kinematics + the forward-kinematics round trip."""

from __future__ import annotations

import math

import pytest

from sketch_artist.fk import BraccioForwardKinematics
from sketch_artist.kinematics import BraccioKinematics, UnreachableError


def test_solve_returns_servos_in_range(workspace_cfg):
    kin = BraccioKinematics(workspace_cfg)
    angles = kin.solve(175, 0, 2)
    for value in angles.as_tuple():
        assert 0 <= value <= 180


def test_unreachable_raises(workspace_cfg):
    kin = BraccioKinematics(workspace_cfg)
    with pytest.raises(UnreachableError):
        kin.solve(1000, 0, 2)


def test_ik_fk_roundtrip(workspace_cfg):
    """FK(IK(p)) should return to p within integer-servo rounding error."""
    kin = BraccioKinematics(workspace_cfg)
    fk = BraccioForwardKinematics(workspace_cfg)
    paper = workspace_cfg["paper"]
    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])

    max_err = 0.0
    for i in range(5):
        for j in range(5):
            x = ox + w * i / 4.0
            y = oy + h * j / 4.0
            z = 2.0
            servos = kin.solve(x, y, z)
            tip = fk.solve(servos.as_tuple())
            err = math.dist((x, y, z), (tip.x_mm, tip.y_mm, tip.z_mm))
            max_err = max(max_err, err)
    assert max_err < 6.0, f"round-trip error too large: {max_err:.2f} mm"
