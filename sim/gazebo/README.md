# Braccio Sketchbot — Gazebo simulation

Draw with the sketchbot into a **full 3D Gazebo** Braccio, using the real
mesh model from the companion [`unoq-braccio`](https://github.com/edgeimpulse/unoq-braccio)
repo (`unoq_braccio_sim`). The bridge here speaks the same `M`/`S` TCP protocol
as the real UNO Q arm agent, so the sketchbot pipeline drives the simulated arm
unchanged.

```
sketch_artist.cli ──M/S TCP:8765──► braccio_bridge ──/braccio/joint_command──►
    unoq_braccio_driver/joint_trajectory_bridge ──► /arm_controller ──► Gazebo (Braccio)
```

> **Just want a picture / a quick check?** Two lighter options need no ROS:
> - `python -m sketch_artist.cli --sim` — the built-in software simulator.
> - `python -m sim.render_arm` — renders the **same** `unoq_braccio_sim` STL
>   model drawing the caricature to `docs/images/gazebo_caricature.png`
>   (headless; see the repo README).

## Requirements

- ROS 2 **Jazzy** (or Humble) + **Gazebo (gz)** with `ros_gz_sim`,
  `gz_ros2_control`, `ros2_control`, `ros2_controllers`.
- The **`unoq-braccio`** repo checked out (it provides the Braccio model
  `unoq_braccio_sim` and the `unoq_braccio_driver` bridges this builds on).

## Build

Put both packages in one ROS 2 workspace and build:

```bash
mkdir -p ~/braccio_ws/src && cd ~/braccio_ws/src
ln -s /path/to/unoq-braccio/ros2_ws/src/unoq_braccio_sim .
ln -s /path/to/unoq-braccio/ros2_ws/src/unoq_braccio_driver .
ln -s /path/to/unoq-braccio-sketchbot/sim/gazebo braccio_sim
cd ~/braccio_ws
colcon build
source install/setup.bash
```

## Run

```bash
# 1. Gazebo + the Braccio model + controllers + driver bridges + the M/S bridge:
ros2 launch braccio_sim sketchbot_gazebo.launch.py        # M/S on :8765

# 2. From the sketchbot repo, draw against it (host defaults to 127.0.0.1:8765,
#    exactly like the real arm):
cd /path/to/unoq-braccio-sketchbot
.venv/bin/python -m sketch_artist.cli \
    --image examples/sample_face_eoin.png --style none
```

The Braccio traces the caricature in Gazebo; `output/preview.png` and a branded
gallery card are written just as on real hardware.

## How it fits together

- **Model + physics** come from `unoq_braccio_sim` (URDF/xacro + Braccio STL
  meshes + `ros2_control`).
- **Servo → joint** conversion and the `JointTrajectoryController` wiring come
  from `unoq_braccio_driver` (`joint_trajectory_bridge`, one source of truth).
- **This package** adds only [`braccio_bridge.py`](braccio_sim/braccio_bridge.py):
  the `M`/`S` TCP server that republishes each move as a
  `sensor_msgs/JointState` on `/braccio/joint_command`.
- **Joint order** (`base, shoulder, elbow, wrist_vertical, wrist_rotation,
  gripper`) matches the `M` command and the controller.
