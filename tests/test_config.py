"""Config loads and the nominal geometry is self-consistent."""

from __future__ import annotations

from sketch_artist.kinematics import BraccioKinematics

REQUIRED_SECTIONS = ["cameras", "workspace", "drawing", "branding", "scenes"]


def test_load_all_sections(conf):
    for key in REQUIRED_SECTIONS:
        assert key in conf, f"missing config section: {key}"


def test_workspace_required_keys(workspace_cfg):
    for key in ["links", "paper", "pen", "servo_calibration"]:
        assert key in workspace_cfg
    for key in ["base_height_mm", "shoulder_mm", "elbow_mm", "wrist_pen_mm"]:
        assert key in workspace_cfg["links"]


def test_paper_is_within_reach(workspace_cfg):
    """Every paper corner must be reachable at both pen heights.

    Regression guard: the nominal paper box previously sat partly beyond the
    arm's ~248 mm span, so the planner silently skipped a third of every
    drawing. Keep the default box reachable.
    """
    kin = BraccioKinematics(workspace_cfg)
    paper = workspace_cfg["paper"]
    pen = workspace_cfg["pen"]
    ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
    w, h = float(paper["width_mm"]), float(paper["height_mm"])
    corners = [(ox, oy), (ox + w, oy), (ox, oy + h),
               (ox + w, oy + h), (ox + w / 2, oy + h / 2)]
    for z in (float(pen["down_z_mm"]), float(pen["up_z_mm"])):
        for x, y in corners:
            kin.solve(x, y, z)  # must not raise UnreachableError
