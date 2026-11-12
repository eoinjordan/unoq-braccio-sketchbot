"""Pick and place as a service: comes up at boot, waits, runs on Start.

``pick_place_cli`` runs one pick-and-place session and exits. This wraps
the same controller in a process that stays up:

    waiting   the arm agent or the camera is missing; says which
    ready     both are there and the arm is parked; waiting for Start
    running   a session is in progress (the controller's own states show)
    done / stopped / fault   how the last session ended; Start runs another

It serves the monitor page with Start, Stop and Park buttons, on the same
port and paths as the CLI's monitor so the page works with either.

Nothing moves until Start is pressed, unless ``--autostart`` is given, and
then only once, the first time everything is ready after the service
starts. Start is refused while the arm agent or camera is missing or the
arm is not parked. Park is a checked, stepped move back to the rest pose
and is the only motion offered outside a session.

Under systemd the unit is Type=notify with a watchdog: the service tells
systemd it is alive from its main loop, so a hung process is restarted. A
restarted service comes back in ``waiting``/``ready``; it never resumes a
session on its own. The detection watchdog inside the controller is
separate and stops a session when the camera goes quiet.

This process must be the only thing driving the arm. The systemd unit
conflicts with the Studio unit for that reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from . import config as cfg
from .arm_client import ArmClient
from .detections import DEFAULT_BAUD, SerialDetectionSource, find_camera_port
from .mirrored_arm import MirroredArm
from .pick_place import (DONE, FAULT, STOPPED, MotionGuard, MotionRefused,
                         PickPlaceController, load_settings, tool_workspace)

LOG = logging.getLogger("sketchbot.pick_place_service")
MONITOR_PAGE = Path(__file__).resolve().parents[1] / "web" / "static" / "pickplace.html"
WAITING, READY, RUNNING, PARKING = "waiting", "ready", "running", "parking"


def sd_notify(message: str) -> None:
    """Tell systemd something (READY=1, WATCHDOG=1, STATUS=...). No-op elsewhere."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode("ascii", "replace"), address)
    except OSError:
        pass


