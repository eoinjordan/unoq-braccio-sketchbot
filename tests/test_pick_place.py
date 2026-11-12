"""Colour pick and place, closed-loop on the software arm.

Nothing here touches hardware. The simulated camera (sketch_artist.sim_camera)
looks at bricks and a bin from the gripper-top camera pose and emits the
detector's text lines; the controller reads them and drives the software arm.
"""

from __future__ import annotations

import copy
import json
import math
import random
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from sketch_artist import config as cfg
from sketch_artist import pick_place_cli
from sketch_artist.arm_client import ArmClient
from sketch_artist.detections import BIN_LABEL
from sketch_artist.gripper_camera import GripperCamera, field_of_view
from sketch_artist.pick_place import (DEFAULTS, MotionGuard, MotionRefused,
                                      PickPlaceController, jaw_angle, jaw_width,
                                      load_settings, tool_workspace,
                                      validate_settings)
from sketch_artist.sim import SimArmAgent
from sketch_artist.sim_camera import (CameraNoise, PickPlaceWorld, SimBin,
                                      SimBrick, SimCameraSource, random_layout,
                                      run_trial, run_trials)

REPO = Path(__file__).resolve().parent.parent
NEW_FILES = ["sketch_artist/detections.py", "sketch_artist/gripper_camera.py",
             "sketch_artist/pick_place.py", "sketch_artist/pick_place_cli.py",
             "sketch_artist/sim_camera.py", "config/pick_place.yaml",
             "web/static/pickplace.html", "docs/pick-place.md",
             "tests/test_pick_place.py", "tests/test_detections.py"]


@pytest.fixture
def settings():
    return copy.deepcopy(DEFAULTS)


def polar(radius, bearing_deg):
    angle = math.radians(bearing_deg)
    return radius * math.cos(angle), radius * math.sin(angle)


def make_world(workspace_cfg, settings, bricks=None, parts_bin=None, noise=None,
               **kwargs):
    if bricks is None:
        bricks = [SimBrick("red", *polar(280, -25), 30.0),
                  SimBrick("yellow", *polar(295, 10), 100.0)]
    if parts_bin is None:
        parts_bin = SimBin(*polar(265, 50), 20.0)
    settings["bin"]["fallback_xy_mm"] = [parts_bin.x, parts_bin.y]
    return PickPlaceWorld(workspace_cfg, settings, bricks, parts_bin,
                          noise or CameraNoise.none(), **kwargs)


# ------------------------------------------------------------- settings

def test_documented_config_matches_the_defaults():
    documented = cfg.load_yaml("pick_place.yaml")
    assert documented == DEFAULTS
    assert load_settings() == DEFAULTS


def test_runtime_overrides_and_validation(tmp_path):
    (tmp_path / "runtime.yaml").write_text(
        "pick_place:\n  colours: [white]\n  bin: {rim_height_mm: 55}\n",
        encoding="ascii")
    loaded = load_settings(tmp_path, {"confidence": 0.7})
    assert loaded["colours"] == ["white"]
    assert loaded["bin"]["rim_height_mm"] == 55
    assert loaded["bin"]["remember"] is True
    assert loaded["confidence"] == 0.7


@pytest.mark.parametrize("change, message", [
    ({"colours": ["green"]}, "colours"),
    ({"colours": []}, "colours"),
    ({"confidence": 0}, "confidence"),
    ({"watchdog_s": 30}, "watchdog"),
    ({"tool": {"pitch_deg": 10}}, "pitch"),
    ({"desk": {"margin_mm": 0}}, "margin"),
    ({"gripper": {"close_width_mm": 50}}, "open_width"),
    ({"speed": {"max_step_deg": 20}}, "max_step_deg"),
    ({"search": {"base_min_deg": 170}}, "base range"),
    ({"surprise": 1}, "Unknown"),
    ({"bin": {"colour": "blue"}}, "Unknown bin"),
])
def test_bad_settings_are_refused(settings, change, message):
    with pytest.raises(ValueError, match=message):
        validate_settings(cfg.merge_config(settings, change))


