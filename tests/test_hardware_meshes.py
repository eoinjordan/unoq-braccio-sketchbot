"""The printable parts in hardware/ have to stay sliceable.

A mesh that is not closed, not manifold, or that carries stray shells slices
into junk without any warning, and an STL that no longer matches its OpenSCAD
source is worse than no source at all. Both used to be true here, so both are
checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.mesh_check import inspect_stl

PARTS = Path(__file__).resolve().parent.parent / "hardware" / "pencil-grip"
STLS = sorted(PARTS.glob("*.stl"))

# Wrist axis -> finger mounting face, from unoq_braccio_sim's URDF: 60 mm to
# wrist_rotation plus 30 mm to the finger. Anything hanging off a finger adds
# to this, and links.wrist_pen_mm in config/workspace.yaml has to agree.
WRIST_AXIS_TO_MOUNT_MM = 90.0


def test_there_are_parts_to_check():
    assert STLS, "no STL files found in hardware/pencil-grip"


@pytest.mark.parametrize("path", STLS, ids=lambda p: p.name)
def test_part_is_printable(path):
    report = inspect_stl(path)
    assert report.is_printable, f"{path.name}: " + "; ".join(report.problems())


@pytest.mark.parametrize("path", STLS, ids=lambda p: p.name)
def test_part_fits_a_hobby_printer(path):
    x, y, z = inspect_stl(path).size_mm
    assert max(x, y, z) < 180, f"{path.name} is {x:.0f}x{y:.0f}x{z:.0f} mm"


@pytest.mark.parametrize("name", ["braccio_pencil_grip", "braccio_pen_finger"])
@pytest.mark.parametrize("preset", ["8mm", "10mm"])
def test_pen_parts_have_both_presets(name, preset):
    assert (PARTS / f"{name}_{preset}.stl").exists()
    assert (PARTS / f"{name}_{preset}.scad").exists()


def test_pen_finger_keeps_the_whole_original_finger():
    """The pen finger must contain the untouched Braccio finger, so the claw
    still closes; the grip that replaces the finger must not."""
    finger = inspect_stl(PARTS / "braccio_mount_reference_mm.stl")
    pen_finger = inspect_stl(PARTS / "braccio_pen_finger_8mm.stl")
    grip = inspect_stl(PARTS / "braccio_pencil_grip_8mm.stl")

    claw_tip_z = finger.min_mm[2]
    assert pen_finger.min_mm[2] == pytest.approx(claw_tip_z, abs=0.01), \
        "the pen finger no longer reaches the original claw tip"
    assert grip.min_mm[2] > claw_tip_z, \
        "the pencil grip is supposed to replace the claw, not keep it"


def test_wrist_camera_mount_is_smaller_than_the_bracket_it_replaces():
    small = inspect_stl(PARTS / "braccio_wrist_camera_mount.stl")
    boxy = inspect_stl(PARTS / "braccio_wrist_camera_bracket.stl")
    assert small.volume_cm3 < boxy.volume_cm3 / 2
    assert max(small.size_mm) < max(boxy.size_mm)


@pytest.mark.parametrize("part", ["braccio_pencil_grip_8mm.stl",
                                  "braccio_pen_finger_8mm.stl"])
def test_configured_pen_length_matches_the_printed_grip(workspace_cfg, part):
    """links.wrist_pen_mm has to describe a grip that actually exists, or the
    planner solves for a pen tip that is nowhere near the paper.

    Both drawing parts are checked: the rigid collar and the pen finger the
    Gazebo model mounts by default (sim/gazebo grip_mesh)."""
    grip = inspect_stl(PARTS / part)
    collar_bottom_mm = -grip.min_mm[2]
    shortest = WRIST_AXIS_TO_MOUNT_MM + collar_bottom_mm
    configured = float(workspace_cfg["links"]["wrist_pen_mm"])
    assert configured >= shortest, (
        f"wrist_pen_mm={configured:.0f} is shorter than the grip itself "
        f"({shortest:.0f} mm to the collar's bottom edge, before the pencil "
        f"even sticks out)")
    assert configured <= shortest + 60, (
        f"wrist_pen_mm={configured:.0f} implies over 60 mm of pencil proud of "
        f"the collar")


GRIPPER_CAMERAS = ["braccio_gripper_xiao_round_display",
                   "braccio_gripper_esp_eye"]


@pytest.mark.parametrize("holder", GRIPPER_CAMERAS)
@pytest.mark.parametrize("suffix", ["", "_near", "_far", "_fit_test"])
def test_gripper_camera_is_exported_ready_to_print(holder, suffix):
    """Every variant comes from the one source and sits on the bed as
    exported, nothing below z = 0."""
    assert (PARTS / f"{holder}.scad").exists()
    assert (PARTS / "braccio_gripper_camera_lib.scad").exists()
    report = inspect_stl(PARTS / f"{holder}{suffix}.stl")
    assert report.is_printable
    assert report.min_mm[2] == pytest.approx(0.0, abs=0.01)
    assert max(report.size_mm) < 120, "should fit a small printer's bed"


@pytest.mark.parametrize("holder, across", [
    ("braccio_gripper_xiao_round_display", 51.7),   # 43.1 board + 2 x (0.3 + 4.0)
    ("braccio_gripper_esp_eye", 28.8),              # 21.0 board + 2 x (0.3 + 3.6)
])
def test_gripper_camera_fit_piece_is_just_the_board_holder(holder, across):
    piece = inspect_stl(PARTS / f"{holder}_fit_test.stl")
    whole = inspect_stl(PARTS / f"{holder}.stl")
    assert min(piece.size_mm[0], piece.size_mm[1]) == pytest.approx(across, abs=1.1)
    assert piece.size_mm[2] < 7
    assert piece.volume_cm3 < whole.volume_cm3 / 2


@pytest.mark.parametrize("holder", GRIPPER_CAMERAS)
def test_gripper_camera_tilt_variants_differ(holder):
    """near / default / far aim at 90 / 120 / 180 mm, so the saddle meets the
    board holder at a different angle in each."""
    heights = [inspect_stl(PARTS / f"{holder}{suffix}.stl").size_mm[2]
               for suffix in ("_near", "", "_far")]
    assert heights[0] < heights[1] < heights[2]


XIAO_HOLDER = "braccio_gripper_xiao_round_display"


@pytest.mark.parametrize("suffix", ["_cover", "_near_cover", "_far_cover",
                                    "_cover_fit_test"])
def test_round_display_cover_is_exported_ready_to_print(suffix):
    """One cover per aim distance (its flat underside follows the tilt), and
    a fit piece of the rim and snap arms. All print face down, no supports."""
    report = inspect_stl(PARTS / f"{XIAO_HOLDER}{suffix}.stl")
    assert report.is_printable
    assert report.min_mm[2] == pytest.approx(0.0, abs=0.01)
    assert max(report.size_mm) < 60


def test_round_display_cover_matches_the_ring_it_clips_to():
    cover = inspect_stl(PARTS / f"{XIAO_HOLDER}_cover.stl")
    ring = inspect_stl(PARTS / f"{XIAO_HOLDER}_fit_test.stl")
    # the cup is the ring's diameter; the snap arms stand 1.7 mm outside it
    assert max(cover.size_mm[0], cover.size_mm[1]) < ring.size_mm[1] + 4.5
    assert min(cover.size_mm[0], cover.size_mm[1]) > ring.size_mm[1] - 1.0
    piece = inspect_stl(PARTS / f"{XIAO_HOLDER}_cover_fit_test.stl")
    assert piece.size_mm[2] < cover.size_mm[2]
    assert piece.volume_cm3 < cover.volume_cm3


def test_saddle_fit_piece_is_the_saddle_alone():
    assert (PARTS / "braccio_gripper_saddle_fit_test.scad").exists()
    saddle = inspect_stl(PARTS / "braccio_gripper_saddle_fit_test.stl")
    assert saddle.is_printable
    assert saddle.min_mm[2] == pytest.approx(0.0, abs=0.01)
    for holder in GRIPPER_CAMERAS:
        assert saddle.volume_cm3 < inspect_stl(PARTS / f"{holder}.stl").volume_cm3


def test_saddle_leaves_the_gripper_servo_to_the_owner():
    """The servo is in no reference, so the slot and the block are parameters
    the source tells the owner to measure, not numbers presented as fact."""
    source = (PARTS / "braccio_gripper_camera_lib.scad").read_text(encoding="utf-8")
    for name in ("servo_slot_length", "servo_slot_width", "servo_stand_height",
                 "servo_from_pivots", "block_half_width", "block_taper",
                 "block_thickness"):
        line = next(l for l in source.splitlines() if l.startswith(f"{name} ="))
        assert "MEASURE" in line, f"{name} is not marked for measuring"
    assert "servo_clear" not in source
