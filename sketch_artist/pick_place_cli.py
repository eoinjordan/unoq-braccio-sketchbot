"""Colour pick and place from the command line.

Nothing is sent to the arm unless ``--live`` is given. Start with these, in
this order (docs/pick-place.md has the full first-run procedure):

    python -m sketch_artist.pick_place_cli --source sim          # all software
    python -m sketch_artist.pick_place_cli --listen              # camera only
    python -m sketch_artist.pick_place_cli                       # dry-run
    python -m sketch_artist.pick_place_cli --live --slow         # moves the arm

Other uses:

    --replay FILE        run the dry-run against a recorded detection log
    --record FILE        save the camera's lines while running or listening
    --trials 200         simulated success rate over random layouts
    --monitor-port 7110  a page with live detections, state and a stop button

The monitor page is served by this program, not by the Studio. Do not run
this while a Studio session is armed: the two do not share an interlock.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import config as cfg
from .arm_client import ArmClient
from .detections import (DEFAULT_BAUD, ReplayDetectionSource,
                         SerialDetectionSource)
from .pick_place import DEFAULTS, PickPlaceController, load_settings

MONITOR_PAGE = cfg.REPO_ROOT / "web" / "static" / "pickplace.html"

FIRST_RUN = """\
This will move the arm. Before going on:
  1. The dry-run (no --live) has been run and its plan read.
  2. A run with --live has been made with the servo power switched OFF.
  3. This run uses --slow, and a hand is on the servo power switch.
  4. The desk is clear of everything but the bricks and the bin, nobody is
     within reach of the arm, and no Studio session is armed.
The stop button and Ctrl-C stop commands being sent. They do not cut servo
power. Only the power switch does."""


class _MonitorHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/pickplace", "/index.html"):
            return self._send(200, MONITOR_PAGE.read_bytes(),
                              "text/html; charset=utf-8")
        if path == "/api/pickplace/state":
            return self._json(200, self.server.controller.snapshot())
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        origin = self.headers.get("Origin")
        if (origin and urlsplit(origin).netloc != self.headers.get("Host")) \
                or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._json(403, {"error": "Cross-origin control is not allowed"})
        if path == "/api/pickplace/stop":
            self.server.controller.stop()
            return self._json(200, {"ok": True, "stop_requested": True})
        self._json(404, {"error": "Unknown action"})


def start_monitor(controller: PickPlaceController, port: int,
                  bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Serve the monitor page for a controller on a background thread."""
    server = ThreadingHTTPServer((bind, port), _MonitorHandler)
    server.daemon_threads = True
    server.controller = controller
    threading.Thread(target=server.serve_forever, name="pickplace-monitor",
                     daemon=True).start()
    return server


def _overrides(args) -> dict:
    overrides: dict = {}
    if args.colours:
        overrides["colours"] = [c.strip().lower() for c in args.colours.split(",")
                                if c.strip()]
    if args.confidence is not None:
        overrides["confidence"] = args.confidence
    if args.max_picks is not None:
        overrides["max_picks"] = args.max_picks
    if args.max_attempts is not None:
        overrides["max_attempts"] = args.max_attempts
    if args.strict_order:
        overrides["strict_order"] = True
    return overrides


def _listen(source, seconds: float) -> int:
    """Print what the camera reports. Moves nothing."""
    print("Listening to the camera. Ctrl-C to stop.")
    end = source.now() + seconds if seconds else None
    frames = 0
    try:
        while end is None or source.now() < end:
            frame = source.read(1.0)
            if frame is None:
                print("  (no detection line in the last second)")
                continue
            frames += 1
            shown = ", ".join(f"{d.label} x={d.x:.2f} y={d.y:.2f} c={d.confidence:.2f}"
                              for d in frame.detections) or "nothing"
            took = "" if frame.inference_ms is None else f"  [{frame.inference_ms:g} ms]"
            print(f"  {shown}{took}")
    except KeyboardInterrupt:
        pass
    print(f"{frames} frames.")
    return 0