def test_jaw_width_maps_to_servo_angle(settings):
    points = settings["gripper"]["jaw_calibration"]
    assert jaw_angle(60, points) == pytest.approx(10)
    assert jaw_angle(0, points) == pytest.approx(73)
    assert 10 < jaw_angle(45, points) < jaw_angle(13, points) < 73
    assert jaw_width(jaw_angle(13, points), points) == pytest.approx(13)


# --------------------------------------------------------- camera model

@pytest.fixture
def camera(workspace_cfg, settings):
    return GripperCamera(tool_workspace(workspace_cfg, settings),
                         settings["tool"], settings["camera"])


def search_angles(workspace_cfg, settings, base=90.0, radius=235.0, z=80.0):
    guard = MotionGuard(tool_workspace(workspace_cfg, settings), settings)
    angle = math.radians(base - 90.0)
    return guard.solve(radius * math.cos(angle), radius * math.sin(angle), z)


def test_field_of_view_is_66_degrees_on_the_diagonal():
    half_w, half_h = field_of_view(66.0, (4, 3))
    assert math.degrees(2 * math.atan(math.hypot(half_w, half_h))) == pytest.approx(66.0)
    assert half_w / half_h == pytest.approx(4 / 3)


def test_optical_axis_meets_the_centre_line_at_the_pick_distance(
        camera, workspace_cfg, settings):
    """The default XIAO holder is aimed 120 mm in front of the finger mount:
    tilt 14.6 degrees, lens 23.7 mm up and 29.0 mm forward."""
    angles = search_angles(workspace_cfg, settings)
    pose = camera.pose(angles)
    ahead = 120.0 - settings["tool"]["grasp_from_mount_mm"]
    point = tuple(g + ahead * t for g, t in zip(pose.grasp, pose.tool))
    x, y = camera.project(point, angles)
    assert x == pytest.approx(0.5, abs=1e-6)
    assert y == pytest.approx(0.5, abs=0.004)
    # Nearer than that the centre line is below the middle of the picture.
    near = tuple(g + 5.0 * t for g, t in zip(pose.grasp, pose.tool))
    assert camera.project(near, angles)[1] > 0.6


def test_camera_sits_on_the_outer_face_and_looks_down(camera, workspace_cfg, settings):
    angles = search_angles(workspace_cfg, settings)
    pose = camera.pose(angles)
    assert pose.tool[2] == pytest.approx(math.sin(math.radians(-60)), abs=0.01)
    assert math.hypot(pose.lens[0], pose.lens[1]) > math.hypot(*pose.grasp[:2]) - 20
    assert pose.lens[2] > pose.grasp[2] + 30
    elevation = math.degrees(math.asin(pose.forward[2]))
    assert elevation == pytest.approx(-74.6, abs=0.3)      # -60 less the tilt
    assert abs(pose.jaw[2]) < 1e-6                         # claws close sideways


def test_project_and_ray_to_plane_agree(camera, workspace_cfg, settings):
    angles = search_angles(workspace_cfg, settings, base=70.0)
    for point in ((250.0, -60.0, 8.0), (300.0, -110.0, 8.0), (250.0, -95.0, 40.0)):
        image = camera.project(point, angles)
        assert camera.in_picture(image)
        x, y = camera.ray_to_plane(image[0], image[1], angles, point[2])
        assert (x, y) == pytest.approx(point[:2], abs=1e-6)


def test_picture_directions(camera, workspace_cfg, settings):
    """Facing outwards from the base: further out is up the picture, the
    arm's right is the right of the picture."""
    angles = search_angles(workspace_cfg, settings)
    middle = camera.project((280.0, 0.0, 0.0), angles)
    assert camera.project((300.0, 0.0, 0.0), angles)[1] < middle[1]
    assert camera.project((280.0, -20.0, 0.0), angles)[0] > middle[0]


