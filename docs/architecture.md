# Architecture

```
 Wrist camera @ person pose ─► portrait.py ─► vectorize.py ─► planner.py ─► kinematics.py ─► arm_client.py ─► Braccio
                                                                                                   │
                                          preview.py / gallery.py ─► output/ ─► web/server.py :7100

 Setup (run once before drawing):
 Wrist camera @ page pose ─► calibration.py ─► config/homography.json  (verify paper placement)

 No hardware:
 sketch_artist/sim.py  ─► software M/S arm agent + FK pen render (drop-in for the arm)
 sim/gazebo, sim/render_arm.py ─► drive / render the real unoq_braccio_sim Braccio model
```

## Modules

The studio adds a guarded control path alongside the portrait CLI:

```text
Touch / gamepad / Three.js preview
          |
          v
web/server.py -> web/control.py -> active tool profile -> IK/FK checks
                       |                                  |
                       +-> task plan (no motion)          v
                       +-> held single-step request -> arm_client.py -> :8765

config defaults + config/runtime.yaml -> studio, portrait CLI, calibration UI
```

| Module                       | Responsibility                                              |
| ---------------------------- | ----------------------------------------------------------- |
| `sketch_artist/config.py`    | Load defaults and atomic runtime overrides; resolve repo-relative paths. |
| `sketch_artist/cameras.py`   | USB V4L2/AVFoundation, HTTP snapshots, MJPEG/RTSP, ESP serial and orientation. |
| `sketch_artist/paper.py`     | Invertible paper-local / base-frame rotation and translation. |
| `sketch_artist/portrait.py`  | Face detect + GrabCut person segmentation → caricature line art (hair/glasses). |
| `sketch_artist/vectorize.py` | Contours → simplified polyline strokes.                     |
| `sketch_artist/planner.py`   | Pixels → paper mm, nearest-neighbour ordering, pen up/down. |
| `sketch_artist/kinematics.py`| Planar 2-link IK → 6 Braccio servo angles.                  |
| `sketch_artist/fk.py`        | Forward kinematics (inverse of the IK): servo angles → pen tip. |
| `sketch_artist/sim.py`       | Software arm agent (`M`/`S`) + FK pen tracking + drawing render. |
| `sketch_artist/arm_client.py`| TCP client for the arm agent (`M`/`S` protocol, `:8765`).   |
| `sketch_artist/calibration.py`| Wrist-cam paper homography (cam px → paper mm).             |
| `sketch_artist/preview.py`   | Dry-run PNG/SVG of the toolpath.                            |
| `sketch_artist/gallery.py`   | Composite the branded postcard + update the manifest.       |
| `sketch_artist/cli.py`       | Orchestrator (`--image`, `--dry-run`, `--no-arm`, `--sim`, `--slow`).|
| `web/server.py`              | Studio, gallery and guarded JSON/camera APIs (stdlib HTTP, port 7100). |
| `web/control.py`             | Discovery, tool profiles, task planning, arming leases, bounded moves and settings. |
| `web/src/robot.js`           | Three.js articulated model, active end effector, paper and pick/place markers. |
| `web/src/input.js`           | Testable gamepad deadzone, enable/stop, reconnect and jaw-button logic. |
| `scripts/check_hardware.py`  | Read-only functional checks; optional required-device exit status. |
| `sim/gazebo/`                | `M`/`S` → `unoq_braccio_sim` Gazebo bridge (real Braccio model). |
| `sim/render_arm.py`          | Headless 3D render of the real Braccio drawing the caricature. |
| `firmware/esp_eye_camera/`   | ESP-EYE (ESP32) camera firmware: JPEG over Wi-Fi/USB.       |

## Data model

- **Stroke**: `list[(x, y)]` in pixels of the square line-art canvas.
- **Move**: `(x_mm, y_mm, pen_down)` in arm-base millimetres after the paper transform.
- **Tool profile**: active sketch/gripper plus independent gripper geometry and targets.
- **Task**: preflighted labelled joint targets, a cursor, and an expected last pose.
  Preparing a task never moves hardware. Each held step uses the same guarded
  move path as manual control; stop discards the task without releasing a load.
- The planner keeps aspect ratio and centres the drawing inside the paper box
  defined in `config/workspace.yaml`.

## Coordinate frames

- **Arm base frame**: origin at the base rotation axis; `+x` points away from
  the base, `+y` to the arm's left, `+z` up. Paper origin/size are given in this
  frame through the paper origin and `rotation_deg` in `workspace.yaml`.
- **Tool elevation**: sketch mode uses -90 degrees plus `pen_tilt_deg`;
  gripper mode supplies its measured length and configured elevation to the
  same two-link IK. The original sketch workspace is not overwritten.
- **Three.js frame**: arm `(x, y, z)` maps to scene `(x, z, -y)`. Tests verify
  front/left/right paper targets against the articulated 3D joint chain.

## Control Concurrency

Only one movement request can own the command lock. It may wait briefly for a
status read under the I/O lock, then rechecks authorization before sending.
Concurrent moves or rate-limited requests return a retryable 409 with no queued
command. Stop revokes the token without waiting for I/O. The browser sends at
most one in-flight move and ignores stale status replies from older arming
generations. There is no persistent motion queue or unattended background runner.

The agent reports commanded joint angles, not measured encoder positions.
Clearance checks concern the modelled tool point, not full-body collisions,
object grip force or real paper contact. Other direct TCP clients are outside
the web interlock and must not run concurrently.
