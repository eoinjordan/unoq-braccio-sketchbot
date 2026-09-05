"""ROS 2 bridge: the sketchbot ``M``/``S`` arm protocol -> the Braccio in Gazebo.

The sketchbot (and the real UNO Q agent) speak a tiny TCP protocol:

    ``M <base> <shoulder> <elbow> <wrist_v> <wrist_rot> <gripper>``  -> ``OK``
    ``S``                                                            -> status line

This node is the *server* side for simulation, so the unchanged sketchbot
pipeline draws into the simulated arm::

    sketch_artist.cli --M/S:8765--> braccio_bridge --/arm_controller--> Gazebo

Three things it does that a naive republisher does not, and that the drawing
needs:

* **It paces the pipeline.** ``OK`` is sent once the arm has actually reached
  the commanded pose (``wait_for_motion``), instead of the instant the command
  is queued. Without that the sketchbot streams hundreds of points in seconds
  while the arm is still on the first one, and the pen cuts corners across the
  whole drawing.
* **It commands at drawing speed.** Each move becomes a ``JointTrajectory``
  with ``move_time`` (default 0.25 s) time_from_start. Going through
  ``unoq_braccio_driver``'s republisher instead hard-codes 2 s per point, which
  turns a 300-point sketch into a ten-minute smear; set
  ``command_mode:=joint_state`` to use that path anyway.
* **It reports what the arm did**, not what it was told: ``S`` answers from
  ``/joint_states``, so calibration and pen-tip checks see the real pose.

Servo degrees are converted with ``unoq_braccio_driver``'s own mapping
(``rad = radians(servo - 90)``), which is correct for the model in
``sim/gazebo/urdf/braccio_sketchbot.urdf.xacro``; see the note at the top of
that file for why the upstream model needs a corrected joint zero.
"""

from __future__ import annotations

import math
import socketserver
import threading
import time
from typing import List, Optional, Sequence

import rclpy
from builtin_interfaces.msg import Duration
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

try:  # One source of truth for joint names, limits and the servo mapping.
    from unoq_braccio_driver.braccio_model import JOINT_NAMES, clamp_degrees
    from unoq_braccio_driver.joint_trajectory_bridge import (
        servo_degrees_to_controller_position,
    )
except ImportError:  # pragma: no cover - lets the file import without ROS deps
    JOINT_NAMES = ["base", "shoulder", "elbow", "wrist_vertical",
                   "wrist_rotation", "gripper"]
    _LIMITS = {"base": (0, 180), "shoulder": (15, 165), "elbow": (0, 180),
               "wrist_vertical": (0, 180), "wrist_rotation": (0, 180),
               "gripper": (10, 110)}

    def clamp_degrees(name: str, value: float) -> int:
        lo, hi = _LIMITS[name]
        # Keep fractions: the sketchbot sends tenths of a degree.
        return max(lo, min(hi, float(value)))

    def servo_degrees_to_controller_position(name: str, value: float) -> float:
        if name == "gripper":
            return 0.1750 + max(0.0, min(1.0, (float(value) - 10.0) / 100.0)) \
                * (1.2741 - 0.1750)
        return math.radians(float(value) - 90.0)


def controller_position_to_servo_degrees(name: str, position: float) -> float:
    """Inverse of the driver's mapping, for reporting measured joint states."""
    if name == "gripper":
        span = 1.2741 - 0.1750
        return 10.0 + max(0.0, min(1.0, (position - 0.1750) / span)) * 100.0
    return math.degrees(position) + 90.0