def test_mirror_rotation_and_wrist_roll(workspace_cfg, settings):
    angles = search_angles(workspace_cfg, settings)
    point = (300.0, -20.0, 0.0)
    plain = GripperCamera(tool_workspace(workspace_cfg, settings), settings["tool"],
                          settings["camera"]).project(point, angles)
    for change in ({"mirror": True}, {"image_rotation_deg": 180.0}):
        other = GripperCamera(
            tool_workspace(workspace_cfg, settings), settings["tool"],
            {**settings["camera"], **change})
        image = other.project(point, angles)
        assert image[0] == pytest.approx(1.0 - plain[0])
        expected_y = plain[1] if "mirror" in change else 1.0 - plain[1]
        assert image[1] == pytest.approx(expected_y)
        assert other.ray_to_plane(image[0], image[1], angles, 0.0) == \
            pytest.approx(point[:2], abs=1e-6)
    camera = GripperCamera(tool_workspace(workspace_cfg, settings),
                           settings["tool"], settings["camera"])
    rolled = angles[:4] + (90.0,) + angles[5:]
    side = camera.pose(rolled)
    assert abs(side.lens[1] - side.grasp[1]) > 20      # now beside the gripper
    assert camera.pose(angles).lens[1] == pytest.approx(camera.pose(angles).grasp[1])


def test_aim_point_moves_down_the_picture_as_the_gripper_descends(
        camera, workspace_cfg, settings):
    high = camera.aim_point(search_angles(workspace_cfg, settings, radius=235, z=80), 8.0)
    low = camera.aim_point(search_angles(workspace_cfg, settings, radius=260, z=35), 8.0)
    assert high[2] > low[2] > 0
    assert camera.in_picture(high[0]) and camera.in_picture(low[0])
    assert low[0][1] > high[0][1]


# --------------------------------------------------------- motion guard

class RecordingArm:
    def __init__(self, pose=(90, 45, 180, 180, 90, 10), reply="OK"):
        self.pose = tuple(float(v) for v in pose)
        self.moves = []
        self.reply = reply

    def move(self, angles):
        self.moves.append(tuple(angles))
        self.pose = tuple(angles)
        return self.reply

    def status_angles(self):
        return self.pose


@pytest.fixture
def guard(workspace_cfg, settings):
    arm = RecordingArm()
    guard = MotionGuard(tool_workspace(workspace_cfg, settings), settings, arm,
                        dry_run=False)
    guard.start()
    return guard


def test_guard_steps_are_bounded_and_planned_first(guard):
    target = guard.solve(235.0, 0.0, 80.0)
    assert guard.move_joints(target)
    moves = guard.arm.moves
    assert moves[-1] == pytest.approx(target, abs=0.01)
    previous = (90, 45, 180, 180, 90, 10)
    for move in moves:
        assert max(abs(a - b) for a, b in zip(move, previous)) <= 2.0 + 1e-6
        previous = move


def test_guard_refuses_to_go_below_the_desk_margin(guard):
    guard.move_joints(guard.solve(250.0, 0.0, 40.0))
    sent = len(guard.arm.moves)
    with pytest.raises(MotionRefused, match="floor"):
        guard.solve(280.0, 0.0, 4.0)        # claw tips under the 3 mm margin
    low = guard.solve(280.0, 0.0, 8.0)      # the grasp height itself is allowed
    assert guard.lowest_mm(low) >= 3.0
    # A target that is fine but whose path dips is refused before any step.
    guard.floor = 60.0
    with pytest.raises(MotionRefused):
        guard.move_joints(low)
    assert len(guard.arm.moves) == sent


def test_guard_refuses_unreachable_and_out_of_limit_poses(guard):
    with pytest.raises(MotionRefused, match="out of reach|needs"):
        guard.solve(420.0, 0.0, 80.0)
    with pytest.raises(MotionRefused, match="needs|outside"):
        guard.solve(120.0, 0.0, 80.0)
    with pytest.raises(MotionRefused, match="gripper"):
        guard.move_joints(guard.pose[:5] + (150.0,))
    with pytest.raises(MotionRefused, match="shoulder"):
        guard.move_joints((90, 5, 180, 180, 90, 10))
    assert guard.arm.moves == []


def test_guard_respects_the_workspace_step_ceiling_and_slow(workspace_cfg, settings):
    tool = tool_workspace(workspace_cfg, settings)
    settings["speed"]["max_step_deg"] = 5.0
    assert MotionGuard(tool, settings).max_step == 2.5      # motion.max_step_deg
    settings["speed"]["max_step_deg"] = 2.0
    slow = MotionGuard(tool, settings, slow=True)
    assert slow.max_step == pytest.approx(0.8)
    assert slow.interval == pytest.approx(0.125)


