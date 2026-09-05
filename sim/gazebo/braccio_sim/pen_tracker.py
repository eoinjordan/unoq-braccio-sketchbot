"""Record what the Braccio actually drew in Gazebo, from the simulated pen tip.

The bridge tells you the arm accepted a command; this tells you where the pen
really went. It follows the ``pen_tip`` TF frame, which the sketchbot URDF
attaches to the wrist, splits the path into strokes wherever the tip lifts above
the pen-down threshold, and writes:

* ``<out>.png``  - the drawing, on the paper rectangle, same framing as the
  software simulator's render, so the two can be compared side by side;
* ``<out>.csv``  - ``t,x_mm,y_mm,z_mm,pen_down`` for every sample.

Run it alongside the sim and stop it with Ctrl-C (or the ``--duration`` /
``--idle-timeout`` limits) to write the files:

    ros2 run braccio_sim pen_tracker --ros-args -p out:=output/gazebo_drawing.png
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path
from typing import List, Optional, Tuple

import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener

Point = Tuple[float, float]


class PenTracker(Node):
    def __init__(self):
        super().__init__("sketchbot_pen_tracker")
        self.declare_parameter("out", "output/gazebo_drawing.png")
        self.declare_parameter("frame", "pen_tip")
        self.declare_parameter("world_frame", "world")
        self.declare_parameter("rate_hz", 50.0)
        # Paper rectangle, millimetres in the arm frame (config/workspace.yaml).
        self.declare_parameter("paper_origin_x_mm", 145.0)
        self.declare_parameter("paper_origin_y_mm", -35.0)
        self.declare_parameter("paper_width_mm", 35.0)
        self.declare_parameter("paper_height_mm", 35.0)
        self.declare_parameter("pen_down_z_mm", 2.0)
        self.declare_parameter("pen_up_z_mm", 8.0)
        # Stop on their own so a scripted run needs no signal handling.
        self.declare_parameter("duration_s", 0.0)
        self.declare_parameter("idle_timeout_s", 0.0)
        # Ignore samples closer together than this, so a stationary pen does not
        # pile up thousands of identical points.
        self.declare_parameter("min_step_mm", 0.2)

        self.out = str(self.get_parameter("out").value)
        self.frame = str(self.get_parameter("frame").value)
        self.world_frame = str(self.get_parameter("world_frame").value)
        self.down_z = float(self.get_parameter("pen_down_z_mm").value)
        self.up_z = float(self.get_parameter("pen_up_z_mm").value)
        self.threshold = (self.down_z + self.up_z) / 2.0
        self.min_step = float(self.get_parameter("min_step_mm").value)
        self.duration = float(self.get_parameter("duration_s").value)
        self.idle_timeout = float(self.get_parameter("idle_timeout_s").value)

        self.polylines: List[List[Point]] = []
        self._current: List[Point] = []
        self.samples: List[Tuple[float, float, float, float, bool]] = []
        self._last_point: Optional[Point] = None
        self._last_tip: Optional[Tuple[float, float, float]] = None
        self._started = time.monotonic()
        self._last_motion = self._started
        self.finished = False

        self._buffer = Buffer()
        self._listener = TransformListener(self._buffer, self)
        rate = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / max(1.0, rate), self._sample)

    # ------------------------------------------------------------- sampling
    def _sample(self) -> None:
        if self.finished:
            return
        now = time.monotonic()
        if self.duration and now - self._started >= self.duration:
            self.finish()
            return
        # Only start the idle countdown once the pen has actually drawn
        # something: the arm spends its first seconds travelling to the paper,
        # and timing out then would write an empty log.
        if self.idle_timeout and self.polylines and \
                now - self._last_motion >= self.idle_timeout:
            self.finish()
            return
        try:
            tf = self._buffer.lookup_transform(
                self.world_frame, self.frame, rclpy.time.Time())
        except Exception:
            return

        t = tf.transform.translation
        x_mm, y_mm, z_mm = t.x * 1000.0, t.y * 1000.0, t.z * 1000.0
        pen_down = z_mm <= self.threshold
        self.samples.append((now - self._started, x_mm, y_mm, z_mm, pen_down))

        # "Idle" means the arm has stopped moving at all, not just that no new
        # pen-down point was recorded: long pen-up travel between strokes would
        # otherwise look like the end of the drawing and cut the log short.
        tip = (x_mm, y_mm, z_mm)
        if self._last_tip is None or math.dist(tip, self._last_tip) > self.min_step:
            self._last_tip = tip
            self._last_motion = now

        if not pen_down:
            self._flush()
            self._last_point = None
            return

        point = (x_mm, y_mm)
        if self._last_point is not None and \
                math.dist(point, self._last_point) < self.min_step:
            return
        self._last_point = point
        self._last_motion = now
        self._current.append(point)

    def _flush(self) -> None:
        if len(self._current) >= 2:
            self.polylines.append(self._current)
        self._current = []

    @property
    def drawn_points(self) -> int:
        return sum(len(line) for line in self.polylines) + len(self._current)

    # -------------------------------------------------------------- output
    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self._flush()
        out = Path(self.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._write_csv(out.with_suffix(".csv"))
        self._render(out)
        self.get_logger().info(
            f"pen tracker: {len(self.polylines)} stroke(s), "
            f"{self.drawn_points} point(s) -> {out}")

    def _write_csv(self, path: Path) -> None:
        with path.open("w", newline="", encoding="ascii") as handle:
            writer = csv.writer(handle)
            writer.writerow(["t_s", "x_mm", "y_mm", "z_mm", "pen_down"])
            for row in self.samples:
                writer.writerow([f"{row[0]:.3f}", f"{row[1]:.3f}",
                                 f"{row[2]:.3f}", f"{row[3]:.3f}",
                                 int(row[4])])

    def _render(self, path: Path, px_per_mm: float = 8.0) -> None:
        from PIL import Image, ImageDraw

        ox = float(self.get_parameter("paper_origin_x_mm").value)
        oy = float(self.get_parameter("paper_origin_y_mm").value)
        w = float(self.get_parameter("paper_width_mm").value)
        h = float(self.get_parameter("paper_height_mm").value)
        width = int(w * px_per_mm) + 20
        height = int(h * px_per_mm) + 20

        def to_px(x_mm: float, y_mm: float) -> Point:
            return (10 + (x_mm - ox) * px_per_mm, 10 + (y_mm - oy) * px_per_mm)

        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([to_px(ox, oy), to_px(ox + w, oy + h)], outline="#cccccc")
        for line in self.polylines:
            if len(line) >= 2:
                draw.line([to_px(x, y) for x, y in line],
                          fill="#0b1221", width=2, joint="curve")
        img.save(path)


def main(argv=None) -> None:
    rclpy.init(args=argv)
    node = PenTracker()
    try:
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.finish()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
