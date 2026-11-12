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

HOLDER = "braccio_wrist_xiao_round_display"

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
    (f"{HOLDER}.stl", "Wrist holder for the XIAO round display, aimed 120 mm "
     "in front of the finger mount", f"{HOLDER}.scad"),
    (f"{HOLDER}_near.stl", "The same holder aimed 90 mm in front",
     f"{HOLDER}.scad"),
    (f"{HOLDER}_far.stl", "The same holder aimed 180 mm in front",
     f"{HOLDER}.scad"),
    (f"{HOLDER}_fit_test.stl", "Fit piece: the display ring and latches only",
     f"{HOLDER}.scad"),
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
  <header class="masthead"><a class="brand" href="./"><span>Sketchbot <b>Studio</b></span></a><nav><a href="./">Setup</a><a href="#holder">Display holder</a><a href="#parts">Parts</a><a href="#arm">Arm meshes</a><a href="{REPO_URL}" target="_blank" rel="noopener noreferrer">Source</a></nav></header>
  <main class="parts-page">
    <div class="title-row"><div><p class="eyebrow">ARDUINO UNO Q / BRACCIO</p><h1>Printable parts and models</h1></div><span class="release-tag">STL and OpenSCAD</span></div>
    <p class="parts-intro">Everything here is generated from <a href="{REPO_URL}/tree/main/hardware">hardware/</a> in the repository. Three licences apply, one per group, and each is stated beside its downloads. The Studio software itself is MIT.</p>

    <section id="holder" class="parts-section">
      <div class="section-heading"><span class="step">01</span><h2>Wrist display and camera holder</h2><a href="{REPO_URL}/blob/main/hardware/pencil-grip/README.md#braccio_wrist_xiao_round_display---camera-and-screen-on-the-wrist" target="_blank" rel="noopener noreferrer">Full notes</a></div>
      <div class="parts-figure">
        <img src="{grip}/{HOLDER}_preview.png" width="1400" height="1050" alt="The holder as printed: display ring with three latches, hub with four screw holes and the tie saddle">
        <img src="{arm}/xiao_round_display_on_wrist.png" width="1400" height="1050" alt="The holder on the Braccio wrist model, fitted by the hub screws, with the display and XIAO in the ring">
      </div>
      <p>A camera option for pick and place. It holds a Seeed Studio Round Display for XIAO with a XIAO ESP32S3 Sense plugged into the back. The camera looks past the gripper at the point between the claws; the screen faces the other way, towards the people watching. Licence: CC BY-SA 4.0. The right-hand picture includes the GPL-3.0 arm meshes.</p>
      <div class="parts-columns">
        <div>
          <h3>Downloads</h3>
          <ul>
            <li>{link("pencil-grip", HOLDER + ".stl")}: aimed 120 mm in front of the finger mounting face, 59 mm past the closed claws. Tilt 20.7 degrees.</li>
            <li>{link("pencil-grip", HOLDER + "_near.stl")}: aimed 90 mm in front. Tilt 25.6 degrees.</li>
            <li>{link("pencil-grip", HOLDER + "_far.stl")}: aimed 180 mm in front. Tilt 15.0 degrees.</li>
            <li>{link("pencil-grip", HOLDER + "_fit_test.stl")}: the display ring and latches on their own. Print this first.</li>
            <li>{link("pencil-grip", HOLDER + ".scad")}: OpenSCAD source. Every dimension is a named value at the top, with where it came from.</li>
            <li>{link("pencil-grip", HOLDER + "_preview.png")} and {link("braccio-arm", "xiao_round_display_on_wrist.png")}, {link("braccio-arm", "xiao_round_display_on_wrist_ties.png")}: pictures.</li>
          </ul>
          <h3>Parts list</h3>
          <ul>
            <li>Seeed Studio Round Display for XIAO (1.28 inch, 43 mm board).</li>
            <li>Seeed Studio XIAO ESP32S3 Sense with its camera board, on soldered pin headers.</li>
            <li>Either 4 x M2 screws, the ones the ESP-EYE wrist mount uses, or 2 x cable ties, 2.5 mm or 3.6 mm wide and at least 250 mm long.</li>
            <li>USB-C cable with slack for the wrist, or a small LiPo with a JST 1.25 plug.</li>
            <li>1 x 2.5 mm cable tie for the cable or the battery.</li>
          </ul>
        </div>
        <div>
          <h3>Print</h3>
          <ol>
            <li>Print the fit piece and press the display into it from the back, screen first. The board's front rim should seat on the bevel and the three latches should click over its back.</li>
            <li>Measure your board against the values marked ESTIMATE in the source. If the fit piece is tight or loose, change <code>board_fit</code>, <code>display_pcb_thick</code> or <code>board_slack</code> and export again.</li>
            <li>Print the holder as exported: rear rim of the ring on the bed, screen side up. PETG or PLA, 0.2 mm layers, 4 walls, 30 to 40 percent infill, no supports. The only bridge is 12 mm, over the battery plug notch.</li>
          </ol>
          <h3>Fit it with screws</h3>
          <ol>
            <li>Use this where the ESP-EYE wrist mount goes: the hub has the same four M2 holes on a 7 mm radius and the same centre bore.</li>
            <li>Turn the holder so the ring is on the side away from the pen collar, then screw the hub down.</li>
            <li>Press the display in with the XIAO's USB-C end at the gap beside the saddle.</li>
            <li>Tie the cable to the saddle face, leaving a loop long enough for the wrist to roll a quarter turn each way. A small LiPo sits on the same face.</li>
          </ol>
          <h3>Fit it with cable ties</h3>
          <ol>
            <li>Turn the holder round so the saddle meets the wrist body, below the roll joint: pad on one cheek, a jaw round each edge, lip over the top.</li>
            <li>Lay the gripper servo lead in the groove down the middle of the pad, or keep it outside the ties altogether.</li>
            <li>Thread one tie through each tunnel and round the wrist. They sit 6 mm and 20 mm below the roll joint. Pull them tight and trim the tails.</li>
            <li>Tie the cable or the battery to the hub, which now stands clear on the outside.</li>
          </ol>
        </div>
      </div>
      <h3>What the two fittings do differently</h3>
      <p>Screwed on, the holder turns with the gripper, so the picture stays square to the claws at every roll angle. Tied on, it stays with the wrist: the camera still looks at the same point on the gripper's centre line, from 14 to 21 mm further back depending on the aim distance, but the claws cross the view when the gripper is rolled close to a quarter turn. With ties, use the default or far holder or a right-angle USB-C plug: the near holder brings a straight plug within 1 mm of a fully open claw at a quarter turn.</p>
      <h3>Software</h3>
      <table class="parts-table">
        <thead><tr><th>Piece</th><th>State</th></tr></thead>
        <tbody>
          <tr><td>Studio camera sources</td><td>USB cameras, and ESP-EYE boards over HTTP or serial with <a href="{REPO_URL}/tree/main/firmware/esp_eye_camera">firmware/esp_eye_camera</a>. That sketch's pin map is for the ESP-EYE; it does not run on a XIAO ESP32S3 Sense as it stands.</td></tr>
          <tr><td>Camera picture and a result on the round display</td><td>Written, in a separate repository: <a href="{XIAO_FIRMWARE_URL}">executorch-zephyr-xiao-esp32s3</a>. Zephyr firmware for this board pair that shows the camera crop, the digit an MNIST model reads from it and the inference time. It does not talk to the Studio.</td></tr>
          <tr><td>Streaming this camera to the Studio</td><td>Not written.</td></tr>
          <tr><td>Showing pick-and-place detections on the screen while streaming</td><td>Not written.</td></tr>
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
      <p>Also in this group, under the same licence because they include the meshes: {link("braccio-arm", "xiao_round_display_on_wrist.scad")}, the scene that draws the display holder on the wrist, and the two pictures rendered from it.</p>
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