def test_dry_run_sends_nothing(workspace_cfg, settings):
    arm = RecordingArm()
    guard = MotionGuard(tool_workspace(workspace_cfg, settings), settings, arm,
                        dry_run=True)
    guard.start()
    guard.move_joints(guard.solve(235.0, 0.0, 80.0))
    assert arm.moves == [] and guard.steps_sent == 0 and guard.steps_planned > 10
    assert guard.grasp_point() == pytest.approx((235.0, 0.0, 80.0), abs=0.6)


# ---------------------------------------------------------- closed loop

def run(workspace_cfg, settings, world, **source_options):
    source = SimCameraSource(world, **source_options)
    controller = PickPlaceController(workspace_cfg, settings, source, arm=world,
                                     dry_run=False)
    return controller, controller.run()


def test_whole_loop_clears_the_desk(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    controller, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done"
    assert summary["picked"] == summary["placed"] == 2
    assert world.counts() == {"desk": 0, "held": 0, "bin": 2}
    assert world.events == ["held red", "binned red", "held yellow", "binned yellow"]
    assert summary["failures"] == {}
    # Never below the desk margin, and back at the search pose with the
    # claws open.
    assert world.lowest_mm >= settings["desk"]["margin_mm"] - 0.05
    assert controller.guard.grasp_point() == pytest.approx((0.0, 235.0, 80.0), abs=0.6) \
        or controller.guard.grasp_point() == pytest.approx((235.0, 0.0, 80.0), abs=0.6)
    assert controller.guard.jaw == pytest.approx(controller.jaw_open, abs=0.1)
    states = " ".join(controller.history)
    for state in ("[search]", "[approach]", "[grasp]", "[lift]", "[verify]",
                  "[bin-search]", "[bin-approach]", "[place]", "[done]"):
        assert state in states


def test_loop_over_the_arm_protocol(workspace_cfg, settings):
    """The same loop through ArmClient and the M/S protocol, as on the UNO Q."""
    agent = SimArmAgent(tool_workspace(workspace_cfg, settings)).start()
    try:
        world = make_world(workspace_cfg, settings,
                           bricks=[SimBrick("white", *polar(285, 0), 60.0)],
                           simulator=agent.simulator)
        with ArmClient(agent.host, agent.port) as arm:
            controller = PickPlaceController(workspace_cfg, settings,
                                             SimCameraSource(world), arm=arm,
                                             dry_run=False)
            summary = controller.run()
    finally:
        agent.stop()
    assert summary["state"] == "done" and world.counts()["bin"] == 1
    assert summary["moves_sent"] > 100


def test_colours_and_strict_order(workspace_cfg, settings):
    bricks = [SimBrick("white", *polar(280, -40)), SimBrick("yellow", *polar(290, -10)),
              SimBrick("red", *polar(285, 20))]
    settings["colours"] = ["yellow", "red"]
    settings["strict_order"] = True
    world = make_world(workspace_cfg, settings, bricks, SimBin(*polar(265, 55)))
    _, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done"
    assert [e for e in world.events if e.startswith("held")] == ["held yellow", "held red"]
    assert bricks[0].state == "desk"            # white was not asked for


def test_low_confidence_detections_are_ignored(workspace_cfg, settings):
    noise = CameraNoise.none()
    noise.confidence = (0.5, 0.0)
    world = make_world(workspace_cfg, settings, noise=noise)
    _, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done" and summary["picked"] == 0
    assert world.counts()["desk"] == 2


def test_failed_grasp_is_noticed_and_retried(workspace_cfg, settings):
    noise = CameraNoise.none()
    noise.slip = 1.0                           # the claws never hold
    world = make_world(workspace_cfg, settings,
                       bricks=[SimBrick("red", *polar(280, 0))], noise=noise)
    _, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done"
    assert summary["failures"] == {"grasp_failed": settings["max_attempts"]}
    assert summary["placed"] == 0 and world.counts()["desk"] == 1
    assert len([e for e in world.events if e.startswith("missed")]) == 3


def test_fixed_bin_position_is_used_when_the_bin_is_not_seen(workspace_cfg, settings):
    class BlindToBin(PickPlaceWorld):
        def render(self, angles):
            return [d for d in super().render(angles) if d.label != BIN_LABEL]

    settings["bin"]["search_timeout_s"] = 4.0
    parts_bin = SimBin(*polar(265, 50), 20.0)
    settings["bin"]["fallback_xy_mm"] = [parts_bin.x, parts_bin.y]
    world = BlindToBin(workspace_cfg, settings, [SimBrick("red", *polar(280, 0))],
                       parts_bin, CameraNoise.none())
    _, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done"
    assert summary["failures"] == {"bin_not_seen": 1}
    assert world.counts()["bin"] == 1


def test_bricks_out_of_reach_are_left_alone(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings,
                       bricks=[SimBrick("red", *polar(232, 0))])
    _, summary = run(workspace_cfg, settings, world)
    assert summary["state"] == "done" and summary["placed"] == 0
    assert set(summary["failures"]) <= {"unreachable", "approach_lost"}
    assert world.counts()["desk"] == 1


def test_watchdog_halts_when_detections_stop(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    controller, summary = run(workspace_cfg, settings, world, stall_after=60)
    assert summary["state"] == "fault"
    assert "Watchdog" in summary["message"]
    moves = world.simulator.move_count
    assert controller.frames_read == 60
    # Nothing more is sent after the fault, and the run does not resume.
    assert controller.run()["state"] == "fault"
    assert world.simulator.move_count == moves


def test_stop_halts_and_keeps_the_claws_as_they_are(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    source = SimCameraSource(world)
    controller = PickPlaceController(workspace_cfg, settings, source, arm=world,
                                     dry_run=False)
    read = source.read

    def read_then_stop(timeout_s):
        if "held red" in world.events:
            controller.stop()
        return read(timeout_s)

    source.read = read_then_stop
    summary = controller.run()
    assert summary["state"] == "stopped"
    assert world.held is not None               # the brick is not dropped
    moves = world.simulator.move_count
    assert controller.snapshot()["stop_requested"] is True
    assert world.simulator.move_count == moves


def test_arm_that_rejects_a_move_is_a_fault(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    arm = RecordingArm(reply="ERR bad move")
    controller = PickPlaceController(workspace_cfg, settings,
                                     SimCameraSource(world), arm=arm, dry_run=False)
    summary = controller.run()
    assert summary["state"] == "fault" and len(arm.moves) == 1


def test_dry_run_plans_the_search_without_moving_the_arm(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    arm = RecordingArm()
    settings["max_attempts"] = 1
    settings["approach"]["timeout_s"] = 3.0
    controller = PickPlaceController(workspace_cfg, settings,
                                     SimCameraSource(world), arm=arm, dry_run=True)
    notes = controller.check_plan()
    assert any("dry-run" in note for note in notes)
    summary = controller.run()
    assert arm.moves == [] and summary["moves_sent"] == 0
    assert summary["moves_planned"] > 50 and summary["dry_run"] is True
    assert world.simulator.move_count == 1      # only the world's own start pose


def test_unsafe_configuration_is_refused_before_moving(workspace_cfg, settings):
    settings["brick"]["grasp_height_mm"] = 4.0
    world = make_world(workspace_cfg, settings)
    controller = PickPlaceController(workspace_cfg, settings,
                                     SimCameraSource(world), arm=world, dry_run=False)
    with pytest.raises(ValueError, match="claw tips"):
        controller.check_plan()
    assert controller.run()["state"] == "fault"
    assert world.simulator.move_count == 1


def test_noise_free_random_layouts_all_clear(workspace_cfg):
    report = run_trials(6, seed=7, workspace=workspace_cfg,
                        noise=CameraNoise.none(), calibration_error=0.0)
    assert report["success_rate"] == 1.0
    assert report["lowest_mm"] >= DEFAULTS["desk"]["margin_mm"] - 0.05


def test_noisy_random_layouts_mostly_clear(workspace_cfg):
    """Detection noise, dropped and lost frames, a frame of lag and a rig
    that is slightly off its configuration. Simulated, not measured."""
    report = run_trials(16, seed=100, workspace=workspace_cfg,
                        calibration_error=0.5)
    assert report["brick_rate"] >= 0.85
    assert report["success_rate"] >= 0.75
    for result in report["results"]:
        assert result.state == "done"


def test_trials_are_repeatable(workspace_cfg):
    first = run_trial(42, workspace=workspace_cfg)
    second = run_trial(42, workspace=workspace_cfg)
    assert (first.binned, first.elapsed_s, first.world_events) == \
        (second.binned, second.elapsed_s, second.world_events)


def test_random_layouts_keep_their_distances():
    bricks, parts_bin = random_layout(random.Random(3), 4)
    assert len(bricks) == 4
    for index, brick in enumerate(bricks):
        assert 262 <= math.hypot(brick.x, brick.y) <= 305
        assert math.dist((brick.x, brick.y), (parts_bin.x, parts_bin.y)) >= 95
        for other in bricks[:index]:
            assert math.dist((brick.x, brick.y), (other.x, other.y)) >= 45


# ------------------------------------------------- monitor page and CLI

def test_monitor_page_shows_state_and_stops(workspace_cfg, settings):
    world = make_world(workspace_cfg, settings)
    controller = PickPlaceController(workspace_cfg, settings,
                                     SimCameraSource(world), arm=world, dry_run=False)
    controller._next_frame()
    server = pick_place_cli.start_monitor(controller, 0)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        assert "Pick and place" in page and 'id="stop"' in page
        state = json.load(urllib.request.urlopen(base + "/api/pickplace/state", timeout=5))
        assert state["state"] == "idle" and state["frames"] == 1
        assert state["dry_run"] is False and len(state["pose"]) == 6
        foreign = urllib.request.Request(
            base + "/api/pickplace/stop", data=b"{}", method="POST",
            headers={"Origin": "http://elsewhere.example"})
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(foreign, timeout=5)
        assert refused.value.code == 403 and not controller.stop_event.is_set()
        stop = urllib.request.Request(base + "/api/pickplace/stop", data=b"{}",
                                      method="POST")
        assert json.load(urllib.request.urlopen(stop, timeout=5))["stop_requested"]
        assert controller.stop_event.is_set()
    finally:
        server.shutdown()
        server.server_close()
    assert controller.run()["state"] == "stopped"
    assert world.simulator.move_count == 1


def test_cli_refuses_live_without_the_real_camera(capsys):
    assert pick_place_cli.main(["--source", "sim", "--live"]) == 2
    assert pick_place_cli.main(["--live", "--dry-run"]) == 2
    assert pick_place_cli.main(["--colours", "green", "--source", "sim"]) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_cli_runs_the_simulation_and_reports_trials(capsys):
    assert pick_place_cli.main(["--source", "sim", "--seed", "3"]) == 0
    out = capsys.readouterr().out
    assert "No hardware is used" in out and '"simulated": true' in out
    assert pick_place_cli.main(["--trials", "2", "--seed", "5"]) == 0
    assert "SIMULATED: " in capsys.readouterr().out


def test_cli_dry_run_against_a_replayed_log(tmp_path, capsys, monkeypatch):
    log = tmp_path / "det.log"
    log.write_text("".join(f"{i * 0.05:.3f} DET n=0 ms=40\n" for i in range(4000)),
                   encoding="ascii")
    monkeypatch.setattr(pick_place_cli, "ReplayDetectionSource",
                        lambda path: __import__("sketch_artist.detections",
                                                fromlist=["x"]).ReplayDetectionSource(
                                                    path, realtime=False))
    assert pick_place_cli.main(["--replay", str(log)]) == 0
    out = capsys.readouterr().out
    assert '"moves_sent": 0' in out and "the arm was not moved" in out


# ------------------------------------------------------------ house rules

@pytest.mark.parametrize("name", NEW_FILES)
def test_new_files_are_plain_ascii(name):
    (REPO / name).read_bytes().decode("ascii")


def test_docs_say_what_is_simulated_and_how_to_start_safely():
    page = (REPO / "docs" / "pick-place.md").read_text(encoding="ascii")
    for needle in ("simulated", "dry-run", "servo power off", "--slow",
                   "power switch", "303A", "wrist_rotation_deg", "jaw_calibration",
                   "fallback_xy_mm", "not been run on a real arm"):
        assert needle in page, needle
    safety = (REPO / "docs" / "safety.md").read_text(encoding="utf-8")
    assert "pick-place.md" in safety and "watchdog" in safety.lower()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/pick-place.md" in readme
    assert "pick_place_cli" in (REPO / "site" / "parts.html").read_text(encoding="ascii")
