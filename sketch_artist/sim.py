"""Software arm simulator that speaks the Braccio ``M``/``S`` protocol.

This is a drop-in replacement for the real UNO Q arm agent (see
:class:`sketch_artist.arm_client.ArmClient`). It accepts

    ``M <base> <shoulder> <elbow> <wrist_v> <wrist_rot> <gripper>``  -> ``OK``
    ``S``                                                            -> status line

over TCP, runs forward kinematics on every move to track the pen tip, records
the strokes it would have drawn, and can render the result to a PNG. That makes
the whole capture -> plan -> draw pipeline runnable end to end with **no
hardware**, and is the software-in-the-loop counterpart to the Gazebo model.

Run it as a standalone agent (same interface the real arm exposes)::

    python -m sketch_artist.sim --port 8765 --render output/sim_drawing.png

or embed it (see ``cli.py --sim`` and the tests): start a :class:`SimArmAgent`,
point an :class:`ArmClient` at ``agent.port``, stream moves, then call
``agent.simulator.render(path)``.
"""

from __future__ import annotations

import argparse
import socketserver
import threading
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import config as cfg
from .fk import BraccioForwardKinematics, PenTip

Point = Tuple[float, float]
Polyline = List[Point]


class SketchbotSimulator:
    """Tracks the simulated pen: forward-kinematics + stroke recording."""

    def __init__(self, workspace_cfg: dict):
        self.workspace = workspace_cfg
        self.fk = BraccioForwardKinematics(workspace_cfg)
        pen = workspace_cfg["pen"]
        self.down_z = float(pen["down_z_mm"])
        self.up_z = float(pen["up_z_mm"])
        # The pen is "drawing" when the tip sits at or below the mid height
        # between the configured pen-down and pen-up heights.
        self.pen_threshold = (self.down_z + self.up_z) / 2.0

        self._lock = threading.Lock()
        self.polylines: List[Polyline] = []
        self._current: Polyline = []
        self.last_angles: Optional[Tuple[float, ...]] = None
        self.move_count = 0

    def apply_move(self, angles: Sequence[int]) -> PenTip:
        """Apply one servo-angle command and update the pen trajectory."""
        with self._lock:
            # Float, not int: the M protocol carries fractional degrees, and
            # truncating here would throw away the sub-millimetre precision the
            # drawing depends on (1 deg of base ~= 3 mm at the paper).
            servo = tuple(float(a) for a in angles)
            tip = self.fk.solve(servo)  # type: ignore[arg-type]
            self.last_angles = servo
            self.move_count += 1
            if tip.z_mm <= self.pen_threshold:
                self._current.append((tip.x_mm, tip.y_mm))
            else:
                self._flush()
            return tip

    def _flush(self) -> None:
        if len(self._current) >= 2:
            self.polylines.append(self._current)
        self._current = []

    def finish(self) -> None:
        """Close any open stroke (call before reading ``polylines``/rendering)."""
        with self._lock:
            self._flush()

    @property
    def drawn_points(self) -> int:
        with self._lock:
            return sum(len(p) for p in self.polylines) + len(self._current)

    def status_line(self) -> str:
        a = self.last_angles or (90.0, 90.0, 90.0, 90.0, 90.0, 90.0)
        return "S " + " ".join(f"{float(x):g}" for x in a)

    def render(self, out_path: str, px_per_mm: float = 4.0) -> str:
        """Render the drawn strokes onto the paper box as a PNG."""
        from PIL import Image, ImageDraw

        self.finish()
        paper = self.workspace["paper"]
        ox, oy = float(paper["origin_x_mm"]), float(paper["origin_y_mm"])
        w, h = float(paper["width_mm"]), float(paper["height_mm"])
        W = int(w * px_per_mm) + 20
        H = int(h * px_per_mm) + 20

        def to_px(x_mm: float, y_mm: float) -> Point:
            return (10 + (x_mm - ox) * px_per_mm, 10 + (y_mm - oy) * px_per_mm)

        img = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([to_px(ox, oy), to_px(ox + w, oy + h)], outline="#cccccc")
        for line in self.polylines:
            if len(line) >= 2:
                draw.line([to_px(x, y) for x, y in line],
                          fill="#0b1221", width=2, joint="curve")

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        sim: SketchbotSimulator = self.server.simulator  # type: ignore[attr-defined]
        for raw in self.rfile:
            line = raw.decode("ascii", "replace").strip()
            if not line:
                continue
            cmd = line[0].upper()
            if cmd == "M":
                parts = line.split()[1:7]
                try:
                    angles = tuple(float(p) for p in parts)
                    if len(angles) != 6:
                        raise ValueError("expected 6 joint angles")
                except ValueError:
                    self.wfile.write(b"ERR bad move\n")
                    continue
                sim.apply_move(angles)
                self.wfile.write(b"OK\n")
            elif cmd == "S":
                self.wfile.write((sim.status_line() + "\n").encode("ascii"))
            elif cmd in ("Q", "X"):
                break
            else:
                self.wfile.write(b"ERR unknown\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr: Tuple[str, int], simulator: SketchbotSimulator):
        super().__init__(addr, _Handler)
        self.simulator = simulator


class SimArmAgent:
    """A running simulator that serves the ``M``/``S`` protocol on a TCP port.

    Pass ``port=0`` for an ephemeral port (read it back from :attr:`port`),
    which the tests and ``cli.py --sim`` use to avoid clashing with a real arm.
    """

    def __init__(self, workspace_cfg: dict, host: str = "127.0.0.1", port: int = 0):
        self.simulator = SketchbotSimulator(workspace_cfg)
        self._server = _Server((host, port), self.simulator)
        self._thread: Optional[threading.Thread] = None

    @property
    def host(self) -> str:
        return self._server.server_address[0]

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> "SimArmAgent":
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="sim-arm-agent", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "SimArmAgent":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Braccio software arm simulator (M/S protocol, no hardware).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    parser.add_argument("--render", default="output/sim_drawing.png",
                        help="PNG to write with what the pen drew, on exit.")
    args = parser.parse_args(argv)

    conf = cfg.load_all()
    agent = SimArmAgent(conf["workspace"], host=args.host, port=args.port).start()
    print(f"Sketchbot simulator (M/S) on {agent.host}:{agent.port}  "
          f"(Ctrl-C to stop)")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()
        out = str(cfg.resolve_path(args.render))
        agent.simulator.render(out)
        print(f"\nWrote simulated drawing: {out} "
              f"({agent.simulator.drawn_points} points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