def _trials(args, settings: dict, workspace: dict) -> int:
    from .sim_camera import run_trials

    report = run_trials(args.trials, seed=args.seed, workspace=workspace,
                        settings=settings, count=args.bricks,
                        calibration_error=args.calibration_error)
    results = report.pop("results")
    print(f"SIMULATED: {report['layouts_cleared']} of {report['trials']} random "
          f"layouts cleared ({100 * report['success_rate']:.1f} percent); "
          f"{report['bricks_binned']} of {report['bricks']} bricks in the bin "
          f"({100 * report['brick_rate']:.1f} percent).")
    print(f"  seed {report['seed']}, {args.bricks} bricks per layout, "
          f"calibration error scale {args.calibration_error:g}, mean run "
          f"{report['mean_elapsed_s']:.0f} s of simulated time")
    print(f"  lowest point of the claws over all runs: "
          f"{report['lowest_mm']:.1f} mm above the simulated desk")
    print(f"  controller events: {report['controller_events'] or 'none'}")
    print(f"  layouts not cleared, by cause: {report['failed_layouts'] or 'none'}")
    if args.verbose:
        for result in results:
            if not result.success:
                print(f"    seed {result.seed}: {result.binned}/{result.bricks} "
                      f"{result.state} {result.reasons} {result.world_events}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Colour pick and place with the gripper-top camera. "
                    "Dry-run unless --live is given.")
    parser.add_argument("--source", choices=("serial", "replay", "sim"),
                        default="serial", help="Where detections come from.")
    parser.add_argument("--port", default="auto",
                        help="Camera serial port; auto finds USB vendor 303A.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--replay", metavar="FILE",
                        help="Recorded detection log (implies --source replay).")
    parser.add_argument("--record", metavar="FILE",
                        help="Append the camera's detection lines to this file.")
    parser.add_argument("--live", action="store_true",
                        help="Send moves to the arm agent. Serial source only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan and log without sending motion (the default).")
    parser.add_argument("--yes", action="store_true",
                        help="With --live: skip the typed confirmation.")
    parser.add_argument("--slow", action="store_true",
                        help="Smaller steps and longer pauses.")
    parser.add_argument("--listen", action="store_true",
                        help="Only print what the camera reports.")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="With --listen: stop after this long.")
    parser.add_argument("--host", default="127.0.0.1", help="Arm agent host.")
    parser.add_argument("--arm-port", type=int, default=8765, help="Arm agent port.")
    parser.add_argument("--colours", help="Comma-separated, in pick order.")
    parser.add_argument("--confidence", type=float)
    parser.add_argument("--max-picks", type=int)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--strict-order", action="store_true")
    parser.add_argument("--monitor-port", type=int, default=0,
                        help="Serve the monitor page on this port (0 = off).")
    parser.add_argument("--monitor-bind", default="127.0.0.1")
    parser.add_argument("--trials", type=int, default=0,
                        help="Run this many simulated random layouts and report.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bricks", type=int, default=3,
                        help="Bricks per simulated layout.")
    parser.add_argument("--calibration-error", type=float, default=1.0,
                        help="Scale of the simulated rig's calibration error.")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    if args.trials or args.listen:
        level = logging.WARNING     # hundreds of runs: print the totals only
    logging.basicConfig(level=level, format="%(message)s")
    if args.replay:
        args.source = "replay"
    if args.live and args.dry_run:
        print("Choose one of --live and --dry-run.", file=sys.stderr)
        return 2
    if args.live and args.source != "serial":
        print("--live needs the real camera (--source serial).", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.config_dir, _overrides(args))
    except (ValueError, KeyError, TypeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    workspace = cfg.load_all(args.config_dir)["workspace"]

    if args.trials:
        return _trials(args, settings, workspace)

    arm = None
    world = None
    try:
        if args.source == "sim":
            from .sim_camera import (PickPlaceWorld, SimCameraSource,
                                     random_layout)
            bricks, parts_bin = random_layout(random.Random(args.seed), args.bricks,
                                              settings["colours"])
            parts_bin.rim_height_mm = float(settings["bin"]["rim_height_mm"])
            world = PickPlaceWorld(workspace, settings, bricks, parts_bin,
                                   seed=args.seed)
            record = [] if args.record else None
            source = SimCameraSource(world, record=record)
            print("Software arm and simulated camera. No hardware is used.")
        elif args.source == "replay":
            if not args.replay:
                print("--source replay needs --replay FILE.", file=sys.stderr)
                return 2
            source = ReplayDetectionSource(args.replay)
        else:
            source = SerialDetectionSource(args.port, args.baud, args.record).open()
            print(f"Camera on {source.port}.")
    except (OSError, RuntimeError) as exc:
        print(f"Cannot open the detection source: {exc}", file=sys.stderr)
        return 1

    with source:
        if args.listen:
            return _listen(source, args.seconds)
        if args.live:
            print(FIRST_RUN)
            if not args.yes and input('Type "move" to go on: ').strip() != "move":
                print("Not started.")
                return 1
            arm = ArmClient(args.host, args.arm_port, timeout=3.0)
            try:
                arm.connect()
            except OSError as exc:
                print(f"Cannot reach the arm agent: {exc}", file=sys.stderr)
                return 1
        if arm is not None and settings["arm"]["reach_behind"]:
            from .mirrored_arm import MirroredArm
            arm = MirroredArm(arm)
        controller = PickPlaceController(
            workspace, settings, source, arm=world if world is not None else arm,
            dry_run=not args.live and world is None, slow=args.slow)
        try:
            controller.check_plan()
        except ValueError as exc:
            print(f"Cannot run with this configuration: {exc}", file=sys.stderr)
            return 2
        server = None
        if args.monitor_port:
            server = start_monitor(controller, args.monitor_port, args.monitor_bind)
            print(f"Monitor on http://{args.monitor_bind}:{server.server_port}/")
        try:
            summary = controller.run()
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if arm is not None:
                arm.close()
        if world is not None:
            summary["simulated"] = True
            summary["simulated_bricks"] = world.counts()
            if args.record:
                Path(args.record).write_text("\n".join(source.record) + "\n",
                                             encoding="ascii")
        print(json.dumps(summary, indent=2))
        if args.source == "replay" or (not args.live and world is None):
            print("Dry-run: the arm was not moved. With a camera that does not "
                  "move, the approach cannot converge; a timeout here is expected.")
        return 0 if summary["state"] == "done" else 1


__all__ = ["DEFAULTS", "build_parser", "main", "start_monitor"]

if __name__ == "__main__":
    raise SystemExit(main())
