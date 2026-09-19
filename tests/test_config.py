"""Config loads and the nominal geometry is self-consistent."""

from __future__ import annotations

import configparser
from pathlib import Path

from sketch_artist.kinematics import BraccioKinematics

REQUIRED_SECTIONS = ["cameras", "workspace", "drawing", "branding", "scenes"]


def test_studio_boot_unit_is_persistent_and_motion_disabled():
    unit = configparser.ConfigParser(interpolation=None)
    path = Path(__file__).resolve().parents[1] / "app_lab/braccio_remote_agent/sketchbot-studio.service"
    assert unit.read(path)
    assert unit["Service"]["WorkingDirectory"] == "%h/unoq-braccio-sketchbot"
    assert unit["Service"]["ExecStart"] == "/usr/bin/python3 -m web.server --port 7100"
    assert unit["Service"]["Restart"] == "on-failure"
    assert unit["Install"]["WantedBy"] == "default.target"
    assert unit["Unit"]["Conflicts"] == "braccio-calibrate.service"
    assert "Wants" not in unit["Unit"]
    assert "Requires" not in unit["Unit"]


def test_runtime_overrides_preserve_defaults(tmp_path):
    import shutil
    from sketch_artist import config
    for name in ("cameras", "workspace", "drawing", "branding", "scenes"):
        shutil.copy(config.CONFIG_DIR / f"{name}.yaml", tmp_path)
    before = (tmp_path / "workspace.yaml").read_bytes()
    config.save_overrides({"workspace": {"paper": {"rotation_deg": 60}}}, tmp_path)
    config.save_overrides({"control": {"child_mode": True}}, tmp_path)
    loaded = config.load_all(tmp_path)
    assert loaded["workspace"]["paper"]["rotation_deg"] == 60
    assert loaded["workspace"]["paper"]["width_mm"] == 30
    assert loaded["control"]["child_mode"] is True
    assert (tmp_path / "workspace.yaml").read_bytes() == before


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
