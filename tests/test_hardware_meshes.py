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
