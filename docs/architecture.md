# Architecture

```
 Razer Kiyo (face cam) ─► portrait.py ─► vectorize.py ─► planner.py ─► kinematics.py ─► arm_client.py ─► Braccio
                                                             │                                  ▲
 Solid Year gripper cam ─► calibration.py (homography) ──────┘                                  │
                                                             │                                  │
                                          preview.py / gallery.py ─► output/ ─► web/server.py :7100
```

## Modules

| Module                       | Responsibility                                              |
| ---------------------------- | ----------------------------------------------------------- |
| `sketch_artist/config.py`    | Load YAML config, resolve repo-relative paths.              |
| `sketch_artist/cameras.py`   | Resolve cameras by USB `VID:PID`, open with V4L2.           |
| `sketch_artist/portrait.py`  | Face crop + edge/line-art extraction (OpenCV).              |
| `sketch_artist/vectorize.py` | Contours → simplified polyline strokes.                     |
| `sketch_artist/planner.py`   | Pixels → paper mm, nearest-neighbour ordering, pen up/down. |
| `sketch_artist/kinematics.py`| Planar 2-link IK → 6 Braccio servo angles.                  |
| `sketch_artist/arm_client.py`| TCP client for the arm agent (`M`/`S` protocol, `:8765`).   |
| `sketch_artist/calibration.py`| Gripper-cam paper homography (cam px → paper mm).           |
| `sketch_artist/preview.py`   | Dry-run PNG/SVG of the toolpath.                            |
| `sketch_artist/gallery.py`   | Composite the branded postcard + update the manifest.       |
| `sketch_artist/cli.py`       | Orchestrator (`--image`, `--dry-run`, `--no-arm`, `--slow`).|
| `web/server.py`              | Branded live gallery (stdlib http, port 7100).              |

## Data model

- **Stroke**: `list[(x, y)]` in pixels of the square line-art canvas.
- **Move**: `(x_mm, y_mm, pen_down)` in paper millimetres.
- The planner keeps aspect ratio and centres the drawing inside the paper box
  defined in `config/workspace.yaml`.

## Coordinate frames

- **Arm base frame**: origin at the base rotation axis; `+x` points away from
  the base, `+y` to the arm's left, `+z` up. Paper origin/size are given in this
  frame in `workspace.yaml`.
- **Pen vertical assumption**: the wrist keeps the pen straight down, so the
  wrist point is directly above the tip by `links.wrist_pen_mm`. This reduces
  the IK to base rotation + a planar 2-link solve.
