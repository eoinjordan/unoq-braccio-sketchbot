"""Overhead pick and place: geometry, planning, detection and frame checks."""

from __future__ import annotations

import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from sketch_artist.pickplace_overhead import detect, geometry as geo, plan, watch  # noqa: E402


ARM = geo.ArmGeometry(tool_mm=190.0)


def camera(mirrored=True):
    return geo.nominal_camera((880, 650), 1.3, 20.0, 1000.0, (960, 540), mirrored=mirrored)


def pose(x, y, z):
    """Any reachable pose with the fingertips at (x, y, z)."""
    return plan.steepest(ARM, x, y, z, 90.0, 10.0, plan.PickConfig())[0]


# -- arm ---------------------------------------------------------------------

@pytest.mark.parametrize("x,y,z,pitch", [
    (-170.0, 20.0, 8.0, -90.0),      # behind, straight down
    (-240.0, -80.0, 30.0, -70.0),    # behind, tilted out
    (170.0, 30.0, 8.0, -90.0),       # in front
])
def test_inverse_then_forward_returns_the_target(x, y, z, pitch):
    angles = ARM.solve(x, y, z, pitch)
    fx, fy, fz = ARM.point_xyz(angles, "tip")
    assert math.hypot(fx - x, fy - y) < 0.6
    assert abs(fz - z) < 0.6
    back = x < 0
    assert (angles[1] > 90.0) == back       # leans over the shoulder only when behind


def test_behind_is_the_mirror_of_in_front():
    front = ARM.solve(180.0, 0.0, 10.0)
    back = ARM.solve(-180.0, 0.0, 10.0)
    assert back[0] == pytest.approx(front[0])
    for i in (1, 2, 3):
        assert back[i] == pytest.approx(180.0 - front[i], abs=0.11)


def test_rest_pose_holds_the_tool_high_behind_the_base():
    chain = ARM.chain(geo.REST_POSE)
    assert chain["tip"][0] < 0 and chain["tip"][1] > 120.0


def test_out_of_reach_is_refused():
    with pytest.raises(geo.Unreachable):
        ARM.solve(-420.0, 0.0, 10.0)
    with pytest.raises(geo.Unreachable):
        ARM.solve(-60.0, 0.0, 10.0)


def test_interpolate_never_exceeds_the_step():
    a, b = geo.REST_POSE, (60.0, 110.0, 165.0, 170.0, 40.0, 10.0)
    steps = [a] + geo.interpolate(a, b, 2.5)
    assert steps[-1] == pytest.approx(b)
    for p, q in zip(steps, steps[1:]):
        assert max(abs(u - v) for u, v in zip(p, q)) <= 2.5 + 1e-9


# -- envelope ----------------------------------------------------------------

def test_floor_guard_and_keep_out():
    square = [(-260, -60), (-140, -60), (-140, 60), (-260, 60)]
    env = geo.Envelope(ARM, floor_clearance_mm=40.0,
                       keep_outs=[geo.KeepOut("bin", square, 105.0, 20.0)])
    low = pose(-200.0, 150.0, 10.0)
    assert "below" in env.violation(low)
    assert env.violation(low, floor_clearance_mm=9.0) is None
    in_bin = pose(-200.0, 0.0, 60.0)
    assert "keep-out" in env.violation(in_bin)
    beside = pose(-200.0, 75.0, 60.0)       # 15 mm outside, inside the margin
    assert "keep-out" in env.violation(beside)
    clear = pose(-200.0, 150.0, 60.0)
    assert env.violation(clear) is None
    above = pose(-200.0, 0.0, 115.0)
    assert env.violation(above) is None


def test_base_sector_and_front_reach_are_enforced():
    env = geo.Envelope(ARM, base_range=(30.0, 150.0), max_front_reach_mm=140.0)
    assert "sector" in env.violation((10.0,) + geo.REST_POSE[1:])
    assert env.violation(geo.REST_POSE) is None
    forward = pose(200.0, 0.0, 80.0)
    assert "in front" in env.violation(forward)


def test_path_check_catches_a_dip_between_two_safe_poses():
    env = geo.Envelope(ARM, floor_clearance_mm=40.0)
    a = pose(-170.0, 0.0, 45.0)
    b = (a[0], a[1] + 14.0, a[2], a[3], a[4], a[5])     # shoulder leans further back
    assert env.violation(a) is None
    assert env.check_path(a, b) is not None