class PickPlaceService:
    def __init__(self, host: str = "127.0.0.1", arm_port: int = 8765,
                 camera_port: str = "auto", baud: int = DEFAULT_BAUD,
                 config_dir: Optional[str] = None, live: bool = False,
                 slow: bool = True, autostart: bool = False,
                 park_when_done: bool = True, record: Optional[str] = None):
        self.host, self.arm_port = host, int(arm_port)
        self.camera_port, self.baud = camera_port, int(baud)
        self.config_dir = config_dir
        self.live, self.slow = bool(live), bool(slow)
        self.autostart, self.park_when_done = bool(autostart), bool(park_when_done)
        self.record = record
        self._lock = threading.RLock()
        self.state = WAITING
        self.problems: List[str] = ["starting"]
        self.history: List[str] = []
        self.controller: Optional[PickPlaceController] = None
        self.last_summary: Optional[dict] = None
        self._worker: Optional[threading.Thread] = None
        self._autostarted = False
        self.pose: Optional[tuple] = None
        self.sessions = 0

    # ------------------------------------------------------------ helpers

    def note(self, text: str) -> None:
        line = time.strftime("%H:%M:%S ") + text
        LOG.info(text)
        with self._lock:
            self.history.append(line)
            del self.history[:-60]

    def _arm(self):
        arm = ArmClient(self.host, self.arm_port, timeout=3.0)
        arm.connect()
        return arm

    def _settings(self):
        settings = load_settings(self.config_dir)
        workspace = cfg.load_all(self.config_dir)["workspace"]
        return settings, workspace

    def _rest_pose(self, settings) -> tuple:
        from web.control import REST_POSE
        return tuple(float(a) for a in REST_POSE)

    def _camera_present(self) -> Optional[str]:
        if self.camera_port not in (None, "", "auto"):
            return self.camera_port if os.path.exists(self.camera_port) else None
        try:
            return find_camera_port()
        except RuntimeError:
            return None

    def busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    # ------------------------------------------------------- prerequisites

    def check(self) -> List[str]:
        """What stands in the way of a Start. Moves nothing."""
        problems: List[str] = []
        try:
            settings, _ = self._settings()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return ["configuration error: %s" % exc]
        try:
            with ArmClient(self.host, self.arm_port, timeout=2.0) as arm:
                pose = arm.status_angles()
        except OSError as exc:
            pose = None
            problems.append("arm agent not reachable on %s:%d (%s)" % (self.host, self.arm_port, exc))
        else:
            if pose is None:
                problems.append("arm agent did not report its pose")
        self.pose = pose
        if pose is not None:
            rest = self._rest_pose(settings)
            if max(abs(a - b) for a, b in zip(pose[:4], rest[:4])) > 0.6:
                problems.append("arm is not parked: press Park")
        if self._camera_present() is None:
            problems.append("camera not found: no USB serial device with Espressif's "
                            "vendor id (303A)" if self.camera_port in (None, "", "auto")
                            else "camera port %s is missing" % self.camera_port)
        return problems

    def refresh(self) -> None:
        """Called from the main loop about once a second."""
        if self.busy():
            return
        problems = self.check()
        with self._lock:
            # The check takes seconds (listing serial ports is slow). A Start
            # pressed meanwhile has already set the state; leave it alone.
            if self.busy() or self.state in (RUNNING, PARKING):
                return
            self.problems = problems
            ended = self.state in (DONE, STOPPED, FAULT)
            if problems:
                if not ended or self.state == READY:
                    self.state = WAITING
            elif not ended:
                self.state = READY
        if not problems and self.autostart and not self._autostarted:
            self._autostarted = True
            self.note("autostart: everything is ready")
            self.start()

    # ------------------------------------------------------------ actions

    def start(self) -> dict:
        with self._lock:
            if self.busy():
                return {"ok": False, "error": "already running"}
            problems = self.check()
            if problems:
                self.problems = problems
                return {"ok": False, "error": "; ".join(problems)}
            self.state = RUNNING
            self.controller = None
            self.sessions += 1
            self._worker = threading.Thread(target=self._session, name="pickplace-session",
                                            daemon=True)
            self._worker.start()
        return {"ok": True}

    def stop(self) -> dict:
        controller = self.controller
        if controller is not None:
            controller.stop()
            self.note("stop requested")
        return {"ok": True, "stop_requested": True}

    def park(self) -> dict:
        with self._lock:
            if self.busy():
                return {"ok": False, "error": "busy: press Stop first"}
            self.state = PARKING
            self._worker = threading.Thread(target=self._park, name="pickplace-park", daemon=True)
            self._worker.start()
        return {"ok": True}

    # ------------------------------------------------------------ workers

    def _wrap(self, arm, settings):
        return MirroredArm(arm) if settings["arm"]["reach_behind"] else arm

    def _session(self) -> None:
        arm = source = None
        final = FAULT
        try:
            settings, workspace = self._settings()
            source = SerialDetectionSource(self.camera_port, self.baud, self.record).open()
            raw = self._arm()
            arm = self._wrap(raw, settings)
            controller = PickPlaceController(workspace, settings, source, arm=arm,
                                             dry_run=not self.live, slow=self.slow)
            self.controller = controller
            self.note("session %d started (%s%s)" % (
                self.sessions, "LIVE" if self.live else "dry-run", ", slow" if self.slow else ""))
            summary = controller.run()
            self.last_summary = summary
            final = summary["state"]
            self.note("session ended: %s %s; picked %d, placed %d" % (
                summary["state"], summary.get("message", ""), summary["picked"], summary["placed"]))
            if final == DONE and self.park_when_done and self.live:
                self._park_with(controller.guard)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self.note("session failed: %s" % exc)
            self.last_summary = {"state": FAULT, "message": str(exc)}
        finally:
            for thing in (source, arm):
                try:
                    if thing is not None:
                        thing.close()
                except Exception:
                    pass
            with self._lock:
                self.state = final

    def _park_with(self, guard: MotionGuard) -> None:
        """Checked move to the rest pose from wherever the arm is."""
        guard.start()
        target = guard.rest_pose[:5] + (guard.pose[5],)
        if isinstance(guard.arm, MirroredArm):
            from .mirrored_arm import mirror
            target = mirror(target)
        guard.move_joints(target, what="park")
        self.note("parked")

    def _park(self) -> None:
        arm = None
        try:
            settings, workspace = self._settings()
            arm = self._wrap(self._arm(), settings)
            guard = MotionGuard(tool_workspace(workspace, settings), settings, arm,
                                dry_run=False, sleep=time.sleep, slow=True)
            self._park_with(guard)
        except (MotionRefused, OSError, RuntimeError, ValueError) as exc:
            self.note("park refused: %s" % exc)
        finally:
            if arm is not None:
                arm.close()
            with self._lock:
                self.state = WAITING

    # ----------------------------------------------------------- snapshot

    def snapshot(self) -> dict:
        controller = self.controller
        with self._lock:
            state, problems = self.state, list(self.problems)
            history = list(self.history[-40:])
        if self.busy() and state != PARKING:
            state = RUNNING
        if controller is not None and state in (RUNNING, DONE, STOPPED, FAULT):
            snap = controller.snapshot()
            snap["log"] = (snap.get("log") or [])[-30:] + history[-10:]
        else:
            snap = {"state": state, "message": "", "dry_run": not self.live,
                    "stop_requested": False, "detections": [], "inference_ms": None,
                    "frame_age_s": None, "frames": 0, "aim": None, "target": None,
                    "pose": list(self.pose) if self.pose else [],
                    "grasp_point_mm": [], "picked": 0, "placed": 0, "failures": [],
                    "moves_sent": 0, "moves_planned": 0, "colours": [], "confidence": 1.0,
                    "log": history}
        if state == RUNNING:
            pass
        elif problems:
            snap["message"] = "; ".join(problems)
        elif state == READY:
            snap["message"] = "ready: press Start"
        snap["service"] = {"state": state, "problems": problems, "live": self.live,
                           "slow": self.slow, "autostart": self.autostart,
                           "can_start": state != RUNNING and state != PARKING and not problems,
                           "can_park": state not in (RUNNING, PARKING),
                           "busy": self.busy(), "sessions": self.sessions}
        if state in (WAITING, READY, PARKING):
            snap["state"] = state
        return snap


