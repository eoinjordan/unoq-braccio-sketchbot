"""Manual controls and discovery must never move hardware implicitly."""

import copy
import shutil
import threading
import time

import pytest

from sketch_artist import config
from web.control import ControlApp, ControlBusy, REST_POSE, check_paper, validate_camera


class FakeArm:
    def __init__(self):
        self.pose = tuple(REST_POSE)
        self.moves = []
        self.reply = "OK"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def status_angles(self):
        return self.pose

    def move(self, angles):
        self.moves.append(angles)
        self.pose = angles
        return self.reply


@pytest.fixture
def controller(tmp_path):
    for name in ("cameras", "workspace", "drawing", "branding", "scenes"):
        shutil.copy(config.CONFIG_DIR / f"{name}.yaml", tmp_path)
    arm = FakeArm()
    app = ControlApp(config_dir=tmp_path, allow_motion=True, arm_factory=lambda: arm)
    yield app, arm
    app.close()


def test_startup_is_read_only_and_defaults_are_disarmed(controller, monkeypatch):
    app, arm = controller
    monkeypatch.setattr("web.control.discover_video_devices", lambda: [])
    report = app.diagnostics()
    assert report["arm"]["connected"]
    assert report["defaults"]["mode"] == "preview"
    assert report["defaults"]["controls"]["child_mode"]
    assert isinstance(report["capabilities"]["face_detection"], bool)
    assert isinstance(report["capabilities"]["esp_serial"], bool)
    assert not app.state()["armed"]
    assert not arm.moves


def test_disconnected_startup_is_not_a_fake_arm(controller, monkeypatch):
    app, arm = controller
    arm.pose = None
    monkeypatch.setattr("web.control.discover_video_devices", lambda: [])
    assert not app.diagnostics()["arm"]["connected"]
    assert not arm.moves


def test_motion_requires_server_opt_in_confirmation_and_held_enable(controller):
    app, arm = controller
    app.allow_motion = False
    with pytest.raises(ValueError, match="disabled"):
        app.arm(True)
    app.allow_motion = True
    with pytest.raises(ValueError, match="confirmation"):
        app.arm(False)
    token = app.arm(True)["token"]
    with pytest.raises(ValueError, match="held"):
        app.move({"token": token, "joint": "base", "delta": 1})
    assert not arm.moves


