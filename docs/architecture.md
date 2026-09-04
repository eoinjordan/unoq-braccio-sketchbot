# Architecture

```
 Razer Kiyo (face cam) ─► portrait.py ─► vectorize.py ─► planner.py ─► kinematics.py ─► arm_client.py ─► Braccio
                                                                                                   │
                                          preview.py / gallery.py ─► output/ ─► web/server.py :7100

 Setup (run once before drawing):
 Solid Year gripper cam ─► calibration.py ─► config/homography.json  (verify paper placement)

 No hardware:
 sketch_artist/sim.py  ─► software M/S arm agent + FK pen render (drop-in for the arm)
 sim/gazebo, sim/render_arm.py ─► drive / render the real unoq_braccio_sim Braccio model
```

## Modules

| Module                       | Responsibility                                              |
| ---------------------------- | ----------------------------------------------------------- |
| `sketch_artist/config.py`    | Load YAML config, resolve repo-relative paths.              |
| `sketch_artist/cameras.py`   | Resolve cameras by USB `VID:PID`, open with V4L2.           |
| `sketch_artist/portrait.py`  | Face detect + GrabCut person segmentation → caricature line art (hair/glasses). |
| `sketch_artist/vectorize.py` | Contours → simplified polyline strokes.                     |
| `sketch_artist/planner.py`   | Pixels → paper mm, nearest-neighbour ordering, pen up/down. |
| `sketch_artist/kinematics.py`| Planar 2-link IK → 6 Braccio servo angles.                  |
| `sketch_artist/fk.py`        | Forward kinematics (inverse of the IK): servo angles → pen tip. |
| `sketch_artist/sim.py`       | Software arm agent (`M`/`S`) + FK pen tracking + drawing render. |
| `sketch_artist/arm_client.py`| TCP client for the arm agent (`M`/`S` protocol, `:8765`).   |
| `sketch_artist/calibration.py`| Gripper-cam paper homography (cam px → paper mm).           |
| `sketch_artist/preview.py`   | Dry-run PNG/SVG of the toolpath.                            |
| `sketch_artist/gallery.py`   | Composite the branded postcard + update the manifest.       |
| `sketch_artist/cli.py`       | Orchestrator (`--image`, `--dry-run`, `--no-arm`, `--sim`, `--slow`).|
| `web/server.py`              | Branded live gallery (stdlib http, port 7100).              |
| `sim/gazebo/`                | `M`/`S` → `unoq_braccio_sim` Gazebo bridge (real Braccio model). |
| `sim/render_arm.py`          | Headless 3D render of the real Braccio drawing the caricature. |

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