class _Handler(BaseHTTPRequestHandler):
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
            return self._send(200, MONITOR_PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/pickplace/state":
            return self._json(200, self.server.service.snapshot())
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        origin = self.headers.get("Origin")
        if (origin and urlsplit(origin).netloc != self.headers.get("Host")) \
                or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._json(403, {"error": "Cross-origin control is not allowed"})
        service: PickPlaceService = self.server.service
        actions = {"/api/pickplace/stop": service.stop, "/api/pickplace/start": service.start,
                   "/api/pickplace/park": service.park}
        if path not in actions:
            return self._json(404, {"error": "Unknown action"})
        result = actions[path]()
        self._json(200 if result.get("ok") else 409, result)


def serve(service: PickPlaceService, port: int, bind: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((bind, port), _Handler)
    server.daemon_threads = True
    server.service = service
    threading.Thread(target=server.serve_forever, name="pickplace-http", daemon=True).start()
    return server


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pick and place as a long-running service. "
                                            "Dry-run unless --live is given.")
    p.add_argument("--host", default="127.0.0.1", help="Arm agent host.")
    p.add_argument("--arm-port", type=int, default=8765)
    p.add_argument("--port", default="auto", help="Camera serial port; auto finds vendor 303A.")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--config-dir", default=None)
    p.add_argument("--http-port", type=int, default=7110)
    p.add_argument("--bind", default="127.0.0.1",
                   help="Address the page is served on. 0.0.0.0 lets anything on the "
                        "network press Start: trusted networks only.")
    p.add_argument("--live", action="store_true",
                   help="Send moves to the arm. Without it sessions are dry runs.")
    p.add_argument("--i-have-calibrated-this-arm", action="store_true",
                   help="Required with --live. There is nobody to type a confirmation "
                        "at boot, so the confirmation is made once, here, by whoever "
                        "installs the unit after doing docs/pick-place.md.")
    p.add_argument("--full-speed", action="store_true", help="Do not use the slow profile.")
    p.add_argument("--autostart", action="store_true",
                   help="Start one session by itself the first time everything is ready.")
    p.add_argument("--no-park", action="store_true", help="Do not park after a finished session.")
    p.add_argument("--record", metavar="FILE")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.live and not args.i_have_calibrated_this_arm:
        print("--live needs --i-have-calibrated-this-arm (see docs/pick-place.md).", file=sys.stderr)
        return 2
    service = PickPlaceService(args.host, args.arm_port, args.port, args.baud, args.config_dir,
                               live=args.live, slow=not args.full_speed, autostart=args.autostart,
                               park_when_done=not args.no_park, record=args.record)
    try:
        server = serve(service, args.http_port, args.bind)
    except OSError as exc:
        print("Cannot serve on %s:%d: %s" % (args.bind, args.http_port, exc), file=sys.stderr)
        return 1
    service.note("service up on http://%s:%d/ (%s, autostart %s)" % (
        args.bind, server.server_port, "LIVE" if args.live else "dry-run",
        "on" if args.autostart else "off"))
    sd_notify("READY=1")
    last_status = None
    try:
        while True:
            service.refresh()
            sd_notify("WATCHDOG=1")
            status = service.snapshot()["service"]["state"] + ": " + "; ".join(service.problems)
            if status != last_status:
                sd_notify("STATUS=" + status)
                if not service.busy():
                    service.note(status)
                last_status = status
            time.sleep(1.0)
    except KeyboardInterrupt:
        service.stop()
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
