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


def test_servo_angles_keep_a_fraction_of_a_degree(workspace_cfg):
    """Whole degrees are ~3 mm at the paper, which is too coarse to draw a face.

    The IK must therefore hand back fractional degrees. Sampling across the
    paper box, at least one solution has to carry a fraction -- if every angle
    came back whole we are silently back to the old resolution.
    """
    kin = BraccioKinematics(workspace_cfg)
    paper = workspace_cfg["paper"]
    x0, y0 = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])
    down_z = float(workspace_cfg["pen"]["down_z_mm"])

    fractional = 0
    for i in range(6):
        for j in range(6):
            angles = kin.solve(x0 + w * i / 5.0, y0 + h * j / 5.0, down_z)
            if any(abs(v - round(v)) > 1e-9 for v in angles.as_tuple()):
                fractional += 1
    assert fractional > 0, "IK is rounding to whole degrees again"


def test_servo_decimals_zero_restores_whole_degrees(workspace_cfg):
    """Firmware that cannot take fractions opts out with servo_decimals: 0."""
    workspace_cfg.setdefault("motion", {})["servo_decimals"] = 0
    kin = BraccioKinematics(workspace_cfg)
    angles = kin.solve(175, 0, 2)
    for value in angles.as_tuple():
        assert value == round(value)


def test_sub_degree_commands_move_the_pen_less_than_a_millimetre(workspace_cfg):
    """A tenth of a degree has to be a visible, sub-millimetre step.

    This is the whole reason the protocol carries floats: at the paper radius
    one degree is ~3 mm, so a tenth should land near 0.3 mm.
    """
    fk = BraccioForwardKinematics(workspace_cfg)
    base = [90.0, 90.0, 90.0, 90.0, 90.0, 90.0]
    nudged = [90.1, 90.0, 90.0, 90.0, 90.0, 90.0]
    a, b = fk.solve(tuple(base)), fk.solve(tuple(nudged))
    step = math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm)
    assert 0.0 < step < 1.0, f"0.1 deg moved the tip {step:.3f} mm"


def test_pen_tilt_round_trips_through_the_fk(workspace_cfg):
    """A tilted pen is still placed exactly: the wrist point moves back along
    the pen and the serial-chain FK lands the tip on the target."""
    import copy
    import math
    from sketch_artist.fk import BraccioForwardKinematics

    # Each tilt gets a target its geometry can reach: a vertical 163 mm pen
    # cannot get out to the shipped (tilt 15) box at all.
    for tilt, (x, y) in ((0.0, (179.0, -20.0)), (10.0, (205.0, -5.0)),
                         (15.0, (235.0, 0.0))):
        cfg = copy.deepcopy(workspace_cfg)
        cfg["links"]["pen_tilt_deg"] = tilt
        cfg["motion"]["servo_decimals"] = 6      # so rounding is not the error
        cfg.pop("servo_limits", None)            # geometry only, here
        kin = BraccioKinematics(cfg)
        fk = BraccioForwardKinematics(cfg)
        for z in (0.0, 5.0):
            tip = fk.solve(kin.solve(x, y, z, strict=True).as_tuple())
            assert math.hypot(tip.x_mm - x, tip.y_mm - y, tip.z_mm - z) < 0.01, (tilt, z, tip)


def test_pen_tilt_opens_the_wrist(workspace_cfg):
    """Every degree of tilt is a degree of wrist clearance - the reason the
    tilt exists (the wrist servo stalls below ~14 deg with the printed grip)."""
    import copy

    def wrist_at(tilt):
        cfg = copy.deepcopy(workspace_cfg)
        cfg["links"]["pen_tilt_deg"] = tilt
        cfg.pop("servo_limits", None)
        paper = cfg["paper"]
        x = float(paper["origin_x_mm"]) + float(paper["width_mm"]) / 2
        y = float(paper["origin_y_mm"]) + float(paper["height_mm"]) / 2
        return BraccioKinematics(cfg).solve(x, y, 0.0).wrist_vertical

    # Not exactly 1:1 because the wrist point moves and the forearm elevation
    # follows it, but the bulk of the tilt shows up at the wrist.
    assert wrist_at(15.0) - wrist_at(0.0) > 10.0


def test_servo_limits_are_honoured(workspace_cfg):
    """A pose that needs a joint inside its declared dead zone is refused in
    strict mode and clamped to the limit otherwise - never commanded."""
    import copy

    cfg = copy.deepcopy(workspace_cfg)
    cfg["links"]["pen_tilt_deg"] = 0.0
    cfg["servo_limits"] = {"wrist_vertical": {"min": 60}}
    kin = BraccioKinematics(cfg)
    paper = cfg["paper"]
    x = float(paper["origin_x_mm"]) + 5.0
    y = float(paper["origin_y_mm"]) + 5.0
    assert kin.margin(x, y, 0.0) < 0                 # needs wrist < 60 here
    with pytest.raises(UnreachableError, match="wrist_vertical"):
        kin.solve(x, y, 0.0, strict=True)
    assert kin.solve(x, y, 0.0).wrist_vertical == 60.0

    with pytest.raises(ValueError, match="servo_limits"):
        cfg["servo_limits"] = {"elbow": {"min": 90, "max": 10}}
        BraccioKinematics(cfg)


def test_configured_box_clears_every_servo_limit(workspace_cfg):
    """The shipped config must be drawable with margin at both pen heights,
    or the arm stalls on a stop exactly the way it did before the tilt."""
    kin = BraccioKinematics(workspace_cfg)
    paper = workspace_cfg["paper"]
    pen = workspace_cfg["pen"]
    worst = 999.0
    for z in (float(pen["down_z_mm"]), float(pen["up_z_mm"])):
        for i in range(7):
            for j in range(7):
                x = float(paper["origin_x_mm"]) + float(paper["width_mm"]) * i / 6
                y = float(paper["origin_y_mm"]) + float(paper["height_mm"]) * j / 6
                worst = min(worst, kin.margin(x, y, z))
    assert worst >= 2.0, f"only {worst:.1f} deg of clearance somewhere in the box"
