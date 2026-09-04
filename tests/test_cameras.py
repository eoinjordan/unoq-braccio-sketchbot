"""Camera role resolution, including one-camera (wrist) rigs."""

from __future__ import annotations

import pytest

from sketch_artist.cameras import resolve_camera_spec


def _cfg(cameras):
    return {"cameras": cameras}


def test_dedicated_roles():
    cfg = _cfg({"face": {"usb_id": "1:1"}, "gripper": {"usb_id": "2:2"}})
    assert resolve_camera_spec(cfg, "face")["usb_id"] == "1:1"
    assert resolve_camera_spec(cfg, "gripper")["usb_id"] == "2:2"


def test_single_camera_serves_both_roles():
    cfg = _cfg({"single": {"usb_id": "9:9"}})
    assert resolve_camera_spec(cfg, "face")["usb_id"] == "9:9"
    assert resolve_camera_spec(cfg, "gripper")["usb_id"] == "9:9"


def test_wrist_alias_serves_any_role():
    cfg = _cfg({"wrist": {"usb_id": "7:7"}})
    assert resolve_camera_spec(cfg, "gripper")["usb_id"] == "7:7"


def test_sole_camera_used_for_any_role():
    cfg = _cfg({"whatever": {"usb_id": "3:3"}})
    assert resolve_camera_spec(cfg, "face")["usb_id"] == "3:3"


def test_dedicated_role_preferred_over_shared():
    cfg = _cfg({"face": {"usb_id": "1:1"}, "single": {"usb_id": "9:9"}})
    assert resolve_camera_spec(cfg, "face")["usb_id"] == "1:1"
    assert resolve_camera_spec(cfg, "gripper")["usb_id"] == "9:9"  # falls back


def test_no_usable_camera_raises():
    with pytest.raises(KeyError):
        resolve_camera_spec(_cfg({}), "face")
    # Two ambiguous cameras, neither a role/shared name -> cannot pick one.
    ambiguous = _cfg({"a": {"usb_id": "1:1"}, "b": {"usb_id": "2:2"}})
    with pytest.raises(KeyError):
        resolve_camera_spec(ambiguous, "face")
