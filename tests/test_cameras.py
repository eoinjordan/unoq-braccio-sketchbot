"""Camera role resolution, including one-camera (wrist) rigs."""

from __future__ import annotations

from unittest.mock import Mock
from types import SimpleNamespace

import pytest
import numpy as np

from sketch_artist.cameras import HttpCamera, TransformedCamera, open_camera, resolve_camera_spec


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


def test_esp_eye_url_resolves():
    cfg = _cfg({"single": {"url": "http://esp-eye.local/capture"}})
    assert resolve_camera_spec(cfg, "face")["url"] == "http://esp-eye.local/capture"


def test_esp_eye_serial_resolves():
    cfg = _cfg({"single": {"serial": "/dev/ttyUSB0", "baud": 921600}})
    assert resolve_camera_spec(cfg, "gripper")["serial"] == "/dev/ttyUSB0"


def test_open_camera_dispatches_to_http_without_io():
    # Constructing an HttpCamera must not touch the network, so this is safe.
    cam = open_camera(_cfg({"single": {"url": "http://127.0.0.1:1/capture"}}), "face")
    assert isinstance(cam, HttpCamera)
    assert cam.url == "http://127.0.0.1:1/capture"
    cam.close()


@pytest.mark.parametrize(("which", "role"), [("person", "face"), ("page", "gripper")])
def test_fixed_camera_does_not_move_arm(monkeypatch, which, role):
    from sketch_artist import cli
    move_to_pose = Mock(return_value=True)
    monkeypatch.setattr(cli, "move_to_pose", move_to_pose)
    monkeypatch.setattr(cli.time, "sleep", Mock())
    conf = {
        "cameras": _cfg({role: {"url": "http://127.0.0.1:1/capture",
                                "mounted_on_arm": False}}),
        "workspace": {"camera_poses": {which: [90, 130, 45, 30, 90, 90]}},
    }
    cli._look_at(conf, "127.0.0.1", 8765, which, slow=True)
    move_to_pose.assert_not_called()


def test_shared_wrist_camera_still_aims(monkeypatch):
    from sketch_artist import cli
    move_to_pose = Mock(return_value=True)
    monkeypatch.setattr(cli, "move_to_pose", move_to_pose)
    monkeypatch.setattr(cli.time, "sleep", Mock())
    angles = [90, 130, 45, 30, 90, 90]
    conf = {
        "cameras": _cfg({"single": {"url": "http://127.0.0.1:1/capture"}}),
        "workspace": {"camera_poses": {"person": angles}},
    }
    cli._look_at(conf, "127.0.0.1", 8765, "person", slow=True)
    move_to_pose.assert_called_once_with(angles, host="127.0.0.1", port=8765)


@pytest.mark.parametrize("cameras", [{}, {"face": {"enabled": False}}])
def test_missing_or_disabled_camera_does_not_aim_arm(monkeypatch, cameras):
    from sketch_artist import cli
    motion = Mock()
    monkeypatch.setattr(cli, "move_to_pose", motion)
    conf = {"cameras": _cfg(cameras), "workspace": {
        "camera_poses": {"person": [90, 130, 45, 30, 90, 90]}}}
    cli._look_at(conf, "127.0.0.1", 8765, "person", slow=True)
    motion.assert_not_called()


def test_portrait_cli_refuses_physical_drawing_in_gripper_mode(monkeypatch):
    from sketch_artist import cli
    monkeypatch.setattr(cli.cfg, "load_all", lambda: {"tools": {"active": "gripper"}})
    motion = Mock()
    monkeypatch.setattr(cli, "_draw_on_arm", motion)
    assert cli.run(SimpleNamespace(dry_run=False, no_arm=False, sim=False)) == 2
    motion.assert_not_called()


@pytest.mark.parametrize("mode", ["dry_run", "no_arm", "sim"])
def test_no_motion_modes_never_aim_physical_wrist_camera(monkeypatch, mode):
    from sketch_artist import cli
    monkeypatch.setattr(cli.cfg, "load_all", lambda: {})
    aiming = Mock()
    monkeypatch.setattr(cli, "_look_at", aiming)
    monkeypatch.setattr(cli, "_capture_face", Mock(side_effect=RuntimeError("No test camera")))
    values = {"dry_run": False, "no_arm": False, "sim": False, "image": None,
              "host": "127.0.0.1", "port": 8765, "slow": False}
    values[mode] = True
    assert cli.run(SimpleNamespace(**values)) == 2
    aiming.assert_not_called()


def test_disabled_role_does_not_fall_back():
    with pytest.raises(KeyError, match="disabled"):
        resolve_camera_spec(_cfg({"face": {"enabled": False},
                                  "single": {"url": "http://camera/capture"}}), "face")


def test_device_zero_is_a_usable_camera():
    assert resolve_camera_spec(_cfg({"gripper": {"device": 0}}), "gripper")["device"] == 0


@pytest.mark.parametrize("format", ["mjpeg", "rtsp"])
def test_network_stream_dispatch(monkeypatch, format):
    from sketch_artist import cameras
    opener = Mock()
    monkeypatch.setattr(cameras, "VideoCamera", opener)
    open_camera(_cfg({"face": {"url": "http://camera/stream", "format": format}}), "face")
    assert opener.call_args.kwargs["stream"] is True
    assert opener.call_args.kwargs["source"] == "http://camera/stream"


def test_explicit_usb_format_dispatch(monkeypatch):
    from sketch_artist import cameras
    opener = Mock()
    monkeypatch.setattr(cameras, "VideoCamera", opener)
    open_camera(_cfg({"gripper": {"device": 0, "pixel_format": "NV12", "fps": 15}}), "gripper")
    assert opener.call_args.kwargs["source"] == 0
    assert opener.call_args.kwargs["pixel_format"] == "NV12"
    assert opener.call_args.kwargs["fps"] == 15


def test_camera_orientation_and_close():
    camera = Mock()
    camera.read.return_value = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    with TransformedCamera(camera, rotation=90, mirror=True) as transformed:
        np.testing.assert_array_equal(transformed.read(), camera.read.return_value.transpose(1, 0, 2))
    camera.close.assert_called_once()


def test_invalid_rotation_does_not_open_camera(monkeypatch):
    from sketch_artist import cameras
    opener = Mock()
    monkeypatch.setattr(cameras, "_open_spec", opener)
    with pytest.raises(ValueError, match="rotation"):
        open_camera(_cfg({"face": {"device": 0, "rotation": 45}}), "face")
    opener.assert_not_called()
