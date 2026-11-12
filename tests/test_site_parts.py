"""The setup site has to serve every part it lists, under the right licence.

GitHub Pages publishes only ``site/``, so ``scripts/build_parts_page.py`` copies
the printable parts and the arm model meshes there and writes the page that
lists them. A part changed in ``hardware/`` without re-running that script, a
link to a file that is not there, or a licence stated wrongly beside a download
would all go unnoticed on the live site, so each is checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import build_parts_page
from scripts.mesh_check import inspect_stl

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
HARDWARE = REPO / "hardware"
PARTS_PAGE = SITE / "parts.html"
HOLDERS = ["braccio_gripper_xiao_round_display", "braccio_gripper_esp_eye"]
ARM_MESHES = ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll",
              "left_gripper", "right_gripper"]


def local_links(page: Path):
    text = page.read_text(encoding="utf-8")
    for target in re.findall(r'(?:href|src)="([^"]+)"', text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        yield target.split("#")[0]


def test_site_copies_and_page_match_the_hardware_folder():
    assert build_parts_page.build(check=True) == [], \
        "run: python scripts/build_parts_page.py"


@pytest.mark.parametrize("page", ["index.html", "parts.html"])
def test_every_local_link_on_the_site_resolves(page):
    missing = [target for target in local_links(SITE / page)
               if target and not (SITE / target).exists()]
    assert not missing, f"{page} links to files that are not published: {missing}"


def test_setup_page_offers_the_holders_as_camera_options():
    text = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'href="./parts.html#holder"' in text
    assert "XIAO ESP32S3 Sense" in text and "ESP-EYE" in text
    assert "./parts.html" in (SITE / "sw.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("folder", ["pencil-grip", "braccio-arm"])
def test_every_mesh_and_source_is_downloadable(folder):
    text = PARTS_PAGE.read_text(encoding="utf-8")
    for path in sorted((HARDWARE / folder).glob("*")):
        if path.suffix not in (".stl", ".scad"):
            continue
        link = f'href="./hardware/{folder}/{path.name}"'
        assert link in text, f"{path.name} is not linked from site/parts.html"
        assert build_parts_page.same(SITE / "hardware" / folder / path.name,
                                     path.read_bytes())


@pytest.mark.parametrize("holder", HOLDERS)
@pytest.mark.parametrize("suffix", ["", "_near", "_far", "_fit_test"])
def test_holder_downloads_are_listed(holder, suffix):
    text = PARTS_PAGE.read_text(encoding="utf-8")
    assert f"{holder}{suffix}.stl" in text
    assert f"{holder}.scad" in text
    assert f"{holder}_preview.png" in text
    assert "braccio_gripper_camera_lib.scad" in text


def test_the_side_arm_holder_is_gone():
    assert not list((HARDWARE / "pencil-grip").glob("braccio_wrist_xiao*"))
    assert "braccio_wrist_xiao" not in PARTS_PAGE.read_text(encoding="utf-8")


def test_each_group_states_its_own_licence():
    """Three licences meet on this page. The printed parts are CC BY-SA 4.0
    and the arm meshes GPL-3.0; neither is the MIT licence of the software."""
    text = PARTS_PAGE.read_text(encoding="utf-8")
    parts = text[text.index('id="parts"'):text.index('id="arm"')]
    arm = text[text.index('id="arm"'):]
    assert "CC BY-SA 4.0" in parts and "GPL" not in parts
    assert "GNU General Public License v3.0" in arm
    assert parts.count("<td>CC BY-SA 4.0</td>") >= 17
    assert arm.count("<td>GPL-3.0</td>") == len(ARM_MESHES)
    assert 'href="./hardware/pencil-grip/LICENSE"' in text
    assert 'href="./hardware/braccio-arm/LICENSE"' in text
    grip_licence = (HARDWARE / "pencil-grip" / "LICENSE").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in grip_licence


def test_arm_meshes_are_isolated_with_their_licence_and_source():
    folder = HARDWARE / "braccio-arm"
    licence = (folder / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in licence
    assert "Version 3, 29 June 2007" in licence
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/lots-of-things/braccio_moveit_gazebo" in readme
    assert "https://opus.stedden.org/2020/08/braccio-moveit-gazebo/" in readme
    assert "MIT" in readme and "not print-ready" in readme
    assert sorted(p.name for p in folder.glob("*.stl")) == sorted(
        f"braccio_{name}.stl" for name in ARM_MESHES)


@pytest.mark.parametrize("name", ARM_MESHES)
def test_arm_meshes_are_closed_and_in_millimetres(name):
    """Kept as found: closed surfaces, in mm (the URDF scales them by 0.001).
    Some hold several shells, which is why they are not offered as prints."""
    report = inspect_stl(HARDWARE / "braccio-arm" / f"braccio_{name}.stl")
    assert report.is_watertight
    assert 35 < max(report.size_mm) < 200


def test_readme_and_top_level_licence_notes_cover_both_folders():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "hardware/braccio-arm" in readme
    assert "hardware/pencil-grip/LICENSE" in readme
    assert "hardware/braccio-arm/LICENSE" in readme
    for holder in HOLDERS:
        assert f"{holder}.stl" in readme
    notice = (REPO / "NOTICE.md").read_text(encoding="utf-8")
    for needle in ("MIT", "CC BY-SA 4.0", "GPL-3.0", "hardware/braccio-arm",
                   "hardware/pencil-grip"):
        assert needle in notice


def test_page_says_plainly_what_software_is_not_written():
    text = PARTS_PAGE.read_text(encoding="utf-8")
    assert text.count("Not written.") == 2
    assert "executorch-zephyr-xiao-esp32s3" in text


def test_parts_page_is_plain_ascii():
    PARTS_PAGE.read_bytes().decode("ascii")