# -- camera ------------------------------------------------------------------

def test_camera_fit_recovers_projection_and_back_projection():
    P = camera()
    rng = np.random.default_rng(1)
    pts = [(rng.uniform(-300, -120), rng.uniform(-200, 200), rng.uniform(100, 260)) for _ in range(40)]
    pix = [geo.project(P, p) for p in pts]
    fit = geo.fit_camera(pts, pix)
    assert geo.reprojection_errors(fit, pts, pix).max() < 1e-6
    x, y = geo.back_project(fit, geo.project(P, (-210.0, 55.0, 19.0)), 19.0)
    assert (x, y) == pytest.approx((-210.0, 55.0), abs=1e-4)
    assert geo.camera_centre(fit)[2] == pytest.approx(1000.0, rel=1e-6)


def test_camera_fit_tolerates_pixel_noise():
    P = camera()
    rng = np.random.default_rng(2)
    pts = [(rng.uniform(-320, -120), rng.uniform(-220, 220), rng.uniform(100, 280)) for _ in range(60)]
    pix = [np.array(geo.project(P, p)) + rng.normal(0, 1.5, 2) for p in pts]
    fit = geo.fit_camera(pts, pix)
    x, y = geo.back_project(fit, geo.project(P, (-200.0, 40.0, 19.0)), 19.0)
    assert math.hypot(x + 200.0, y - 40.0) < 12.0


def test_camera_fit_refuses_coplanar_points():
    P = camera()
    pts = [(x, y, 150.0) for x in (-300, -250, -200, -150) for y in (-100, 0, 100)]
    with pytest.raises(ValueError):
        geo.fit_camera(pts, [geo.project(P, p) for p in pts])


def test_nominal_camera_puts_the_base_where_it_was_seen():
    for mirrored in (True, False):
        P = camera(mirrored)
        assert geo.project(P, (0, 0, 0)) == pytest.approx((880, 650), abs=1e-6)
        u, v = geo.project(P, (100, 0, 0))
        assert math.degrees(math.atan2(-(v - 650), u - 880)) == pytest.approx(20.0, abs=1e-6)
        assert geo.mm_per_pixel(P, (700, 500), 0.0) == pytest.approx(1 / 1.3, rel=1e-6)
    assert geo.mm_per_pixel(camera(), (700, 500), 200.0) < 1 / 1.3     # nearer the lens


def test_tool_length_from_a_level_arm():
    assert geo.tool_length_from_image((100, 100), (300, 100), (604, 100)) == pytest.approx(190.0)


# -- detection ----------------------------------------------------------------

FLOOR = (118, 160, 205)      # BGR, warm wood
COLOURS = {detect.YELLOW: (60, 190, 245), detect.RED: (60, 50, 215),
           detect.WHITE: (238, 238, 236), detect.BIN: (215, 120, 20)}


def scene():
    img = np.full((600, 800, 3), FLOOR, np.uint8)
    rng = np.random.default_rng(0)
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)

    def brick(cx, cy, w, h, ang, colour):
        box = cv2.boxPoints(((cx, cy), (w, h), ang)).astype(np.int32)
        cv2.fillPoly(img, [box], colour)

    brick(200, 150, 84, 42, 20, COLOURS[detect.YELLOW])
    brick(400, 200, 84, 42, -35, COLOURS[detect.RED])
    brick(300, 380, 42, 42, 0, COLOURS[detect.WHITE])
    brick(620, 430, 240, 160, 10, COLOURS[detect.BIN])
    cv2.line(img, (0, 560), (800, 500), (30, 30, 30), 6)               # a cable
    cv2.circle(img, (650, 120), 70, (40, 110, 240), -1)                # orange arm base
    return img


