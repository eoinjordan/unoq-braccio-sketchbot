# Braccio drawing + camera tooling

The 3D-printed parts for the Sketchbot. All of them keep the exact TinkerKit
Braccio mounting interfaces, so they bolt on with the original screws.

![Grip preview](braccio_pencil_grip_preview.png)

> **Source / attribution:** *Braccio ROS2 Pencil/Pen Drawing Grip – Arduino
> UNO Q + Edge Impulse Demo* by **eoinedge**, published on Thingiverse:
> <https://www.thingiverse.com/thing:7382987>.
> Licensed **CC BY-SA 4.0** (see [LICENSE](LICENSE)). This differs from the
> repository's MIT license, which does not cover the files in this folder.

## Which part do I want?

| I want to…                                        | Print                              |
| ------------------------------------------------- | ---------------------------------- |
| Draw, and the claws can stay out of action         | `braccio_pencil_grip_8mm.stl`      |
| Draw **and** keep the claws working                | `braccio_pen_finger_8mm.stl`       |
| Put a camera on a finger, claws still working      | `braccio_camera_finger.stl`        |
| Put a camera on the wrist, both fingers free       | `braccio_wrist_camera_mount.stl`   |

The `_10mm` variants take thicker pens and markers; `_8mm` suits common 7–8 mm
wooden pencils.

### `braccio_pencil_grip` — rigid split collar (replaces a finger)

A split collar with an M3 screw and captive nut, in place of one Braccio
finger. The most rigid option, and the pen cannot slip — but while it is
fitted the gripper cannot hold anything.

### `braccio_pen_finger` — the same collar, beside the whole finger

The **original finger is imported whole and untouched**, claw included, with
the collar carried on one face and tied back to the blade by a web. So the
claws still close and grip; pull the pencil out (slacken the one M3 screw) and
the finger behaves exactly like a standard one.

`pen_side` picks the +y (`1`, default) or -y (`-1`) face. It has to be the
**outside** face — the one that does not meet the opposing finger — or the
claws will foul the collar. Fit it, see which way it closes, flip the sign if
needed.

### `braccio_camera_finger` — camera on a finger, claws still working

Built the same way: the untouched original finger with a camera cradle beside
it. Sized for an **ESP-EYE** (see [`../../firmware/esp_eye_camera`](../../firmware/esp_eye_camera));
change `camera_width` / `camera_height` / `camera_depth` for anything else.

### `braccio_wrist_camera_mount` — the small wrist mount

Replaces the old `braccio_wrist_camera_bracket.stl` (a 56 × 44 × 49 mm,
16.6 cm³ box) with a 31 × 32 × 44 mm, 5.3 cm³ hub-arm-plate, on the **same**
mounting interface: four M2 screws on a 7 mm radius cross plus a 6.2 mm centre
bore, measured off the original bracket.

The plate takes any camera: two M2 holes at `board_hole_pitch` for an
ESP32-CAM/ESP-EYE, two strap slots for a zip tie or elastic round a USB webcam,
a ledge for it to rest on, and a flat face if you would rather use tape.
`-D tilt=20` cants it towards the paper.

## Files

| File                                | Purpose                                      |
| ----------------------------------- | -------------------------------------------- |
| `braccio_grip_lib.scad`             | Shared clamp + finger geometry.               |
| `braccio_pencil_grip.scad`          | Split collar that replaces a finger.          |
| `braccio_pen_finger.scad`           | Collar beside the whole finger.               |
| `braccio_camera_finger.scad`        | Camera cradle beside the whole finger.        |
| `braccio_wrist_camera_mount.scad`   | Minimal wrist camera mount.                   |
| `*_8mm.scad` / `*_10mm.scad`        | Bore-size presets; the geometry lives above.  |
| `*.stl` / `*.obj`                   | Rendered meshes, regenerated from the source. |
| `braccio_mount_reference_mm.stl`    | The original Braccio finger — **required** by the SCAD. |
| `braccio_camera_mount.stl`          | Older end-effector camera mount (replaces a finger). |
| `braccio_wrist_camera_bracket.stl`  | The older, bulkier wrist bracket.             |

