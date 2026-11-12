#!/usr/bin/env python3
"""Publish the printable parts and the arm model meshes on the setup site.

GitHub Pages serves only ``site/``, so the files people download have to live
there. This copies them from ``hardware/`` and writes ``site/parts.html``, the
page that lists every one with its size, its licence and its links:

    python scripts/build_parts_page.py           # copy and rewrite
    python scripts/build_parts_page.py --check   # fail if anything is stale

``tests/test_site_parts.py`` runs the check, so a part changed in ``hardware/``
without re-running this fails the suite. Needs numpy only.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.mesh_check import inspect_stl  # noqa: E402

HARDWARE = REPO / "hardware"
SITE = REPO / "site"
PAGE = SITE / "parts.html"
REPO_URL = "https://github.com/eoinjordan/unoq-braccio-sketchbot"
XIAO_FIRMWARE_URL = "https://github.com/eoinjordan/executorch-zephyr-xiao-esp32s3"

XIAO = "braccio_gripper_xiao_round_display"
EYE = "braccio_gripper_esp_eye"

# Folder, licence shown beside its downloads, and which files are published.
GROUPS = {
    "pencil-grip": {
        "licence": "CC BY-SA 4.0",
        "patterns": ["*.stl", "*.scad", "*_preview.png", "LICENSE"],
    },
    "braccio-arm": {
        "licence": "GPL-3.0",
        "patterns": ["*.stl", "*.scad", "*.png", "LICENSE", "README.md"],
    },
}

# What each mesh is, and the source it is rendered from where there is one.
PENCIL_GRIP = [
    (f"{XIAO}.stl", "Gripper-top holder for the XIAO round display, aimed "
     "120 mm in front of the finger mount", f"{XIAO}.scad"),
    (f"{XIAO}_near.stl", "The same holder aimed 90 mm in front", f"{XIAO}.scad"),
    (f"{XIAO}_far.stl", "The same holder aimed 180 mm in front", f"{XIAO}.scad"),
    (f"{XIAO}_fit_test.stl", "Fit piece: the display ring and latches only",
     f"{XIAO}.scad"),
    (f"{EYE}.stl", "Gripper-top holder for the ESP-EYE, aimed 120 mm in front "
     "of the finger mount", f"{EYE}.scad"),
    (f"{EYE}_near.stl", "The same holder aimed 90 mm in front", f"{EYE}.scad"),
    (f"{EYE}_far.stl", "The same holder aimed 180 mm in front", f"{EYE}.scad"),
    (f"{EYE}_fit_test.stl", "Fit piece: the ESP-EYE frame and latches only",
     f"{EYE}.scad"),
    ("braccio_wrist_camera_mount.stl", "Wrist mount for an ESP-EYE",
     "braccio_wrist_camera_mount.scad"),
    ("braccio_camera_finger.stl", "ESP-EYE cradle beside a whole finger",
     "braccio_camera_finger.scad"),
    ("braccio_pen_finger_8mm.stl", "Pen collar beside a whole finger, 8 mm bore",
     "braccio_pen_finger_8mm.scad"),
    ("braccio_pen_finger_10mm.stl", "Pen collar beside a whole finger, 10 mm bore",
     "braccio_pen_finger_10mm.scad"),
    ("braccio_pencil_grip_8mm.stl", "Split collar in place of a finger, 8 mm bore",
     "braccio_pencil_grip_8mm.scad"),
    ("braccio_pencil_grip_10mm.stl", "Split collar in place of a finger, 10 mm bore",
     "braccio_pencil_grip_10mm.scad"),
    ("braccio_camera_mount.stl", "Older camera mount in place of a finger", None),
    ("braccio_wrist_camera_bracket.stl", "Older, larger wrist bracket", None),
    ("braccio_mount_reference_mm.stl", "The original Braccio finger, used by "
     "the sources above", None),
]

SHARED_SOURCES = [
    ("braccio_gripper_camera_lib.scad", "Gripper saddle, ties, screw slots and "
     "aim, shared by the two gripper-top holders"),
    ("braccio_grip_lib.scad", "Shared clamp and finger geometry"),
    ("braccio_pencil_grip.scad", "Split collar, all bore sizes"),
    ("braccio_pen_finger.scad", "Pen finger, all bore sizes"),
]

BRACCIO_ARM = [
    ("braccio_base.stl", "Base"),
    ("braccio_shoulder.stl", "Shoulder link"),
    ("braccio_elbow.stl", "Elbow link"),
    ("braccio_wrist_pitch.stl", "Wrist pitch link"),
    ("braccio_wrist_roll.stl", "Wrist roll link"),
    ("braccio_left_gripper.stl", "Left gripper blade"),
    ("braccio_right_gripper.stl", "Right gripper blade"),
]


def published_files():
    """(source path, path under site/) for every file the site serves."""
    pairs = []
    for folder, group in GROUPS.items():
        seen = set()
        for pattern in group["patterns"]:
            for path in sorted((HARDWARE / folder).glob(pattern)):
                if path not in seen:
                    seen.add(path)
                    pairs.append((path, Path("hardware") / folder / path.name))
    return pairs


def size_text(path):
    x, y, z = inspect_stl(path).size_mm
    return f"{x:.1f} x {y:.1f} x {z:.1f}"


def kilobytes(path):
    return f"{max(1, round(path.stat().st_size / 1024))} kB"


def link(folder, name, text=None):
    return (f'<a href="./hardware/{folder}/{html.escape(name)}" download>'
            f"{html.escape(text or name)}</a>")


def mesh_rows(folder, entries):
    rows = []
    for entry in entries:
        name, what = entry[0], entry[1]
        source = entry[2] if len(entry) > 2 else None
        path = HARDWARE / folder / name
        cells = [
            f"<td>{link(folder, name)}<small>{kilobytes(path)}</small></td>",
            f"<td>{html.escape(what)}</td>",
            f"<td>{size_text(path)}</td>",
            f"<td>{GROUPS[folder]['licence']}</td>",
        ]
        if folder == "pencil-grip":
            cells.append(f"<td>{link(folder, source) if source else 'none'}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def source_rows():
    return "\n".join(
        f"<tr><td>{link('pencil-grip', name)}</td><td>{html.escape(what)}</td>"
        f"<td>{GROUPS['pencil-grip']['licence']}</td></tr>"
        for name, what in SHARED_SOURCES)


def render():
    grip = "./hardware/pencil-grip"
    arm = "./hardware/braccio-arm"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#087f60">
  <meta name="description" content="Printable parts for the Sketchbot Braccio arm and the arm model meshes, with sizes, licences and downloads.">
  <link rel="icon" type="image/png" href="./assets/icon-192.png">
  <link rel="stylesheet" href="./assets/setup.css">
  <link rel="stylesheet" href="./style.css">
  <title>Sketchbot Studio / Printable parts and models</title>
</head>
<body>
  <header class="masthead"><a class="brand" href="./"><span>Sketchbot <b>Studio</b></span></a><nav><a href="./">Setup</a><a href="#holder">Gripper cameras</a><a href="#parts">Parts</a><a href="#arm">Arm meshes</a><a href="{REPO_URL}" target="_blank" rel="noopener noreferrer">Source</a></nav></header>
  <main class="parts-page">
    <div class="title-row"><div><p class="eyebrow">ARDUINO UNO Q / BRACCIO</p><h1>Printable parts and models</h1></div><span class="release-tag">STL and OpenSCAD</span></div>
    <p class="parts-intro">Everything here is generated from <a href="{REPO_URL}/tree/main/hardware">hardware/</a> in the repository. Three licences apply, one per group, and each is stated beside its downloads. The Studio software itself is MIT.</p>

    <section id="holder" class="parts-section">
      <div class="section-heading"><span class="step">01</span><h2>Cameras on top of the gripper</h2><a href="{REPO_URL}/blob/main/hardware/pencil-grip/README.md#cameras-on-top-of-the-gripper" target="_blank" rel="noopener noreferrer">Full notes</a></div>
      <p>Two camera options for pick and place. Each stands on the flat face of the gripper block, just behind the finger pivots, and looks forward along the fingers and down at the point the claws are about to close on. Because it is on the gripper it follows wrist roll. Licence: CC BY-SA 4.0. The pictures include the GPL-3.0 arm meshes.</p>
      <div class="parts-figure">
        <figure><img src="{arm}/gripper_xiao_round_display_side.png" width="1400" height="1050" alt="XIAO round display holder on the gripper model, seen from the side: the ring stands on the gripper block and the camera looks forward and down along the fingers"><figcaption>XIAO ESP32S3 Sense on the Round Display, from the side.</figcaption></figure>
        <figure><img src="{arm}/gripper_xiao_round_display_audience.png" width="1400" height="1050" alt="The same holder seen from behind: the round screen faces back up the arm"><figcaption>The same, from behind: the screen faces the audience.</figcaption></figure>
        <figure><img src="{arm}/gripper_esp_eye_side.png" width="1400" height="1050" alt="ESP-EYE holder on the gripper model, seen from the side: the board stands upright on the gripper block with the lens looking forward"><figcaption>ESP-EYE, from the side.</figcaption></figure>
        <figure><img src="{arm}/gripper_esp_eye_audience.png" width="1400" height="1050" alt="The ESP-EYE holder seen from behind, with the USB plug leaving upwards"><figcaption>ESP-EYE, from behind.</figcaption></figure>
      </div>
      <div class="parts-scroll"><table class="parts-table">
        <thead><tr><th>Holder</th><th>Aimed in front of the finger mount</th><th>Tilt</th><th>Lens above the gripper centre line</th><th>Closed claws cover</th></tr></thead>
        <tbody>
          <tr><td>{link("pencil-grip", XIAO + "_near.stl")}</td><td>90 mm</td><td>17.3 deg</td><td>21.0 mm</td><td>20 percent of the picture</td></tr>
          <tr><td>{link("pencil-grip", XIAO + ".stl")}</td><td>120 mm</td><td>13.3 deg</td><td>22.8 mm</td><td>13 percent</td></tr>
          <tr><td>{link("pencil-grip", XIAO + "_far.stl")}</td><td>180 mm</td><td>9.0 deg</td><td>24.8 mm</td><td>8 percent</td></tr>
          <tr><td>{link("pencil-grip", EYE + "_near.stl")}</td><td>90 mm</td><td>11.3 deg</td><td>16.5 mm</td><td>29 percent</td></tr>
          <tr><td>{link("pencil-grip", EYE + ".stl")}</td><td>120 mm</td><td>8.6 deg</td><td>17.0 mm</td><td>23 percent</td></tr>
          <tr><td>{link("pencil-grip", EYE + "_far.stl")}</td><td>180 mm</td><td>5.8 deg</td><td>17.5 mm</td><td>15 percent</td></tr>
        </tbody>
      </table></div>
      <p>The claw tips are 61.4 mm in front of the finger mount, so the default aims 59 mm past them. Open and half-open claws are outside the picture; the cover figures are for claws fully closed, measured on the model's flat 101 mm blades with a 66 degree lens.</p>
      <div class="parts-columns">
        <div>
          <h3>Downloads</h3>
          <ul>
            <li>Fit pieces, to print first: {link("pencil-grip", XIAO + "_fit_test.stl")} (the display ring) and {link("pencil-grip", EYE + "_fit_test.stl")} (the ESP-EYE frame).</li>
            <li>Sources: {link("pencil-grip", XIAO + ".scad")}, {link("pencil-grip", EYE + ".scad")} and the saddle they share, {link("pencil-grip", "braccio_gripper_camera_lib.scad")}. Every dimension is a named value with where it came from.</li>
            <li>Pictures: {link("pencil-grip", XIAO + "_preview.png")}, {link("pencil-grip", EYE + "_preview.png")}, and the four above.</li>
          </ul>
          <h3>Parts list</h3>
          <ul>
            <li>Either a Seeed Studio Round Display for XIAO with a XIAO ESP32S3 Sense on soldered pin headers, or an Espressif ESP-EYE v2.1.</li>
            <li>To fix it: 1 or 2 cable ties, 2.5 mm or 3.6 mm wide and at least 200 mm long, or 2 x M3 screws.</li>
            <li>A USB cable with slack for the wrist. The round display can run from a small LiPo with a JST 1.25 plug instead.</li>
          </ul>
          <h3>Measure the gripper first</h3>
          <p>The saddle is drawn from the simulation mesh, which shows the gripper block as a 4.5 mm plate. Yours is thicker and carries the gripper servo. Measure the width of the face at two points along it, and the thickness, and set <code>block_half_width</code>, <code>block_taper</code>, <code>block_thickness</code> and <code>servo_clear</code> in the shared source before you export a holder.</p>
        </div>
        <div>
          <h3>Print</h3>
          <ol>
            <li>Print the fit piece for your camera and press the board into it. The round display goes in from the back, screen first; the ESP-EYE goes in back first, camera end under the fixed hook, then the USB end past the two latches.</li>
            <li>If it is tight or loose, change <code>board_fit</code> or <code>board_slack</code> and export again. Check the values marked ESTIMATE in the source against your board.</li>
            <li>Print the holder as exported, lens side on the bed. PETG or PLA, 0.2 mm layers, 4 walls, 30 to 40 percent infill, no supports. Bridges are 12 mm or less.</li>
          </ol>
          <h3>Fit it with cable ties</h3>
          <ol>
            <li>Sit the saddle on the top face of the gripper block, jaws down the two sloping edges, and push it forward until the jaws are snug.</li>
            <li>Thread a tie through the front tunnel, just behind the finger pivots, and round the block. It passes over the finger bases in a bridge, clear of them. Add the rear tie, behind the servo, if you want two.</li>
            <li>Keep the gripper servo lead outside the ties, open and close the claws by hand to see nothing rubs, then pull the ties tight and trim them.</li>
          </ol>
          <h3>Fit it with screws</h3>
          <ol>
            <li>The pad has two slots for M3 screws. None of the references this part was drawn from shows a fixing point on the gripper block, so their position is a placeholder.</li>
            <li>Find two holes or studs on your gripper block, measure them, and set <code>screw_spacing</code>, <code>screw_centre_x</code> and <code>screw_z</code>. Export and print.</li>
          </ol>
        </div>
      </div>
      <h3>Software</h3>
      <table class="parts-table">
        <thead><tr><th>Piece</th><th>State</th></tr></thead>
        <tbody>
          <tr><td>ESP-EYE to the Studio</td><td>Written: <a href="{REPO_URL}/tree/main/firmware/esp_eye_camera">firmware/esp_eye_camera</a> serves snapshots and MJPEG over HTTP, or frames over USB serial.</td></tr>
          <tr><td>Camera picture and a result on the round display</td><td>Written, in a separate repository: <a href="{XIAO_FIRMWARE_URL}">executorch-zephyr-xiao-esp32s3</a>. Zephyr firmware for the XIAO and round display that shows the camera crop, the digit an MNIST model reads from it and the inference time. It does not talk to the Studio.</td></tr>
          <tr><td>Streaming the XIAO camera to the Studio</td><td>Not written.</td></tr>
          <tr><td>Showing pick-and-place detections on the round display while streaming</td><td>Not written.</td></tr>
        </tbody>
      </table>
    </section>

    <section id="parts" class="parts-section">
      <div class="section-heading"><span class="step">02</span><h2>Sketchbot printed parts</h2><a href="{grip}/LICENSE">Licence: CC BY-SA 4.0</a></div>
      <p>Pencil grips, pen fingers and camera mounts for the Braccio, with their OpenSCAD sources. All of them are licensed under <strong>CC BY-SA 4.0</strong>, the licence in <a href="{REPO_URL}/blob/main/hardware/pencil-grip/LICENSE">hardware/pencil-grip/LICENSE</a>, not the MIT licence that covers the software. Sizes are the bounding box in millimetres.</p>
      <div class="parts-scroll"><table class="parts-table">
        <thead><tr><th>STL</th><th>What it is</th><th>Size (mm)</th><th>Licence</th><th>Source</th></tr></thead>
        <tbody>
{mesh_rows("pencil-grip", PENCIL_GRIP)}
        </tbody>
      </table></div>
      <div class="parts-scroll"><table class="parts-table">
        <thead><tr><th>Shared source</th><th>What it is</th><th>Licence</th></tr></thead>
        <tbody>
{source_rows()}
        </tbody>
      </table></div>
    </section>

    <section id="arm" class="parts-section">
      <div class="section-heading"><span class="step">03</span><h2>Braccio arm model meshes</h2><a href="{arm}/LICENSE">Licence: GPL-3.0</a></div>
      <p>Seven meshes of the arm itself, copied unmodified from <a href="https://github.com/lots-of-things/braccio_moveit_gazebo">lots-of-things/braccio_moveit_gazebo</a> (<a href="https://opus.stedden.org/2020/08/braccio-moveit-gazebo/">article</a>) and licensed under the <strong>GNU General Public License v3.0</strong>. They are simulation visual meshes, one simplified shape per link, in millimetres. They are not print-ready arm parts: servos, screws and the gripper linkage are not modelled. See the <a href="{arm}/README.md">README</a> in the folder.</p>
      <div class="parts-scroll"><table class="parts-table">
        <thead><tr><th>STL</th><th>Link</th><th>Size (mm)</th><th>Licence</th></tr></thead>
        <tbody>
{mesh_rows("braccio-arm", BRACCIO_ARM)}
        </tbody>
      </table></div>
      <p>Also in this group, under the same licence because they include the meshes: {link("braccio-arm", "gripper_cameras_on_gripper.scad")}, the scene that draws the camera holders on the gripper, and the four pictures rendered from it.</p>
    </section>
  </main>
  <footer><span>Sketchbot Studio / Edge Impulse + Arduino UNO Q</span><a href="{REPO_URL}/blob/main/docs/safety.md" target="_blank" rel="noopener noreferrer">Safety and supervision</a></footer>
</body>
</html>
"""