def test_colour_detector_finds_each_brick_and_the_bin():
    dets = detect.ColourDetector().detect(scene())
    by_label = {}
    for d in dets:
        by_label.setdefault(d.label, []).append(d)
    assert {k: len(v) for k, v in by_label.items()} == {
        detect.YELLOW: 1, detect.RED: 1, detect.WHITE: 1, detect.BIN: 1}
    y = by_label[detect.YELLOW][0]
    assert (y.x_px, y.y_px) == pytest.approx((200, 150), abs=2.5)
    assert y.length_px == pytest.approx(84, abs=5) and y.width_px == pytest.approx(42, abs=5)
    assert y.angle_deg == pytest.approx(-20.0, abs=4.0)     # drawn clockwise on screen
    label, x_px, y_px, confidence = y[:4]                   # the plain interface
    assert label == detect.YELLOW and 0.0 < confidence <= 1.0


def test_ignore_regions_and_roi_drop_detections():
    cfg = detect.ColourDetectorConfig(roi=(0, 0, 500, 300), ignore_circles=[(400, 200, 60)])
    labels = [d.label for d in detect.ColourDetector(cfg).detect(scene())]
    assert labels == [detect.YELLOW]


def test_annotate_keeps_the_frame_size():
    img = scene()
    dets = detect.ColourDetector().detect(img)
    assert detect.annotate(img, dets).shape == img.shape


# -- planning ----------------------------------------------------------------

def det_at(P, label, x, y, z, length_mm=64.0, width_mm=32.0, angle=0.0):
    u, v = geo.project(P, (x, y, z))
    s = 1.0 / geo.mm_per_pixel(P, (u, v), z)
    return detect.Detection(label, u, v, 0.9, angle, length_mm * s, width_mm * s,
                            length_mm * width_mm * s * s)


def test_plan_reaches_near_bricks_and_reports_the_rest():
    P = camera()
    cfg = plan.PickConfig(bin_rim_mm=80.0)
    dets = [
        det_at(P, detect.YELLOW, -180.0, 90.0, 19.0),
        det_at(P, detect.RED, -420.0, 60.0, 19.0),                    # too far
        det_at(P, detect.WHITE, -200.0, 160.0, 19.0, 64.0, 60.0),     # too wide for the jaws
        det_at(P, detect.BIN, -190.0, -90.0, 80.0, 180.0, 110.0),
    ]
    plans, env = plan.plan_all(dets, P, ARM, cfg)
    result = {p.detection.label: p for p in plans}
    assert result[detect.YELLOW].reachable
    assert not result[detect.RED].reachable and "reach" in result[detect.RED].reason
    assert not result[detect.WHITE].reachable and "wider" in result[detect.WHITE].reason
    assert [k.name for k in env.keep_outs] == ["bin"]
    text = plan.describe(plans)
    assert "reachable" in text and "SKIP" in text

    wps = result[detect.YELLOW].waypoints
    assert wps[0].label == "turn to brick" and wps[-1].label == "park"
    assert wps[-1].angles[:5] == geo.REST_POSE[:5]
    lowest = min(ARM.chain(w.angles)["tip"][1] for w in wps)
    assert lowest == pytest.approx(cfg.grasp_z_mm, abs=0.6)
    # The fingertips stay over the brick all the way down.
    for w in wps:
        if w.label.startswith("descend"):
            x, y, _ = ARM.point_xyz(w.angles, "tip")
            assert math.hypot(x + 180.0, y - 90.0) < 1.0
    # Jaws close only at the bottom and open only over the bin, above the rim.
    closed = [w for w in wps if w.angles[5] == cfg.jaws_closed]
    assert closed[0].label == "close jaws"
    release = next(w for w in wps if w.label == "open jaws")
    assert ARM.chain(release.angles)["tip"][1] >= cfg.bin_rim_mm + cfg.bin_margin_mm
    # Every leg was checked against the envelope.
    previous = geo.REST_POSE[:5] + (cfg.jaws_open,)
    for w in wps:
        assert env.check_path(previous, w.angles, w.floor_guard_mm) is None
        previous = w.angles


def test_a_brick_beside_the_bin_wall_is_not_attempted():
    P = camera()
    cfg = plan.PickConfig(bin_rim_mm=80.0)
    dets = [det_at(P, detect.YELLOW, -190.0, -20.0, 19.0),            # 15 mm from the bin wall
            det_at(P, detect.BIN, -190.0, -90.0, 80.0, 180.0, 110.0)]
    plans, _ = plan.plan_all(dets, P, ARM, cfg)
    assert not plans[0].reachable and "keep-out" in plans[0].reason