Every STL is validated in CI (`tests/test_hardware_meshes.py`): closed,
manifold, one shell, and small enough for a hobby printer.

```bash
python scripts/mesh_check.py hardware/pencil-grip/*.stl
```

## Regenerating the meshes

The shipped STLs are rendered straight from the SCAD source — don't hand-edit
them:

```bash
scripts/render_hardware.sh
```

That renders every preset, converts to binary STL, writes the OBJ copies, and
re-runs the validation. Override `OPENSCAD=` / `PYTHON=` if they are not on
your `PATH`. For a one-off size:

```bash
openscad -o my_grip.stl -D pencil_diameter=9 braccio_pencil_grip.scad
```

## Hardware

- 1 × M3 socket-head screw, 16–20 mm long, and 1 × M3 hex nut (per clamp)
- 4 × M2 screws for the wrist camera mount (reuse the bracket's)
- The original Braccio finger mounting screws

## Print settings

- Material: **PETG preferred** (best clamp flex); PLA+ also fine.
- Layer height: 0.20 mm.
- Walls: 4 · Top/bottom: 5 · Infill: 30–40 % gyroid or cubic.
- Supports: build-plate supports may be needed under the collar/shoulder.

## Assembly

1. Print the size you need (mounting face on the plate, or on its side with
   supports under the collar).
2. Press the M3 nut into the captive hex pocket.
3. Fit the M3 screw loosely through the opposite clamp ear.
4. Mount the part with the original Braccio finger screws.
5. Insert the pencil until it bottoms out in the bore — the bore is blind on
   purpose, so the tip ends up the same distance out every time, which is what
   makes `wrist_pen_mm` repeatable.
6. Tighten the M3 screw just enough to stop slipping — don't crush a wooden
   pencil.

## Wiring it into the Sketchbot software

The pen is **rigidly clamped** (not held by the gripper), so:

- Set `links.wrist_pen_mm` in [`../../config/workspace.yaml`](../../config/workspace.yaml)
  to the wrist-axis-to-tip distance. The SCAD echoes the number when you render
  it: 90 mm from the wrist axis to the finger mounting face (from the URDF),
  plus the collar length, plus however far the pencil sticks out. For
  `braccio_pencil_grip` that is about **174 mm**.
- **Then re-run the workspace check.** A long pen pushes the wrist point high,
  which shrinks the drawable area sharply — the elbow and wrist servos only
  bend ±90° from in line, so the drawable region is a fairly narrow annulus:

  ```bash
  python scripts/check_workspace.py --suggest
  ```

  It prints the largest paper box that actually fits and refuses to let you
  configure one that does not (the planner silently *skips* moves it cannot
  solve, so an oversized box just loses strokes). Standing the arm on a ~60 mm
  riser, or hanging the paper below the base plane, roughly doubles the box.
- `pen.down_gripper` just sets a neutral finger angle; the screw holds the tool.
- There is no built-in Z compliance. Tune `pen.down_z_mm` carefully and keep
  downward force light.

## A note on the source

An earlier revision's STLs did not match the SCAD: rendering the source
produced a mesh with two stray 0.5 mm shells (inherited from the reference
finger) and a non-manifold edge, while the shipped STLs had been repaired
externally. The reference mesh is now clean, `scripts/render_hardware.sh`
regenerates everything from source, and the test suite checks it stays that
way. The clamp also had only 0.8 mm of material behind the screw head; the
clamp lug is now hulled onto the collar with ≥2 mm webs, and the collar wall is
parametric (3.4 mm by default) so it can actually flex closed — which also took
the 8 mm grip from 15.9 cm³ down to 9.9 cm³ of plastic hanging off the wrist.
