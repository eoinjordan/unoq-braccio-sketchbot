"""ROS 2 bridge: the sketchbot ``M``/``S`` arm protocol -> the ``unoq_braccio_sim``
Gazebo model.

The sketchbot (and the real UNO Q agent) speak a tiny TCP protocol:

    ``M <base> <shoulder> <elbow> <wrist_v> <wrist_rot> <gripper>``  -> ``OK``
    ``S``                                                            -> status line

This node is the *server* side for simulation: it accepts those moves on a TCP
port and republishes each as a ``sensor_msgs/JointState`` (servo degrees) on
``/braccio/joint_command`` -- exactly the topic the ``unoq_braccio_driver``
nodes already consume. Their ``joint_trajectory_bridge`` then converts servo
degrees to the controller's radians and drives the Braccio in Gazebo, so the
sketchbot pipeline draws into the *real* arm model unchanged::

    sketch_artist.cli --M/S:8765--> braccio_bridge --/braccio/joint_command-->
        unoq_braccio_driver/joint_trajectory_bridge --> /arm_controller --> Gazebo

One source of truth: the servo->radian mapping and joint names live in
``unoq_braccio_driver`` (see the unoq-braccio repo), not here.
"""

from __future__ import annotations

import socketserver
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

# Joint order of the M command == unoq_braccio_driver.braccio_model.JOINT_NAMES.
JOINT_NAMES = [
    "base",
    "shoulder",
    "elbow",
    "wrist_vertical",
    "wrist_rotation",
    "gripper",
]


class BraccioBridge(Node):
    def __init__(self):
        super().__init__("sketchbot_ms_bridge")
        self.declare_parameter("port", 8765)
        self.port = int(self.get_parameter("port").value)
        self.last = [90.0, 90.0, 90.0, 90.0, 90.0, 90.0]

        self._pub = self.create_publisher(JointState, "/braccio/joint_command", 10)
        self._server = _MSServer(("127.0.0.1", self.port), self)
        threading.Thread(target=self._server.serve_forever,
                         name="ms-bridge", daemon=True).start()
        self.get_logger().info(
            f"Sketchbot M/S bridge on 127.0.0.1:{self.port} -> /braccio/joint_command")

    def publish_servo(self, angles) -> None:
        self.last = [float(a) for a in angles]
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(JOINT_NAMES)
        msg.position = self.last
        self._pub.publish(msg)

    def status_line(self) -> str:
        return "S " + " ".join(str(int(a)) for a in self.last)

    def destroy_node(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            super().destroy_node()


class _MSHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        bridge: BraccioBridge = self.server.bridge  # type: ignore[attr-defined]
        for raw in self.rfile:
            line = raw.decode("ascii", "replace").strip()
            if not line:
                continue
            cmd = line[0].upper()
            if cmd == "M":
                parts = line.split()[1:7]
                try:
                    angles = tuple(int(float(p)) for p in parts)
                    if len(angles) != 6:
                        raise ValueError
                except ValueError:
                    self.wfile.write(b"ERR bad move\n")
                    continue
                bridge.publish_servo(angles)
                self.wfile.write(b"OK\n")
            elif cmd == "S":
                self.wfile.write((bridge.status_line() + "\n").encode("ascii"))
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
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
