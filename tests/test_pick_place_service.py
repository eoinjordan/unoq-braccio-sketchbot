"""Reaching behind the base, and pick and place as a boot service."""

from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request

import pytest

from sketch_artist import pick_place_service as svc
from sketch_artist.detections import DetectionSource, parse_det_line
from sketch_artist.fk import BraccioForwardKinematics
from sketch_artist.mirrored_arm import MirroredArm, mirror
from sketch_artist.pick_place import DEFAULTS, MotionGuard, tool_workspace
from sketch_artist.sim import SimArmAgent

REST = (90.0, 45.0, 180.0, 180.0, 90.0, 10.0)


class FakeArm:
    """Remembers the servo angles it was sent, as the real agent does."""

    def __init__(self, pose=REST):
        self.pose = tuple(pose)
        self.sent = []

    def move(self, angles):
        self.pose = tuple(float(a) for a in angles)
        self.sent.append(self.pose)
        return "OK"

    def status_angles(self):
        return self.pose


def behind_settings():
    settings = copy.deepcopy(DEFAULTS)
    settings["arm"]["reach_behind"] = True
    return settings


# -- mirrored arm --------------------------------------------------------------

def test_mirror_is_its_own_inverse_and_keeps_base_and_jaws():
    pose = (70.0, 110.0, 30.0, 45.0, 0.0, 33.0)
    assert mirror(mirror(pose)) == pose
    assert mirror(pose) == (70.0, 70.0, 150.0, 135.0, 180.0, 33.0)
    assert mirror(REST) == (90.0, 135.0, 0.0, 0.0, 90.0, 10.0)


def test_mirrored_pose_is_the_forward_pose_turned_half_a_turn(workspace_cfg):
    fk = BraccioForwardKinematics(tool_workspace(workspace_cfg, copy.deepcopy(DEFAULTS)))
    for pose in ((90.0, 60.0, 40.0, 50.0, 0.0, 10.0), (130.0, 75.0, 25.0, 70.0, 0.0, 10.0)):
        front, back = fk.solve(pose), fk.solve(mirror(pose))
        assert (back.x_mm, back.y_mm) == pytest.approx((-front.x_mm, -front.y_mm), abs=1e-6)
        assert back.z_mm == pytest.approx(front.z_mm, abs=1e-6)


def test_wrapper_translates_both_ways():
    arm = FakeArm()
    wrapped = MirroredArm(arm)
    assert wrapped.status_angles() == mirror(REST)
    wrapped.move((90.0, 60.0, 40.0, 50.0, 0.0, 10.0))
    assert arm.pose == (90.0, 120.0, 140.0, 130.0, 180.0, 10.0)


def test_reach_behind_swaps_the_servo_ends_in_the_limits(workspace_cfg):
    forward = tool_workspace(workspace_cfg, copy.deepcopy(DEFAULTS))
    behind = tool_workspace(workspace_cfg, behind_settings())
    assert forward["servo_limits"]["wrist_vertical"] == {"min": 17}
    assert behind["servo_limits"]["wrist_vertical"] == {"max": 163.0}
    assert behind["servo_limits"]["elbow"] == {"max": 177.0}


def test_guard_goes_from_the_rest_pose_to_a_search_pose_behind_the_base(workspace_cfg):
    settings = behind_settings()
    tool = tool_workspace(workspace_cfg, settings)
    arm = FakeArm()
    guard = MotionGuard(tool, settings, MirroredArm(arm), dry_run=False)
    assert guard.start() == mirror(REST)
    target = guard.solve(235.0, 0.0, 80.0)          # "ahead" in the controller's frame
    assert guard.move_joints(target)
    assert arm.pose[1] > 90.0                        # leaning over the shoulder
    tip = BraccioForwardKinematics(tool).solve(arm.pose)
    assert (tip.x_mm, tip.y_mm, tip.z_mm) == pytest.approx((-235.0, 0.0, 80.0), abs=0.6)
    # Every step sent stayed inside the firmware's limits.
    for step in arm.sent:
        assert 15 <= step[1] <= 165 and all(0 <= a <= 180 for a in step[:5])
    # Without the swapped limits the same start is refused: the rest pose
    # reads as elbow 0 and wrist 0, below the forward minimums.
    plain = copy.deepcopy(settings)
    plain["arm"]["reach_behind"] = False
    refused = MotionGuard(tool_workspace(workspace_cfg, plain), plain, MirroredArm(FakeArm()),
                          dry_run=False)
    refused.start()
    with pytest.raises(ValueError):
        refused.move_joints(refused.solve(235.0, 0.0, 80.0))


def test_wrist_zero_shifts_the_wrist_servo(workspace_cfg):
    settings = copy.deepcopy(DEFAULTS)
    base = MotionGuard(tool_workspace(workspace_cfg, settings), settings).solve(235.0, 0.0, 80.0)
    settings["arm"]["wrist_zero_deg"] = 100.0
    moved = MotionGuard(tool_workspace(workspace_cfg, settings), settings).solve(235.0, 0.0, 80.0)
    assert moved[3] == pytest.approx(base[3] + 10.0, abs=0.11)
    assert moved[:3] == pytest.approx(base[:3], abs=0.11)