def test_move_is_bounded_and_stop_revokes_token(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    app.move({"token": token, "held": True, "angles": [140, 45, 180, 180, 90, 10]})
    assert arm.moves[-1][0] == 90.75
    app.stop()
    with pytest.raises(ValueError):
        app.move({"token": token, "held": True, "joint": "base", "delta": 1})
    assert len(arm.moves) == 1


def test_status_read_contention_does_not_reject_or_disarm_motion(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    reading, release = threading.Event(), threading.Event()
    def status_read():
        with app.motion_lock:
            reading.set()
            release.wait(timeout=2)
    worker = threading.Thread(target=status_read)
    worker.start()
    assert reading.wait(timeout=1)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        result = app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
        assert result["pose"][0] == 90.5
        assert app.token == token
        assert len(arm.moves) == 1
    finally:
        release.set()
        worker.join(timeout=2)
        timer.join(timeout=2)


def test_concurrent_motion_is_rejected_without_queueing(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    with app.command_lock:
        with pytest.raises(ControlBusy, match="no move was queued"):
            app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
    assert not arm.moves
    assert app.token == token


def test_stop_cancels_a_move_waiting_for_a_status_read(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    reading, release = threading.Event(), threading.Event()
    def status_read():
        with app.motion_lock:
            reading.set()
            release.wait(timeout=2)
    def stop_and_release():
        app.stop()
        release.set()
    worker = threading.Thread(target=status_read)
    worker.start()
    assert reading.wait(timeout=1)
    timer = threading.Timer(0.1, stop_and_release)
    timer.start()
    try:
        with pytest.raises(ValueError, match="armed session"):
            app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
        assert not arm.moves
        assert app.token is None
    finally:
        release.set()
        worker.join(timeout=2)
        timer.join(timeout=2)


def test_rate_limit_keeps_control_session(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    app.last_move = time.monotonic()
    with pytest.raises(ControlBusy, match="rate limited"):
        app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
    assert not arm.moves
    assert app.token == token


def test_expired_session_and_second_operator_are_rejected(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    with pytest.raises(ValueError, match="already armed"):
        app.arm(True)
    app.armed_until = time.monotonic() - 1
    with pytest.raises(ValueError, match="expired"):
        app.move({"token": token, "held": True, "joint": "base", "delta": 1})
    assert not arm.moves


def test_stop_during_arm_status_query_cancels_arming(controller, monkeypatch):
    app, arm = controller
    def stopping_status():
        app.stop()
        return arm.pose
    monkeypatch.setattr(arm, "status_angles", stopping_status)
    with pytest.raises(ValueError, match="cancelled"):
        app.arm(True)
    assert app.token is None
    assert not arm.moves


@pytest.mark.parametrize("updates", [
    {"motion": {"settle_s": float("nan")}},
    {"pen": {"down_gripper": float("inf")}},
    {"servo_calibration": {"wrist_rotation": {"fixed": float("nan")}}},
    {"camera_poses": {"person": [90, 0, 180, 180, 90, 10]}},
])
def test_invalid_advanced_values_are_not_persisted(controller, updates):
    app, arm = controller
    with pytest.raises(ValueError):
        app.save_workspace(updates)
    assert not (app.config_dir / "runtime.yaml").exists()
    assert not arm.moves


def test_legacy_calibration_updates_the_runtime_overlay(controller, monkeypatch):
    from web import calibrate
    app, arm = controller
    app.save_workspace({"paper": {"rotation_deg": 60}})
    monkeypatch.setattr(calibrate, "WORKSPACE_YAML", app.config_dir / "workspace.yaml")
    calibrate._write_config_keys({"down_z_mm": -1.0, "up_z_mm": 9.0})
    app.state()
    assert app.workspace["pen"]["down_z_mm"] == -1.0
    assert app.workspace["paper"]["rotation_deg"] == 60


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 181])
def test_invalid_joint_targets_never_reach_arm(controller, invalid):
    app, arm = controller
    token = app.arm(True)["token"]
    with pytest.raises(ValueError):
        app.move({"token": token, "held": True, "angles": [invalid, 45, 180, 180, 90, 10]})
    assert not arm.moves


def test_agent_rejection_disarms(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    arm.reply = "ERR stalled"
    with pytest.raises(RuntimeError, match="rejected"):
        app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
    assert app.token is None


def test_unknown_pose_never_falls_back_to_unramped_motion(controller):
    app, arm = controller
    token = app.arm(True)["token"]
    arm.pose = None
    with pytest.raises(RuntimeError, match="current"):
        app.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
    assert not arm.moves
    assert app.token is None


@pytest.mark.parametrize("rotation", [-60, 0, 60])
def test_paper_side_save_is_reachable_and_never_moves(controller, rotation):
    app, arm = controller
    app.save_workspace({"paper": {"rotation_deg": rotation}})
    assert app.workspace["paper"]["rotation_deg"] == rotation
    assert app.conf["calibration_required"]
    assert app.paper_check["ok"]
    assert not arm.moves


def test_unreachable_paper_is_not_persisted(controller):
    app, arm = controller
    before = copy.deepcopy(app.workspace)
    with pytest.raises(ValueError):
        app.save_workspace({"paper": {"rotation_deg": 180}})
    assert app.workspace == before
    assert not (app.config_dir / "runtime.yaml").exists()
    assert not arm.moves


def test_advanced_workspace_roundtrip(controller):
    app, arm = controller
    workspace = copy.deepcopy(app.workspace)
    workspace["paper"]["rotation_deg"] = 60
    app.save_workspace(workspace)
    assert app.workspace["paper"]["rotation_deg"] == 60
    assert not arm.moves


def test_preview_uses_paper_side_without_motion(controller):
    app, arm = controller
    app.save_workspace({"paper": {"rotation_deg": 60}})
    target = app.preview({"x": 15, "y": 15, "z": 10})
    assert target["angles"][0] == pytest.approx(150)
    assert not arm.moves


def test_switch_tools_preserves_sketch_geometry_and_disarms(controller):
    app, arm = controller
    original = copy.deepcopy(app.workspace)
    app.arm(True)
    app.save_tools({"active": "gripper"})
    assert app.token is None
    assert app.workspace == original
    assert app.tool_workspace["links"]["wrist_pen_mm"] == 100
    assert app.state()["tools"]["active"] == "gripper"
    app.save_tools({"active": "sketch"})
    assert app.tool_workspace == original
    assert not arm.moves


def test_gripper_preview_uses_grasp_point_and_requires_tool_confirmation(controller):
    from sketch_artist.fk import BraccioForwardKinematics
    app, arm = controller
    app.save_tools({"active": "gripper"})
    target = app.tools["gripper"]["pick"]
    preview = app.preview(target)
    tip = BraccioForwardKinematics(app.tool_workspace).solve(preview["angles"])
    assert tip.as_tuple() == pytest.approx((target["x"], target["y"], target["z"]), abs=0.5)
    with pytest.raises(ValueError, match="Confirm the gripper"):
        app.arm(True)
    app.paper_check = {"ok": False, "error": "Paper not configured"}
    assert app.arm(True, tool_confirmed=True)["token"]
    assert not arm.moves


def test_pick_place_plan_has_grip_lift_release_order_without_motion(controller):
    app, arm = controller
    app.save_tools({"active": "gripper"})
    task = app.prepare_task({"kind": "pick_place"})
    assert task["count"] == 9
    assert task["checked_poses"] > 100
    assert [point["label"] for point in task["waypoints"]] == [
        "Approach pick", "Open gripper", "Lower to pick", "Grip object", "Lift object",
        "Transfer", "Lower to place", "Release object", "Retract"]
    assert task["waypoints"][3]["angles"][5] == app.tools["gripper"]["closed_deg"]
    assert task["waypoints"][7]["angles"][5] == app.tools["gripper"]["open_deg"]
    assert not arm.moves


def test_pick_place_task_completes_in_bounded_held_steps(controller):
    app, arm = controller
    app.save_tools({"active": "gripper"})
    task = app.prepare_task({"kind": "pick_place"})
    token = app.arm(True, tool_confirmed=True)["token"]
    previous = list(arm.pose)
    for _ in range(1200):
        app.last_move = 0
        result = app.advance_task({"token": token, "held": True, "task_id": task["id"]})
        assert max(abs(value - before) for value, before in zip(result["pose"], previous)) <= 0.751
        previous = result["pose"]
        if result["complete"]:
            break
    assert result["complete"]
    assert app.token is None
    assert app.task is None
    assert arm.pose[5] == app.tools["gripper"]["open_deg"]


def test_stopping_task_holds_gripper_without_release(controller):
    app, arm = controller
    app.save_tools({"active": "gripper"})
    task = app.prepare_task({"kind": "pick_place"})
    token = app.arm(True, tool_confirmed=True)["token"]
    app.advance_task({"token": token, "held": True, "task_id": task["id"]})
    previous = tuple(arm.pose)
    app.stop()
    assert tuple(arm.pose) == previous
    assert app.task is None
    with pytest.raises(ValueError):
        app.advance_task({"token": token, "held": True, "task_id": task["id"]})


def test_concurrent_task_steps_are_rejected_without_queueing(controller):
    app, arm = controller
    app.save_tools({"active": "gripper"})
    task = app.prepare_task({"kind": "pick_place"})
    token = app.arm(True, tool_confirmed=True)["token"]
    with app.task_step_lock:
        with pytest.raises(ControlBusy, match="no move was queued"):
            app.advance_task({"token": token, "held": True, "task_id": task["id"]})
    assert not arm.moves
    assert app.task["index"] == 0
    assert app.token == token


def test_sketch_task_requires_verified_contact_and_adult_mode(controller):
    app, arm = controller
    task = app.prepare_task({"kind": "test_sketch"})
    assert task["requires_contact_confirmation"]
    assert task["waypoints"][0]["label"] == "Approach paper"
    assert task["waypoints"][-1]["label"] == "Pen up"
    token = app.arm(True)["token"]
    with pytest.raises(ValueError, match="supervised mode"):
        app.advance_task({"token": token, "held": True, "task_id": task["id"], "contact_confirmed": True})
    app.controls["child_mode"] = False
    with pytest.raises(ValueError, match="contact height"):
        app.advance_task({"token": token, "held": True, "task_id": task["id"]})
    assert not arm.moves


def test_complete_sketch_task_traces_closed_square_and_finishes_pen_up(controller):
    from sketch_artist.sim import SketchbotSimulator
    app, arm = controller
    app.controls["child_mode"] = False
    task = app.prepare_task({"kind": "test_sketch", "size_mm": 10})
    token = app.arm(True)["token"]
    for _ in range(1200):
        app.last_move = 0
        result = app.advance_task({"token": token, "held": True, "task_id": task["id"], "contact_confirmed": True})
        if result["complete"]:
            break
    assert result["complete"]
    simulator = SketchbotSimulator(app.workspace)
    for angles in arm.moves:
        simulator.apply_move(angles)
    simulator.finish()
    assert len(simulator.polylines) == 1
    assert simulator.fk.solve(arm.pose).z_mm > 9
    assert max(point[0] for point in simulator.polylines[0]) - min(point[0] for point in simulator.polylines[0]) == pytest.approx(10, abs=1)
    assert max(point[1] for point in simulator.polylines[0]) - min(point[1] for point in simulator.polylines[0]) == pytest.approx(10, abs=1)
    assert app.token is None


def test_stale_task_or_external_movement_never_continues(controller):
    app, arm = controller
    app.save_tools({"active": "gripper"})
    task = app.prepare_task({"kind": "pick_place"})
    token = app.arm(True, tool_confirmed=True)["token"]
    with pytest.raises(ValueError, match="stale"):
        app.advance_task({"token": token, "held": True, "task_id": "old"})
    arm.pose = (100, *arm.pose[1:])
    with pytest.raises(ValueError, match="outside this task"):
        app.advance_task({"token": token, "held": True, "task_id": task["id"]})
    assert app.token is None
    assert not arm.moves


@pytest.mark.parametrize("updates", [
    {"active": "unknown"}, {"gripper": {"length_mm": float("nan")}},
    {"gripper": {"closed_deg": 10}}, {"gripper": {"lift_z_mm": 31}},
    {"gripper": {"pick": {"x": 400, "y": 400}}},
])
def test_invalid_gripper_settings_are_rejected_without_motion(controller, updates):
    app, arm = controller
    with pytest.raises(ValueError):
        app.save_tools(updates)
    assert not arm.moves
    assert not (app.config_dir / "runtime.yaml").exists()


@pytest.mark.parametrize("spec", [
    {"format": "snapshot", "url": "file:///etc/passwd"},
    {"format": "usb", "device": "/etc/passwd"},
    {"format": "usb", "device": False},
    {"format": "serial", "serial": "/dev/mmcblk0"},
    {"format": "usb", "device": 0, "rotation": 45},
])
def test_unsafe_camera_settings_are_rejected(spec):
    with pytest.raises(ValueError):
        validate_camera(spec)


def test_camera_transport_switch_clears_old_source(controller):
    app, arm = controller
    app.save_camera("face", {"format": "snapshot", "url": "http://192.168.1.73/capture", "mounted_on_arm": True})
    app.save_camera("face", {"format": "usb", "device": 0, "mounted_on_arm": False})
    saved = app.camera_specs()["face"]
    assert saved["url"] is None
    assert saved["device"] == 0
    assert not saved["mounted_on_arm"]
    assert not arm.moves


def test_disabling_camera_preserves_source_and_mount(controller):
    app, arm = controller
    app.save_camera("face", {"format": "snapshot", "url": "http://127.0.0.1:1/capture", "mounted_on_arm": False})
    app.save_camera("face", {"enabled": False})
    disabled = app.camera_specs()["face"]
    assert disabled["url"] == "http://127.0.0.1:1/capture"
    assert disabled["mounted_on_arm"] is False
    app.save_camera("face", {**disabled, "enabled": True})
    assert app.camera_specs()["face"]["url"] == disabled["url"]
    assert app.camera_specs()["face"]["mounted_on_arm"] is False
    assert not arm.moves


def test_tablet_camera_requires_opt_in_expires_and_never_moves(controller):
    import cv2
    import numpy as np
    app, arm = controller
    _, encoded = cv2.imencode(".jpg", np.zeros((64, 96, 3), dtype=np.uint8))
    data = encoded.tobytes()
    with pytest.raises(ValueError, match="Select Tablet"):
        app.receive_tablet_frame("face", data)
    app.save_camera("face", {"format": "tablet", "mounted_on_arm": True})
    assert not app.camera_specs()["face"]["mounted_on_arm"]
    assert app.receive_tablet_frame("face", data)["width"] == 96
    jpeg, health = app.snapshot("face")
    assert jpeg.startswith(b"\xff\xd8")
    assert health["source"] == "tablet"
    app.tablet_frames["face"]["received"] -= 301
    with pytest.raises(RuntimeError, match="recent tablet"):
        app.tablet_frame("face")
    assert not app.tablet_frames
    assert not arm.moves


def test_tablet_camera_rejects_invalid_content_and_clears_frames(controller):
    import cv2
    import numpy as np
    app, arm = controller
    app.save_camera("gripper", {"format": "tablet"})
    for data in (b"not an image", b"", b"x" * 4_000_001):
        with pytest.raises(ValueError):
            app.receive_tablet_frame("gripper", data)
    _, encoded = cv2.imencode(".png", np.zeros((32, 32, 3), dtype=np.uint8))
    app.receive_tablet_frame("gripper", encoded.tobytes())
    app.clear_tablet_frame("gripper")
    with pytest.raises(RuntimeError):
        app.tablet_frame("gripper")
    assert not arm.moves


def test_controller_preferences_validate_button_conflicts(controller):
    app, arm = controller
    with pytest.raises(ValueError, match="different"):
        app.save_controls({"gamepad_enable_button": 1})
    with pytest.raises(ValueError, match="deadzone"):
        app.save_controls({"gamepad_deadzone": float("nan")})
    app.save_controls({"gamepad_enabled": True, "gamepad_axes": [0, 1, 2, 3]})
    assert app.controls["gamepad_enabled"]
    assert not arm.moves


def test_real_protocol_status_and_one_bounded_move(tmp_path, sim_agent):
    for name in ("cameras", "workspace", "drawing", "branding", "scenes"):
        shutil.copy(config.CONFIG_DIR / f"{name}.yaml", tmp_path)
    sim_agent.simulator.apply_move(REST_POSE)
    with_motion = ControlApp(port=sim_agent.port, allow_motion=True, config_dir=tmp_path)
    try:
        assert with_motion.state()["arm"]["connected"]
        token = with_motion.arm(True)["token"]
        result = with_motion.move({"token": token, "held": True, "joint": "base", "delta": 0.5})
        assert result["pose"][0] == 90.5
        assert sim_agent.simulator.last_angles[0] == 90.5
    finally:
        with_motion.close()