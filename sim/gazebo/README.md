# Braccio Sketchbot — Gazebo simulation

Draw with the sketchbot into a **full 3D Gazebo** Braccio, using the real
mesh model from the companion [`unoq-braccio`](https://github.com/edgeimpulse/unoq-braccio)
repo (`unoq_braccio_sim`). The bridge here speaks the same `M`/`S` TCP protocol
as the real UNO Q arm agent, so the sketchbot pipeline drives the simulated arm
unchanged.

```
sketch_artist.cli ──M/S TCP:8765──► braccio_bridge ──/arm_controller/joint_trajectory──►
    JointTrajectoryController ──► gz_ros2_control ──► Gazebo (Braccio)
                                        │
                            pen_tracker ┤  ── measures the pen tip off TF
                            ink_marker  ┘  ── paints the stroke onto the paper
```

> **Just want a picture / a quick check?** Two lighter options need no ROS:
> - `python -m sketch_artist.cli --sim` — the built-in software simulator.
> - `python -m sim.render_arm` — renders the **same** `unoq_braccio_sim` STL
>   model drawing the caricature to `docs/images/gazebo_caricature.png`
>   (headless; see the repo README).

## Requirements

- ROS 2 **Jazzy** (or Humble) + **Gazebo (gz)** with `ros_gz_sim`,
  `gz_ros2_control`, `ros2_control`, `ros2_controllers`.
- The **`unoq-braccio`** repo checked out (it provides the Braccio STL meshes
  and the servo→radian mapping this builds on).

## Run it end to end

One command builds the workspace, starts Gazebo, draws, and checks the result:

```bash
scripts/run_gazebo_e2e.sh              # headless
scripts/run_gazebo_e2e.sh --gui        # watch it in the Gazebo GUI
```

It writes `output/gazebo_drawing.png` (what the simulated pen actually drew),
`output/gazebo_drawing.csv` (every pen-tip sample) and `output/gazebo_e2e.log`,
then compares the traced path with the planned strokes and fails if they
disagree by more than a few millimetres.

## Or run the pieces yourself

```bash
mkdir -p ~/braccio_ws/src && cd ~/braccio_ws/src
ln -s /path/to/unoq-braccio/ros2_ws/src/unoq_braccio_sim .
ln -s /path/to/unoq-braccio/ros2_ws/src/unoq_braccio_driver .
ln -s /path/to/unoq-braccio-sketchbot/sim/gazebo braccio_sim
cd ~/braccio_ws && colcon build --symlink-install && source install/setup.bash

ros2 launch braccio_sim sketchbot_gazebo.launch.py        # M/S on :8765
```

```bash
cd /path/to/unoq-braccio-sketchbot
python -m sketch_artist.cli --image examples/sample_face_eoin.png --style none
```

Useful launch arguments: `headless`, `port`, `move_time` (seconds per stroke
point), `command_mode`, `wrist_pen`, `grip_mesh`, `ink`, `pen_down_z` /
`pen_up_z`, and the four `paper_*` values.

## How it fits together

- **Meshes** come from `unoq_braccio_sim`; the **servo → joint mapping** comes
  from `unoq_braccio_driver`. One source of truth for both.
- **This package** adds the `M`/`S` TCP server
  ([`braccio_bridge.py`](braccio_sim/braccio_bridge.py)), the pen-tip recorder
  ([`pen_tracker.py`](braccio_sim/pen_tracker.py)), the live ink painter
  ([`ink_marker.py`](braccio_sim/ink_marker.py)), and a corrected robot
  description ([`braccio_sketchbot.urdf.xacro`](urdf/braccio_sketchbot.urdf.xacro)).
- **Joint order** (`base, shoulder, elbow, wrist_vertical, wrist_rotation,
  gripper`) matches the `M` command and the controller.

## The printed grip, and ink you can see

The tool on the simulated arm is the **actual printed part** from
[`hardware/pencil-grip/`](../../hardware/pencil-grip/) — by default
`braccio_pen_finger_8mm.stl`, the variant that keeps the claws working. It is
loaded as a visual-only mesh on `pen_link`, so it never pushes the paper around
in physics, and the launch file resolves it straight out of `hardware/` (no copy
in the ROS package) via the `grip_mesh_dir` / `grip_mesh` xacro arguments.

The placement is registered off the part's own OpenSCAD constants rather than
eyeballed: the bore axis sits at (16.5, 14.175) mm in the mesh's frame, the
mounting plane is mesh z = 0, and `rpy="${pi} 0 0"` flips the finger so it hangs
down `pen_link` +z. That puts the bore on the link axis with the pencil tip at
`wrist_pen`, and the 174 mm chain closes exactly:

    60 (wrist axis -> wrist_roll) + 30 (-> finger mount)
       + 57 (-> collar bottom) + 27 (pencil proud) = 174 mm

**The grip is a visual change only.** `pen_mount` and `pen_tip_joint` are
untouched, so `pen_tip` — the frame everything is measured against — does not
move, and the end-to-end deviation is unchanged (median 0.76 mm, p95 2.55 mm,
278/278 planned points reached).

`ink_marker` paints the path as it is drawn: it watches the same `world` ->
`pen_tip` transform `pen_tracker` does, with the same pen-down threshold, and
emits one `gz.msgs.Marker` LINE_STRIP per stroke just above the paper surface.
So the picture appears under the pencil while you watch.

    ros2 launch braccio_sim sketchbot_gazebo.launch.py ink:=false   # turn it off
    ros2 launch braccio_sim sketchbot_gazebo.launch.py \
        grip_mesh:=braccio_pen_finger_10mm.stl pen_diameter:=0.010  # thicker pen

Two things worth knowing. The markers are served by the **GUI** process, so ink
is skipped when `headless:=true` — the headless e2e still measures the path off
TF exactly as before. And the placement constants are measured from the
`pen_finger` parts; the older `braccio_pencil_grip_*.stl` has a different frame
(collar on the other face) and would need re-measuring before it lines up.

## Why this package has its own URDF

`unoq_braccio_sim`'s `braccio.urdf.xacro` puts an extra `rpy="-1.5708 0 0"` on
the shoulder, elbow and wrist_vertical joints. Since the mapping is
`rad = radians(servo - 90)`, that shifts each pitch joint's zero by 90°: the
model curls under its own base at servos `90/90/90/90` and only stands up at
`90/180/180/180`, while a real Braccio stands up at `90/90/90/90`. The same `M`
command therefore drove two different arms.

Dropping those three `rpy` values reproduces the upstream link frames exactly
(checked to 1e-5 m across the workspace — the meshes, collisions and inertias
are carried over untouched) and makes servo 90 mean what it means on hardware.
The upstream joint limits turn out to have been written for this convention
already: `shoulder ±1.309 rad` is exactly the real 15–165° servo travel.

On top of that the model adds a `-90°` yaw at `base_fixed`, so `+x` points at
the paper and the simulation's world frame *is* the arm frame from
`config/workspace.yaml`, plus a `pen_link`/`pen_tip` for the printed grip so
the drawn path can be measured straight off TF.

The launch file also composes the stack itself instead of including
`unoq_braccio_sim`'s `gazebo.launch.py`, because that one hard-codes `gz_args`
(no headless mode) and starts `joint_state_simulator`, which publishes
*commanded* angles onto `/joint_states` in competition with the
`joint_state_broadcaster` publishing the real physics state.

## Gotchas worth knowing

- **Everything runs on sim time.** Gazebo publishes `/clock`; a node left on
  wall time stamps TF in a different domain and tf2 ends up with two
  unconnected trees. The bridge publishes trajectories with a **zero** header
  stamp so the controller starts them on its own clock — stamping them from
  wall time makes the controller judge every point to be in the past and drop
  it, and the arm never moves.
- **The bridge answers `OK` only once the arm has arrived** (`wait_for_motion`).
  Without that the pipeline streams hundreds of points in seconds while the arm
  is still on the first one.
- **`command_mode:=joint_state`** routes through
  `unoq_braccio_driver`'s `joint_trajectory_bridge` instead. That path
  hard-codes 2 s per point, so a 300-point sketch takes ten minutes.
- **Gazebo transport uses multicast** for discovery, which is unreliable on
  some hosts (WSL especially). `export GZ_IP=127.0.0.1` fixes it; the
  end-to-end script does this for you.