def test_no_bin_means_nothing_is_attempted():
    P = camera()
    plans, _ = plan.plan_all([det_at(P, detect.YELLOW, -180.0, 90.0, 19.0)], P, ARM, plan.PickConfig())
    assert not plans[0].reachable and "bin" in plans[0].reason


def test_wrist_roll_puts_the_jaws_across_the_brick():
    cfg = plan.PickConfig(jaw_line_offset_deg=90.0, jaw_roll_sign=1.0)
    # Brick lying along the reach direction: the jaw line must be across it,
    # which is where it already is at roll 90.
    assert plan.wrist_roll_for(180.0, 180.0, cfg) == pytest.approx(90.0)
    assert plan.wrist_roll_for(200.0, 180.0, cfg) == pytest.approx(110.0)
    assert plan.wrist_roll_for(20.0, 180.0, cfg) == pytest.approx(110.0)    # axis has no direction
    cfg.jaw_roll_sign = -1.0
    assert plan.wrist_roll_for(200.0, 180.0, cfg) == pytest.approx(70.0)


# -- frame checks --------------------------------------------------------------

def sheet_scene(dx=0, angle=0.0):
    img = np.full((500, 500, 3), FLOOR, np.uint8)
    box = cv2.boxPoints(((250 + dx, 250), (200, 200), angle)).astype(np.int32)
    cv2.fillPoly(img, [box], (232, 232, 228))
    cv2.circle(img, (250 + dx, 250), 60, (40, 110, 240), -1)
    return img


def test_base_shift_detects_a_slide_and_a_turn_but_not_noise():
    ref = sheet_scene()
    rng = np.random.default_rng(3)
    noisy = np.clip(ref + rng.normal(0, 3, ref.shape), 0, 255).astype(np.uint8)
    assert not watch.base_shift(ref, noisy, (250, 250), 180).moved
    assert watch.base_shift(ref, sheet_scene(dx=25), (250, 250), 180).moved
    assert watch.base_shift(ref, sheet_scene(angle=25.0), (250, 250), 180).moved


def test_base_shift_ignores_the_part_under_the_arm():
    ref = sheet_scene()
    cur = ref.copy()
    cv2.rectangle(cur, (140, 200), (260, 300), (40, 110, 240), -1)      # arm over the sheet
    assert watch.base_shift(ref, cur, (250, 250), 180).moved
    exclude = np.zeros(ref.shape[:2], np.uint8)
    cv2.rectangle(exclude, (130, 190), (270, 310), 255, -1)
    assert not watch.base_shift(ref, cur, (250, 250), 180, exclude=exclude).moved


def test_unexplained_change_flags_an_intruder_outside_the_arm():
    ref = np.full((400, 400, 3), FLOOR, np.uint8)
    cur = ref.copy()
    cv2.rectangle(cur, (40, 40), (120, 140), (110, 70, 40), -1)         # a dark blue sleeve
    cv2.rectangle(cur, (250, 250), (330, 330), (40, 110, 240), -1)      # the arm
    zone = watch.disc_mask(ref.shape, (200, 200), 260)
    arm = np.zeros(ref.shape[:2], np.uint8)
    cv2.rectangle(arm, (230, 230), (350, 350), 255, -1)
    found = watch.unexplained_changes(ref, cur, zone, arm)
    assert len(found) == 1 and abs(found[0].x_px - 80) < 5
    assert watch.unexplained_changes(ref, ref, zone, arm) == []
    spots = watch.spots_mask(ref.shape, [(80, 90, 80)])
    assert watch.unexplained_changes(ref, cur, zone, arm | spots) == []


def test_arm_mask_covers_the_projected_links():
    P = camera()
    angles = pose(-200.0, 60.0, 60.0)
    mask = watch.arm_mask((1080, 1920), P, ARM, angles)
    for name in ("elbow", "wrist", "tip"):
        u, v = geo.project(P, ARM.point_xyz(angles, name))
        assert mask[int(v), int(u)] == 255
    assert mask[100, 100] == 0


def test_sharpness_drops_when_blurred():
    img = scene()
    assert watch.sharpness(cv2.GaussianBlur(img, (21, 21), 0)) < 0.3 * watch.sharpness(img)


# -- calibration ---------------------------------------------------------------