class BraccioBridge(Node):
    def __init__(self):
        super().__init__("sketchbot_ms_bridge")
        self.declare_parameter("host", "127.0.0.1")
        self.declare_parameter("port", 8765)
        self.declare_parameter("command_mode", "trajectory")
        self.declare_parameter("move_time", 0.25)
        self.declare_parameter("wait_for_motion", True)
        # 0.75 deg is ~2 mm at the pen tip with a 174 mm grip. Looser than
        # that and a travel move still reads as a stroke, because the pen
        # only lifts a few mm between strokes.
        # 0.15 deg is ~0.45 mm at the paper radius. The old 0.75 deg was
        # ~2.3 mm -- on a 40 mm sheet the bridge would answer OK while the pen
        # was still a twentieth of the drawing away from the commanded point,
        # so the arm chased a moving target and rounded every corner off.
        self.declare_parameter("position_tolerance_deg", 0.15)
        self.declare_parameter("move_timeout_s", 4.0)

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        self.command_mode = str(self.get_parameter("command_mode").value)
        self.move_time = float(self.get_parameter("move_time").value)
        self.wait_for_motion = bool(self.get_parameter("wait_for_motion").value)
        self.tolerance = float(self.get_parameter("position_tolerance_deg").value)
        self.move_timeout = float(self.get_parameter("move_timeout_s").value)

        self.target: List[float] = [90.0, 90.0, 90.0, 90.0, 90.0, 90.0]
        self._measured: Optional[List[float]] = None
        self._measured_lock = threading.Lock()
        self.moves = 0
        self.timeouts = 0
        self._started = time.monotonic()

        group = ReentrantCallbackGroup()
        self._traj_pub = self.create_publisher(
            JointTrajectory, "/arm_controller/joint_trajectory", 10)
        self._state_pub = self.create_publisher(
            JointState, "/braccio/joint_command", 10)
        self.create_subscription(JointState, "/joint_states",
                                 self._on_joint_states, 10, callback_group=group)

        self._server = _MSServer((self.host, self.port), self)
        threading.Thread(target=self._server.serve_forever,
                         name="ms-bridge", daemon=True).start()
        self.get_logger().info(
            f"Sketchbot M/S bridge on {self.host}:{self.port} "
            f"(mode={self.command_mode}, move_time={self.move_time}s, "
            f"wait_for_motion={self.wait_for_motion})")

    # ------------------------------------------------------------- ROS side
    def _on_joint_states(self, msg: JointState) -> None:
        by_name = dict(zip(msg.name, msg.position))
        if not all(name in by_name for name in JOINT_NAMES):
            return
        degrees = [controller_position_to_servo_degrees(name, by_name[name])
                   for name in JOINT_NAMES]
        with self._measured_lock:
            self._measured = degrees

    def measured(self) -> Optional[List[float]]:
        with self._measured_lock:
            return None if self._measured is None else list(self._measured)

    def publish_servo(self, angles: Sequence[float]) -> None:
        self.target = [float(clamp_degrees(name, value))
                       for name, value in zip(JOINT_NAMES, angles)]
        self.moves += 1

        if self.command_mode == "joint_state":
            # Hand off to unoq_braccio_driver's joint_trajectory_bridge.
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = list(JOINT_NAMES)
            msg.position = list(self.target)
            self._state_pub.publish(msg)
            return

        traj = JointTrajectory()
        # Leave the stamp at zero: that tells JointTrajectoryController to start
        # the trajectory now, on ITS clock. Stamping it ourselves means the
        # controller compares a wall-clock time against Gazebo's simulated
        # clock, decides every point is in the past, and drops the trajectory -
        # the arm then never moves at all.
        traj.joint_names = list(JOINT_NAMES)
        point = JointTrajectoryPoint()
        point.positions = [servo_degrees_to_controller_position(name, value)
                           for name, value in zip(JOINT_NAMES, self.target)]
        seconds = int(self.move_time)
        point.time_from_start = Duration(
            sec=seconds, nanosec=int((self.move_time - seconds) * 1e9))
        traj.points = [point]
        self._traj_pub.publish(traj)

    def await_move(self) -> bool:
        """Block until the arm is within tolerance of the target, or time out."""
        if not self.wait_for_motion:
            return True
        deadline = time.monotonic() + self.move_timeout
        while time.monotonic() < deadline:
            measured = self.measured()
            if measured is not None:
                worst = max(abs(m - t) for m, t in zip(measured, self.target))
                if worst <= self.tolerance:
                    return True
            time.sleep(0.005)
        self.timeouts += 1
        return False

    def status_line(self) -> str:
        """``S`` reply: measured servo degrees, falling back to the target."""
        measured = self.measured()
        source = measured if measured is not None else self.target
        return "S " + " ".join(f"{float(value):g}" for value in source)

    def stats_line(self) -> str:
        uptime_ms = int((time.monotonic() - self._started) * 1000)
        target = ",".join(str(int(value)) for value in self.target)
        return (f"STAT uptime_ms={uptime_ms} move_count={self.moves} "
                f"timeouts={self.timeouts} target={target}")

    def destroy_node(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            super().destroy_node()


# ------------------------------------------------------------------ TCP side
class _MSHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        bridge: BraccioBridge = self.server.bridge  # type: ignore[attr-defined]
        for raw in self.rfile:
            line = raw.decode("ascii", "replace").strip()
            if not line:
                continue
            cmd = line[0].upper()
            if cmd == "M":
                parts = line.split()[1:]
                try:
                    if len(parts) != 6:
                        raise ValueError("expected 6 joint angles")
                    angles = [float(part) for part in parts]
                except ValueError:
                    self.wfile.write(b"ERR bad move\n")
                    continue
                bridge.publish_servo(angles)
                reached = bridge.await_move()
                self.wfile.write(b"OK\n" if reached else b"OK slow\n")
            elif cmd == "S":
                self.wfile.write((bridge.status_line() + "\n").encode("ascii"))
            elif cmd == "T":
                self.wfile.write((bridge.stats_line() + "\n").encode("ascii"))
            elif cmd in ("Q", "X"):
                break
            else:
                self.wfile.write(b"ERR unknown\n")


class _MSServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, bridge: BraccioBridge):
        super().__init__(addr, _MSHandler)
        self.bridge = bridge


def main(argv=None) -> None:
    rclpy.init(args=argv)
    node = BraccioBridge()
    # A multi-threaded executor keeps /joint_states flowing while a move blocks.
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