# -- service --------------------------------------------------------------------

class EmptyDesk(DetectionSource):
    """A camera that sees nothing, on a clock of its own so the test is quick."""

    def __init__(self, *args, **kwargs):
        self.clock = 0.0

    def open(self):
        return self

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.clock += max(0.0, seconds)

    def read(self, timeout_s):
        self.clock += 0.05
        return parse_det_line("DET n=0 ms=40", self.clock)


@pytest.fixture
def agent(workspace_cfg):
    with SimArmAgent(tool_workspace(workspace_cfg, copy.deepcopy(DEFAULTS))) as running:
        running.simulator.apply_move(REST)          # as the firmware does at power-on
        yield running


def wait_until(predicate, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_waits_and_refuses_start_without_a_camera(agent, tmp_path):
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(tmp_path / "ttyMissing"))
    service.refresh()
    snap = service.snapshot()
    assert snap["state"] == "waiting" and "camera" in snap["message"]
    assert snap["service"]["can_start"] is False
    assert service.start()["ok"] is False
    assert agent.simulator.status_line()                 # nothing was sent to the arm


def test_waits_when_the_arm_agent_is_down(tmp_path):
    port = tmp_path / "ttyCam"
    port.write_text("")
    service = svc.PickPlaceService("127.0.0.1", 1, camera_port=str(port))
    service.refresh()
    assert service.state == "waiting"
    assert any("arm agent" in p for p in service.problems)


def test_ready_then_a_dry_run_session_then_done(agent, tmp_path, monkeypatch):
    port = tmp_path / "ttyCam"
    port.write_text("")
    monkeypatch.setattr(svc, "SerialDetectionSource", EmptyDesk)
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(port))
    service.refresh()
    assert service.state == "ready" and service.snapshot()["service"]["can_start"]
    assert service.start()["ok"]
    assert service.start() == {"ok": False, "error": "already running"}
    assert wait_until(lambda: not service.busy())
    assert service.state == "done"
    assert service.last_summary["dry_run"] is True and service.last_summary["moves_sent"] == 0
    service.refresh()
    assert service.state == "done" and service.snapshot()["service"]["can_start"]


def test_autostart_runs_once(agent, tmp_path, monkeypatch):
    port = tmp_path / "ttyCam"
    port.write_text("")
    monkeypatch.setattr(svc, "SerialDetectionSource", EmptyDesk)
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(port), autostart=True)
    service.refresh()
    assert wait_until(lambda: service.sessions == 1 and not service.busy())
    service.refresh()
    service.refresh()
    assert service.sessions == 1


def test_not_parked_blocks_start_and_park_brings_it_back(agent, tmp_path):
    port = tmp_path / "ttyCam"
    port.write_text("")
    agent.simulator.apply_move((90.0, 60.0, 40.0, 50.0, 0.0, 10.0))
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(port))
    service.refresh()
    assert service.state == "waiting" and any("Park" in p for p in service.problems)
    assert service.park()["ok"]
    assert wait_until(lambda: not service.busy(), 60.0)
    service.refresh()
    assert service.state == "ready", service.history


def test_http_page_state_and_actions(agent, tmp_path):
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(tmp_path / "none"))
    server = svc.serve(service, 0, "127.0.0.1")
    root = "http://127.0.0.1:%d" % server.server_port
    try:
        service.refresh()
        page = urllib.request.urlopen(root + "/").read().decode("utf-8")
        assert 'id="start"' in page and 'id="park"' in page and "kiosk" in page
        state = json.load(urllib.request.urlopen(root + "/api/pickplace/state"))
        assert state["state"] == "waiting" and state["service"]["live"] is False
        request = urllib.request.Request(root + "/api/pickplace/start", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)
        assert refused.value.code == 409
        cross = urllib.request.Request(root + "/api/pickplace/stop", data=b"{}", method="POST",
                                       headers={"Origin": "http://elsewhere.example"})
        with pytest.raises(urllib.error.HTTPError) as blocked:
            urllib.request.urlopen(cross)
        assert blocked.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_live_needs_the_explicit_flag(capsys):
    assert svc.main(["--live", "--http-port", "0"]) == 2
    assert "calibrated" in capsys.readouterr().err


def test_a_slow_check_does_not_overwrite_a_running_session(agent, tmp_path, monkeypatch):
    port = tmp_path / "ttyCam"
    port.write_text("")
    monkeypatch.setattr(svc, "SerialDetectionSource", EmptyDesk)
    service = svc.PickPlaceService(agent.host, agent.port, camera_port=str(port))
    service.refresh()
    real_check = service.check

    def check_then_start():
        problems = real_check()
        if service.sessions == 0:
            service.check = real_check
            assert service.start()["ok"]            # Start lands while the check is in flight
        return problems

    service.check = check_then_start
    service.refresh()
    assert service.sessions == 1
    assert service.snapshot()["state"] not in ("ready", "waiting")
    assert service.snapshot()["service"]["state"] in ("running", "done")
    assert wait_until(lambda: not service.busy())