def test_calibration_recovers_the_camera_and_the_tool_length():
    from sketch_artist.pickplace_overhead import calibrate
    true_arm = geo.ArmGeometry(tool_mm=190.0)
    P = camera()
    poses = calibrate.calibration_poses(true_arm, [70, 95, 120, 145, 170])
    assert len(poses) >= 25
    assert min(true_arm.chain(p)["tip"][1] for p in poses) >= 149.0     # never near the floor
    rng = np.random.default_rng(4)
    samples = [calibrate.Sample(p, tuple(np.array(geo.project(P, true_arm.point_xyz(p, "tip")))
                                         + rng.normal(0, 1.0, 2))) for p in poses]
    wrong = geo.ArmGeometry(tool_mm=100.0)                              # the configured guess
    cal = calibrate.fit(samples, wrong, range(150, 231, 2))
    assert abs(cal.tool_mm - 190.0) <= 8.0
    assert cal.rms_px < 2.0
    assert calibrate.fit(samples, wrong).rms_px > 3 * cal.rms_px        # 100 mm cannot explain it
    x, y = geo.back_project(cal.P, geo.project(P, (-200.0, 60.0, 19.0)), 19.0)
    assert math.hypot(x + 200.0, y - 60.0) < 6.0
    arm = geo.ArmGeometry(tool_mm=cal.tool_mm)
    assert calibrate.leave_one_out_mm(samples, arm) < 4.0


def test_calibration_drops_a_sighting_that_landed_on_a_cable():
    from sketch_artist.pickplace_overhead import calibrate
    P = camera()
    poses = calibrate.calibration_poses(ARM, [70, 95, 120, 145, 170])
    samples = [calibrate.Sample(p, geo.project(P, ARM.point_xyz(p, "tip"))) for p in poses]
    u, v = samples[5].pixel
    samples[5] = calibrate.Sample(samples[5].angles, (u + 90.0, v - 60.0))
    cal = calibrate.fit(samples, ARM)
    assert cal.rejected == 1 and cal.rms_px < 0.5


def test_fingertip_is_the_far_end_of_the_new_white_blob():
    from sketch_artist.pickplace_overhead import calibrate
    ref = np.full((600, 800, 3), FLOOR, np.uint8)
    cv2.rectangle(ref, (560, 330), (700, 470), (232, 232, 228), -1)     # base sheet, always white
    frame = ref.copy()
    cv2.line(frame, (620, 400), (380, 300), (40, 110, 240), 40)         # orange forearm
    cv2.line(frame, (380, 300), (270, 254), (236, 236, 232), 18)        # white jaws
    cv2.line(frame, (0, 100), (300, 120), (225, 225, 225), 5)           # a white cable elsewhere
    heading = math.degrees(math.atan2(-(254 - 400), 270 - 620))
    assert calibrate.find_fingertip(ref, frame, (620, 400), heading)[0] < 50      # fooled by the cable
    tip = calibrate.find_fingertip(ref, frame, (620, 400), heading, expected_px=(300, 280))
    assert tip is not None
    assert math.hypot(tip[0] - 270, tip[1] - 254) < 12.0
    assert calibrate.find_fingertip(ref, ref, (620, 400), heading) is None


def test_arm_where_expected_fails_when_the_base_has_turned():
    P = camera()
    angles = pose(-200.0, 60.0, 60.0)
    img = np.full((1080, 1920, 3), FLOOR, np.uint8)
    e = geo.project(P, ARM.point_xyz(angles, "elbow"))
    w = geo.project(P, ARM.point_xyz(angles, "wrist"))
    cv2.line(img, tuple(int(v) for v in e), tuple(int(v) for v in w), (40, 110, 240), 70)
    assert watch.arm_where_expected(img, P, ARM, angles).ok
    turned = (angles[0] + 25.0,) + angles[1:]          # commanded, but the arm did not follow
    assert not watch.arm_where_expected(img, P, ARM, turned).ok
    red = np.full((1080, 1920, 3), FLOOR, np.uint8)
    cv2.line(red, tuple(int(v) for v in e), tuple(int(v) for v in w), COLOURS[detect.RED], 70)
    assert not watch.arm_where_expected(red, P, ARM, angles).ok     # a red brick is not the arm