def unix(data: bytes) -> bytes:
    return data.replace(bytes([13, 10]), bytes([10]))


def same(a: Path, b_bytes: bytes) -> bool:
    """Byte-equal, except that a checkout may have turned LF into CRLF in the
    text files (the ASCII STLs among them) on one side and not the other."""
    a_bytes = a.read_bytes()
    if 0 not in a_bytes and 0 not in b_bytes:
        return unix(a_bytes) == unix(b_bytes)
    return a_bytes == b_bytes


def build(check):
    stale = []
    for source, relative in published_files():
        target = SITE / relative
        if target.exists() and same(target, source.read_bytes()):
            continue
        stale.append(str(relative))
        if not check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    wanted = {SITE / relative for _, relative in published_files()}
    for folder in GROUPS:
        for extra in sorted((SITE / "hardware" / folder).glob("*")):
            if extra not in wanted:
                stale.append(f"{extra.relative_to(SITE)} (no longer published)")
                if not check:
                    extra.unlink()
    page = render().encode("ascii")
    if not PAGE.exists() or not same(PAGE, page):
        stale.append(PAGE.name)
        if not check:
            PAGE.write_bytes(page)
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report stale files instead of rewriting them")
    args = parser.parse_args(argv)
    stale = build(args.check)
    for name in stale:
        print(("stale: " if args.check else "updated: ") + name)
    if not stale:
        print("site/parts.html and site/hardware are up to date")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
