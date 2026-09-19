# Calibration

Drawing quality depends entirely on geometry. Do these steps in order and
re-run `--dry-run` after each change.

The Studio menu saves changes in `config/runtime.yaml`, which overrides the
documented defaults below. The CLI and legacy calibration UI load that same
overlay. Editing a default alone will not override a saved menu setting.
Use **Setup > Paper / Arm** for the pen, and **Setup > Tools** for the gripper.
Tool switches disarm without moving or overwriting the pen calibration.

![Current tool setup menu](images/studio-gripper-setup.png)

## 1. Measure the arm (once)

With a ruler, fill in `config/workspace.yaml` → `links` (millimetres):

- `base_height_mm` – table to the shoulder axis.
- `shoulder_mm` – shoulder axis to elbow axis.
- `elbow_mm` – elbow axis to wrist axis.
- `wrist_pen_mm` – wrist axis to the **pen tip, with the holder mounted**.

## 2. Place and describe the paper

Tape the printed `assets/edge_impulse_paper_template.svg` down. Measure the
near-left corner of the drawing box relative to the base and set
`workspace.yaml` → `paper` (`origin_x_mm`, `origin_y_mm`, `width_mm`,
`height_mm`).

## 3. Tune the servo mapping

The IK produces *geometric* angles; each joint is converted to a servo angle
with `offset + sign * geometric` (`workspace.yaml` → `servo_calibration`).

1. Home the arm and note each servo angle where the link is at its geometric
   zero.
2. Set `offset`/`sign` per joint.
3. Run `.venv/bin/python -m sketch_artist.cli --dry-run` and inspect `output/preview.png`.
4. Run `--slow` and watch the first strokes; adjust `pen.down_z_mm` /
   `pen.up_z_mm` until the pen touches with light, even pressure. The printed
   grip is rigid, so go slowly — a small Z error shows up directly as pressure.
5. Find the joint stops before trusting any of the above. Hold every other
   joint, step one joint through the range the IK uses (raw `M` commands over
   `:8765`), and watch it — a phone camera is enough. A joint that gives the
   same frame for several commanded angles has a mechanical stop there; put it
   in `workspace.yaml` → `servo_limits` with a couple of degrees of margin.
   With the printed pen grip the wrist stops at ~14°, which `links.pen_tilt_deg`
   is there to clear.
6. Measure contact with a camera at paper level, not by feel: step z down
   1 mm at a time and take the height where the tip stops descending *and* the
   grip starts to pivot. Small height commands only move the tip a fraction of
   the way (servo dead band + backlash), so set `pen.down_z_mm` 1–2 mm past
   contact and keep `motion.pen_down_overshoot_mm` on. `web/calibrate` does the
   stepping; `scripts/check_workspace.py` confirms the box still clears the
   limits at the heights you chose.

## 4. Paper homography (wrist camera at the page pose)

```bash
.venv/bin/python -m sketch_artist.calibration --save config/homography.json
```

This detects the paper's four corners in the wrist-camera view (arm at the page
pose) and stores a
camera-pixel → paper-millimetre homography. Use it to confirm the paper is where
`workspace.yaml` claims and to monitor drawing. For booth robustness, replace
the plain-quad detector with an ArUco/AprilTag marker.

> Tip: the registration ticks on the printed template give the corner detector
> clean, high-contrast targets.

## 5. Supervised Test Square

Flatten and secure the sheet; remove tools and hands from the sweep. In Sketch
mode, **Plan test square** and **Play task preview** check a small square without
motion. Actual pen contact is not established by that preview. After measuring
contact, use supervised mode, select Real arm, plan again, check **Pen height
verified**, arm and hold **Hold to run**. Verify actual marks with the observation
camera. Release pauses and Stop cancels without an automatic return.

Do not increase downward pressure just because the sheet is blank. Confirm that
the pen tip is over the paper, the holder has not slipped, the wrist is clear of
its stop, and small height commands produce real movement. The software knows
commanded angles only. Stop if those observations disagree with the model.

## 6. Gripper Setup

Remove the pen before selecting Gripper. Measure the wrist-to-grasp-point length,
choose the tool elevation, and establish conservative open/closed jaw angles
without driving the jaws against a hard stop. Configure pick and place X/Y/Z in
the base frame and a transfer height at least 5 mm above both. First inspect the
nine-step sequence in Preview. Physical trials need a clear workspace, light
objects, adult supervision and the cutoff within reach. Never infer a successful
grasp from the sequence reaching its final command.
