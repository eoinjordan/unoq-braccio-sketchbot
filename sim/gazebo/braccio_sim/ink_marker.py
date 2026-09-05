"""Leave ink on the paper in Gazebo, live, as the simulated pen draws.

``pen_tracker`` answers "what did the arm draw?" *after* the fact, in a PNG.
This node answers it *while* it happens, in the Gazebo window: it follows the
same ``pen_tip`` TF frame with the same pen-down rule, and paints each stroke
onto the paper as a ``gz.msgs.Marker`` LINE_STRIP. Markers have no lifetime, so
the ink stays put - the drawing accumulates on screen exactly the way it would
on real paper.

It is a pure overlay. It publishes nothing to ROS, touches no joint and no TF,
and cannot move ``pen_tip``; if it fails, the drawing and its measurement are
unaffected.

Three things about gz markers drive the shape of this file:

* **Markers live in the GUI process.** ``/marker_array`` is advertised by
  ``gz sim gui``, so it does not exist at all when Gazebo runs headless. The
  launch file keeps this node out of headless runs, and if the service is
  missing anyway the node warns *once* and goes quiet rather than retrying a
  subprocess several times a second for the length of a test run.
* **There are no Python gz bindings on Jazzy** (``gz-msgs``/``gz-transport``
  ship C++ only, and ``python3-gz-transport13`` is not in the ROS repos), so a
  request means shelling out to gz-transport's own service client with a
  text-format protobuf.
* **``/marker_array`` costs ~250 ms per call and the payload is nearly free**
  (2 points and 300 points both measure ~250 ms), while single-marker
  ``/marker`` costs ~1 s. So the whole picture goes out in one call, from a
  coalescing background thread that always sends the newest state and drops
  anything it fell behind on. That self-throttles to a ~4 Hz refresh and can
  never queue up.

Run it alongside the sim (the launch file does this for you when the GUI is
up)::

    ros2 run braccio_sim ink_marker --ros-args -p use_sim_time:=true
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
from typing import List, Optional, Sequence, Tuple

import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener

Point = Tuple[float, float]

# gz-transport's own service client. Calling it directly skips the ~280 ms of
# ruby start-up that `gz service` pays on every single call - which is more
# than the service call itself costs.
_VENDORED_CLIENT = ("/opt/ros/{distro}/opt/gz_transport_vendor/libexec/"
                    "gz/transport{abi}/gz-transport-service")
_TRANSPORT_ABIS = ("13", "14", "12")

# Linux caps a single argv entry at 128 KiB (MAX_ARG_STRLEN), and the request
# goes in as one argument. Stay well under it and split across calls; markers
# are keyed by namespace + id, so several calls paint the same picture as one.
_MAX_REQUEST_BYTES = 100_000


def _resolve_service_client() -> Optional[List[str]]:
    """The argv prefix for a gz service call, or None if gz is not installed."""
    distro = os.environ.get("ROS_DISTRO", "jazzy")
    for abi in _TRANSPORT_ABIS:
        candidate = _VENDORED_CLIENT.format(distro=distro, abi=abi)
        if os.access(candidate, os.X_OK):
            return [candidate]
    fallback = shutil.which("gz")
    return [fallback, "service"] if fallback else None


class InkMarkerNode(Node):
    def __init__(self):
        super().__init__("sketchbot_ink_marker")
        # Frames and the pen-down rule: identical to pen_tracker, deliberately.
        # Two different answers to "is the pen down?" would mean the ink on
        # screen and the measured drawing disagree about what was drawn.
        self.declare_parameter("frame", "pen_tip")
        self.declare_parameter("world_frame", "world")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("pen_down_z_mm", 2.0)
        self.declare_parameter("pen_up_z_mm", 8.0)
        self.declare_parameter("min_step_mm", 0.2)
        # Height of the ink above the world origin. The paper's top face is at
        # z = 0.001; coplanar ink z-fights into a dashed line and +0.05 mm is
        # not enough, while +0.5 mm is clean and still sits below the pen tip
        # at pen_down_z_mm, so the pen never hides its own line.
        self.declare_parameter("ink_z_m", 0.0015)
        self.declare_parameter("ink_rgb", [0.05, 0.05, 0.09])
        self.declare_parameter("marker_ns", "ink")
        self.declare_parameter("service", "/marker_array")
        # "" = auto-detect; set it to run a gz from somewhere else.
        self.declare_parameter("service_bin", "")
        self.declare_parameter("service_timeout_ms", 5000)
        # Wipe ink left over from a previous drawing, so a relaunch does not
        # start on top of the last one.
        self.declare_parameter("clear_on_start", True)
        # The service call is its own throttle at ~250 ms; this only stops a
        # very fast machine from spinning up subprocesses back to back.
        self.declare_parameter("min_publish_interval_s", 0.1)
        # Gazebo's GUI can still be coming up when this node starts, so a first
        # failure is not proof the service is missing.
        self.declare_parameter("startup_grace_s", 20.0)

        self.frame = str(self.get_parameter("frame").value)
        self.world_frame = str(self.get_parameter("world_frame").value)
        self.down_z = float(self.get_parameter("pen_down_z_mm").value)
        self.up_z = float(self.get_parameter("pen_up_z_mm").value)
        self.threshold = (self.down_z + self.up_z) / 2.0
        self.min_step = float(self.get_parameter("min_step_mm").value)
        self.ink_z = float(self.get_parameter("ink_z_m").value)
        self.marker_ns = str(self.get_parameter("marker_ns").value)
        self.service = str(self.get_parameter("service").value)
        self.timeout_ms = int(self.get_parameter("service_timeout_ms").value)
        self.min_interval = float(
            self.get_parameter("min_publish_interval_s").value)
        self.grace = float(self.get_parameter("startup_grace_s").value)
        rgb = [float(v) for v in self.get_parameter("ink_rgb").value]
        self._material = self._material_block(rgb)

        override = str(self.get_parameter("service_bin").value).strip()
        if not override:
            self._client: Optional[List[str]] = _resolve_service_client()
        elif os.path.basename(override) == "gz":
            self._client = [override, "service"]
        else:
            self._client = [override]

        # Strokes are in metres, in the world frame: the URDF's root link *is*
        # the Gazebo origin (the model is spawned at 0,0,0), so a pen_tip
        # translation goes straight into a marker point with no conversion.
        self._lock = threading.Lock()
        self._strokes: List[List[Point]] = []
        self._current: List[Point] = []
        self._last_point: Optional[Point] = None
        # How many finished strokes the GUI has already been told about, so a
        # steady-state publish only carries the stroke being drawn.
        self._sent_strokes = 0
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._enabled = True
        self._warned = False

        self._buffer = Buffer()
        self._listener = TransformListener(self._buffer, self)
        rate = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / max(1.0, rate), self._sample)

        if self._client is None:
            self._disable("no gz service client found (looked for "
                          "gz-transport-service and 'gz' on PATH)")
            return
        self._thread = threading.Thread(target=self._publish_loop,
                                        name="ink-marker", daemon=True)
        self._thread.start()
        self.get_logger().info(
            f"ink marker: painting {self.frame} onto {self.service} "
            f"(ns='{self.marker_ns}', z={self.ink_z:.4f} m) via "
            f"{self._client[0]}")

    # ------------------------------------------------------------- sampling
    def _sample(self) -> None:
        """One TF sample. Mirrors pen_tracker._sample, but keeps metres."""
        if not self._enabled:
            return
        try:
            tf = self._buffer.lookup_transform(
                self.world_frame, self.frame, rclpy.time.Time())
        except Exception:
            # Normal for the first second or two, while TF fills up.
            return

        t = tf.transform.translation
        if t.z * 1000.0 > self.threshold:
            self._flush()
            return

        point = (t.x, t.y)
        if self._last_point is not None and \
                math.dist(point, self._last_point) * 1000.0 < self.min_step:
            return
        self._last_point = point
        with self._lock:
            self._current.append(point)
            # A stroke is only drawable once it has two points to join.
            drawable = len(self._current) >= 2
        if drawable:
            self._dirty.set()

    def _flush(self) -> None:
        """End the stroke in progress, the way pen_tracker does on pen-up."""
        self._last_point = None
        with self._lock:
            if not self._current:
                return
            if len(self._current) >= 2:
                self._strokes.append(self._current)
            self._current = []
        self._dirty.set()

    # ------------------------------------------------------------ publishing
    def _publish_loop(self) -> None:
        started = time.monotonic()
        if bool(self.get_parameter("clear_on_start").value):
            # Doubles as the probe: it is the same service, the same message
            # type and the same client as every later call, so if this works
            # the format is accepted.
            while not self._stop.is_set():
                if self._call([f'marker {{ ns:"{self.marker_ns}" '
                               f'action:DELETE_ALL }}']):
                    break
                if time.monotonic() - started > self.grace:
                    self._disable(
                        f"{self.service} did not answer within "
                        f"{self.grace:.0f}s - is the Gazebo GUI running? "
                        "(markers are a GUI-process facility and do not exist "
                        "headless). Live ink is off; the drawing itself and "
                        "pen_tracker are unaffected.")
                    return
                self._stop.wait(2.0)

        failures = 0
        while not self._stop.is_set():
            self._dirty.wait(0.5)
            if self._stop.is_set():
                return
            self._dirty.clear()
            blocks, finished = self._snapshot()
            if not blocks:
                continue
            if self._call(blocks):
                self._sent_strokes = finished
                failures = 0
            else:
                # Not acknowledged, so those strokes still need sending.
                self._dirty.set()
                failures += 1
                # One timed-out call is not a dead GUI - the render thread is
                # busy under software rendering. Only a run of them is.
                if failures >= 3 and time.monotonic() - started > self.grace:
                    self._disable(
                        f"{self.service} stopped answering (the Gazebo GUI has "
                        "probably been closed); live ink is off.")
                    return
            self._stop.wait(self.min_interval)

    def _snapshot(self) -> Tuple[List[str], int]:
        """Marker blocks for everything the GUI has not been told about yet.

        Finished strokes never change, so only the stroke being drawn is
        re-sent each time. ADD_MODIFY on an existing namespace + id replaces
        the marker in place, which is what makes a growing stroke cheap.
        """
        with self._lock:
            finished = list(self._strokes)
            current = list(self._current)
        blocks: List[str] = []
        for index in range(self._sent_strokes, len(finished)):
            blocks.extend(self._stroke_blocks(index, finished[index]))
        if len(current) >= 2:
            # The in-progress stroke takes the id it will keep once it is
            # flushed, so the final version simply overwrites this one.
            blocks.extend(self._stroke_blocks(len(finished), current))
        return blocks, len(finished)

    def _stroke_blocks(self, index: int, points: Sequence[Point]) -> List[str]:
        """One stroke -> one LINE_STRIP, or several if it is very long."""
        # 128 KiB of argv is roughly 3400 points, so split before then and
        # overlap by a point so the pieces join seamlessly.
        chunk = 2000
        blocks = []
        for part, start in enumerate(range(0, len(points) - 1, chunk - 1)):
            piece = points[start:start + chunk]
            if len(piece) < 2:
                break
            coords = " ".join(
                f"point {{x:{x:.6f} y:{y:.6f} z:{self.ink_z:.6f}}}"
                for x, y in piece)
            # Ids are 1-based: gz reads id 0 as "allocate me one", so a stroke
            # numbered 0 would spawn a fresh marker on every refresh instead of
            # growing in place, and the first stroke alone would leave hundreds
            # of stacked LINE_STRIPs behind. Verified against the live GUI.
            blocks.append(
                f'marker {{ ns:"{self.marker_ns}" id:{index * 1000 + part + 1} '
                f"action:ADD_MODIFY type:LINE_STRIP visibility:GUI "
                f"{self._material} {coords} }}")
        return blocks

    @staticmethod
    def _material_block(rgb: Sequence[float]) -> str:
        # Emissive matched to diffuse with lighting off, so the ink reads as
        # flat graphite whatever the scene lighting is doing.
        r, g, b = (float(v) for v in rgb)
        colour = f"{{r:{r} g:{g} b:{b} a:1}}"
        return (f"material {{ambient {colour} diffuse {colour} "
                f"emissive {colour} lighting: false}}")

    def _call(self, blocks: Sequence[str]) -> bool:
        """Send marker blocks, splitting into several calls if argv demands."""
        if self._client is None:
            return False
        for request in self._batch(blocks):
            command = self._client + [
                "-s", self.service,
                "--reqtype", "gz.msgs.Marker_V",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", str(self.timeout_ms),
                "--req", request,
            ]
            try:
                done = subprocess.run(
                    command, capture_output=True, text=True,
                    # The service's own timeout should fire first; this is the
                    # backstop for a client that hangs instead.
                    timeout=self.timeout_ms / 1000.0 + 5.0,
                    # Inherit the environment: GZ_IP and friends are how the
                    # rest of the stack found each other.
                    env=os.environ.copy())
            except (OSError, subprocess.SubprocessError):
                return False
            if done.returncode != 0 or "true" not in done.stdout.lower():
                return False
        return True

    @staticmethod
    def _batch(blocks: Sequence[str]) -> List[str]:
        """Group marker blocks into requests that fit in one argv entry."""
        requests: List[str] = []
        batch: List[str] = []
        size = 0
        for block in blocks:
            if batch and size + len(block) > _MAX_REQUEST_BYTES:
                requests.append(" ".join(batch))
                batch, size = [], 0
            batch.append(block)
            size += len(block) + 1
        if batch:
            requests.append(" ".join(batch))
        return requests

    # -------------------------------------------------------------- shutdown
    def _disable(self, reason: str) -> None:
        """Give up on markers - once, quietly, and without taking ROS down."""
        self._enabled = False
        if not self._warned:
            self._warned = True
            self.get_logger().warning(f"ink marker disabled: {reason}")

    def destroy_node(self):
        self._stop.set()
        self._dirty.set()
        thread = getattr(self, "_thread", None)
        if thread is not None:
            thread.join(timeout=2.0)
        super().destroy_node()


def main(argv=None) -> None:
    rclpy.init(args=argv)
    node = InkMarkerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
