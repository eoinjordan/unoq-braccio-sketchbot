# Calibration

Drawing quality depends entirely on geometry. Do these steps in order and
re-run `--dry-run` after each change.

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
3. Run `python -m sketch_artist.cli --dry-run` and inspect `output/preview.png`.
4. Run `--slow` and watch the first strokes; adjust `pen.down_z_mm` /
   `pen.up_z_mm` until the pen touches with light, even pressure. The
   spring-loaded pen holder absorbs small errors.

## 4. Paper homography (gripper camera)

```bash
python -m sketch_artist.calibration --save config/homography.json
```

This detects the paper's four corners in the gripper-camera view and stores a
camera-pixel → paper-millimetre homography. Use it to confirm the paper is where
`workspace.yaml` claims and to monitor drawing. For booth robustness, replace
the plain-quad detector with an ArUco/AprilTag marker.

> Tip: the registration ticks on the printed template give the corner detector
> clean, high-contrast targets.
