"""Pen calibration web UI (stdlib only).

A small page for the two numbers the drawing depends on and that nothing else
can measure for you: how long the pen is, and where the paper is. Open it on a
phone next to the arm, jog the pen down until it just touches, press *Mark
contact*, done.

  GET  /                     -> the page
  GET  /api/state            -> config, current target, servo pose, reach band
  POST /api/hover            -> ramp to the paper centre at a safe height
  POST /api/jog              -> {"dz": -1} / {"dx": 2} / {"dy": -2}  (mm)
  POST /api/goto             -> {"z": 3.0}                            (mm)
  POST /api/mark_contact     -> the pen is touching NOW: write down_z/up_z
  POST /api/set_pen_length   -> {"wrist_pen_mm": 174}  (ruler-measured)
  POST /api/derive_pen_length-> touching at z means the pen is z too long:
                                fold it into wrist_pen_mm, draw at z=0
  POST /api/square           -> trace the paper box at the current down_z
  POST /api/park             -> ramp to the firmware rest pose (safe to power off)

Run:  python -m web.calibrate       # http://<host>:7200

Why this exists. The whole 40 mm paper is only reachable in a band about 8 mm
deep above the sheet, so a pen even 10 mm longer than `links.wrist_pen_mm`
presses at every height the arm can reach and no value of `down_z_mm` fixes
it. Several rounds of "raise it a bit" were spent learning that. Measure it.

Config is written with a targeted regex on the three keys so the comments in
config/workspace.yaml survive - round-tripping through yaml.dump would strip
every one of them.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

from sketch_artist import config as cfg
from sketch_artist.arm_client import ArmClient
from sketch_artist.kinematics import BraccioKinematics, UnreachableError

STATIC_DIR = Path(__file__).resolve().parent / "static"
WORKSPACE_YAML = cfg.resolve_path("config/workspace.yaml")

# The pose the MCU sketch commands at power-on. Parking here before shutdown
# means the next boot moves nothing.
REST_POSE = (90.0, 45.0, 180.0, 180.0, 90.0, 10.0)

# Never command the tip below this: it is already through the paper.
Z_FLOOR_MM = -3.0
Z_CEIL_MM = 40.0


def _write_config_keys(values: Dict[str, float]) -> None:
    """Rewrite `key: <number>` lines in workspace.yaml, keeping the comments.

    The keys touched here (wrist_pen_mm, down_z_mm, up_z_mm) are unique in the
    file, so matching on the bare key name is safe.
    """
    text = WORKSPACE_YAML.read_text(encoding="utf-8")
    for key, value in values.items():
        pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*)[-+]?\d+(?:\.\d+)?", re.M)
        if not pattern.search(text):
            raise KeyError(f"{key} not found in {WORKSPACE_YAML}")
        rendered = f"{value:g}"
        text = pattern.sub(lambda m: m.group(1) + rendered, text, count=1)
    WORKSPACE_YAML.write_text(text, encoding="utf-8")


def _reach_band(kin: BraccioKinematics, workspace: dict) -> Tuple[int, int]:
    """(deepest, highest) whole-mm heights at which EVERY paper point solves.

    This is the band the pen has to live in. It is narrow - about 0-8 mm with
    the stock 174 mm pen - and it shrinks as wrist_pen_mm grows.
    """
    p = workspace["paper"]
    x0, y0 = float(p["origin_x_mm"]), float(p["origin_y_mm"])
    w, h = float(p["width_mm"]), float(p["height_mm"])

    def all_reach(z: float) -> bool:
        for i in range(6):
            for j in range(6):
                try:
                    kin.solve(x0 + w * i / 5, y0 + h * j / 5, z, strict=True)
                except UnreachableError:
                    return False
        return True

    lo = next((z for z in range(-3, 41) if all_reach(float(z))), None)
    if lo is None:
        return (0, 0)
    hi = lo
    for z in range(lo, 41):
        if all_reach(float(z)):
            hi = z
        else:
            break
    return (lo, hi)


class Calibrator:
    """Owns the arm connection and the current target; one move at a time."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.lock = threading.Lock()
        self.reload()
        self.x, self.y = self.paper_centre()
        self.z = min(8.0, float(self.band[1])) if self.band[1] > 0 else 8.0
        self.last_error: Optional[str] = None

    # -- config ------------------------------------------------------------
    def reload(self) -> None:
        self.conf = cfg.load_all()
        self.workspace = self.conf["workspace"]
        self.kin = BraccioKinematics(self.workspace)
        self.band = _reach_band(self.kin, self.workspace)

    def paper_centre(self) -> Tuple[float, float]:
        p = self.workspace["paper"]
        return (float(p["origin_x_mm"]) + float(p["width_mm"]) / 2,
                float(p["origin_y_mm"]) + float(p["height_mm"]) / 2)

    # -- arm ---------------------------------------------------------------
    def _pose(self, arm: ArmClient):
        return arm.status_angles()

    def _move_to(self, arm: ArmClient, x: float, y: float, z: float,
                 step: float = 2.0) -> Tuple[float, ...]:
        angles = self.kin.solve(x, y, z, strict=True)   # raises if unreachable
        arm.move_ramped(angles.as_tuple(), max_step_deg=step, dwell_s=0.03)
        self.x, self.y, self.z = x, y, z
        return angles.as_tuple()

    def state(self) -> dict:
        pose = None
        try:
            with ArmClient(host=self.host, port=self.port, timeout=2.0) as arm:
                pose = self._pose(arm)
            agent = "connected"
        except OSError as exc:
            agent = f"unreachable: {exc}"
        pen, links = self.workspace["pen"], self.workspace["links"]
        return {
            "agent": agent,
            "pose": pose,
            "target": {"x": self.x, "y": self.y, "z": self.z},
            "config": {
                "wrist_pen_mm": float(links["wrist_pen_mm"]),
                "down_z_mm": float(pen["down_z_mm"]),
                "up_z_mm": float(pen["up_z_mm"]),
            },
            "band": {"lo": self.band[0], "hi": self.band[1]},
            "paper": self.workspace["paper"],
            "last_error": self.last_error,
        }

    def hover(self) -> dict:
        cx, cy = self.paper_centre()
        z = float(min(8, self.band[1])) if self.band[1] > 0 else 8.0
        with self.lock, ArmClient(host=self.host, port=self.port) as arm:
            self._move_to(arm, cx, cy, z, step=2.5)
        return {"ok": True, "z": z}

    def jog(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> dict:
        z = max(Z_FLOOR_MM, min(Z_CEIL_MM, self.z + dz))
        with self.lock, ArmClient(host=self.host, port=self.port) as arm:
            self._move_to(arm, self.x + dx, self.y + dy, z, step=1.5)
        return {"ok": True, "x": self.x, "y": self.y, "z": self.z}

    def goto_z(self, z: float) -> dict:
        z = max(Z_FLOOR_MM, min(Z_CEIL_MM, float(z)))
        with self.lock, ArmClient(host=self.host, port=self.port) as arm:
            self._move_to(arm, self.x, self.y, z, step=1.5)
        return {"ok": True, "z": self.z}

    def mark_contact(self) -> dict:
        """The pen is touching at the current z: make that the drawing height.

        up_z is set 5 mm above, capped at the top of the reach band so pen-up
        moves never leave the paper's reachable envelope.
        """
        down = round(self.z, 1)
        lo, hi = self.band
        # Contact ABOVE the band is not a drawing height, it is a diagnosis: the
        # pen is (z - band) mm longer than the model. Writing it as down_z would
        # put most of the paper out of reach and the planner would skip strokes.
        if down > hi:
            raise ValueError(
                f"touching at {down:g} mm is above the reach band (max {hi} mm): "
                f"the pen is about {down - hi:g} mm too long. Shorten it so the "
                f"tip stands 27 mm below the collar, or press 'Derive from "
                f"contact' to fold it into wrist_pen_mm instead.")
        if down < lo:
            raise ValueError(
                f"{down:g} mm is below the reach band (min {lo} mm): that is "
                f"through the paper, not on it.")
        up = round(min(down + 5.0, float(hi)), 1)
        if up <= down:
            up = round(down + 2.0, 1)
        _write_config_keys({"down_z_mm": down, "up_z_mm": up})
        self.reload()
        return {"ok": True, "down_z_mm": down, "up_z_mm": up}

    def set_pen_length(self, wrist_pen_mm: float) -> dict:
        """Ruler-measured: wrist-rotation axis to the pen tip, in mm."""
        _write_config_keys({"wrist_pen_mm": float(wrist_pen_mm)})
        self.reload()
        return {"ok": True, "wrist_pen_mm": float(wrist_pen_mm),
                "band": {"lo": self.band[0], "hi": self.band[1]}}

    def derive_pen_length(self) -> dict:
        """Touching at z > 0 means the pen is z mm longer than modelled.

        Fold that into wrist_pen_mm so commanded heights become honest, then
        draw at the surface. Prefer the ruler when you have one - this costs
        reach, because a longer modelled pen lifts the wrist.
        """
        extra = round(self.z, 1)
        new_len = float(self.workspace["links"]["wrist_pen_mm"]) + extra
        _write_config_keys({"wrist_pen_mm": new_len})
        self.reload()
        up = float(min(5, self.band[1])) if self.band[1] > 0 else 5.0
        _write_config_keys({"down_z_mm": 0.0, "up_z_mm": up})
        self.reload()
        self.z = 0.0
        return {"ok": True, "wrist_pen_mm": new_len, "down_z_mm": 0.0,
                "up_z_mm": up, "band": {"lo": self.band[0], "hi": self.band[1]}}

    def square(self) -> dict:
        """Trace the paper box at the configured down_z: the acceptance test."""
        p = self.workspace["paper"]
        pen = self.workspace["pen"]
        x0, y0 = float(p["origin_x_mm"]), float(p["origin_y_mm"])
        w, h = float(p["width_mm"]), float(p["height_mm"])
        down, up = float(pen["down_z_mm"]), float(pen["up_z_mm"])
        inset = 3.0
        corners = [(x0 + inset, y0 + inset), (x0 + w - inset, y0 + inset),
                   (x0 + w - inset, y0 + h - inset), (x0 + inset, y0 + h - inset),
                   (x0 + inset, y0 + inset)]
        pts = []
        for (ax, ay), (bx, by) in zip(corners, corners[1:]):
            for k in range(8):
                t = k / 8.0
                pts.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        pts.append(corners[0])
        with self.lock, ArmClient(host=self.host, port=self.port) as arm:
            self._move_to(arm, pts[0][0], pts[0][1], up, step=2.5)
            self._move_to(arm, pts[0][0], pts[0][1], down, step=1.0)
            for x, y in pts[1:]:
                arm.move(self.kin.solve(x, y, down, strict=True).as_tuple())
            self._move_to(arm, pts[-1][0], pts[-1][1], up, step=1.0)
        return {"ok": True, "points": len(pts), "down_z_mm": down, "up_z_mm": up}

    def park(self) -> dict:
        with self.lock, ArmClient(host=self.host, port=self.port) as arm:
            arm.move_ramped(REST_POSE, max_step_deg=3.0, dwell_s=0.05)
        return {"ok": True, "pose": REST_POSE}


CAL: Optional[Calibrator] = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/calibrate"):
            f = STATIC_DIR / "calibrate.html"
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json(200, CAL.state())
        self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._body()
        actions = {
            "/api/hover": lambda: CAL.hover(),
            "/api/jog": lambda: CAL.jog(float(body.get("dx", 0)),
                                        float(body.get("dy", 0)),
                                        float(body.get("dz", 0))),
            "/api/goto": lambda: CAL.goto_z(float(body["z"])),
            "/api/mark_contact": lambda: CAL.mark_contact(),
            "/api/set_pen_length": lambda: CAL.set_pen_length(float(body["wrist_pen_mm"])),
            "/api/derive_pen_length": lambda: CAL.derive_pen_length(),
            "/api/square": lambda: CAL.square(),
            "/api/park": lambda: CAL.park(),
        }
        action = actions.get(path)
        if action is None:
            return self._send(404, b"Not found", "text/plain")
        try:
            CAL.last_error = None
            return self._json(200, action())
        except UnreachableError as exc:
            CAL.last_error = f"out of reach: {exc}"
        except (OSError, KeyError, ValueError) as exc:
            CAL.last_error = f"{type(exc).__name__}: {exc}"
        self._json(409, {"ok": False, "error": CAL.last_error})


def main(port: int = 7200, arm_host: str = "127.0.0.1", arm_port: int = 8765) -> int:
    global CAL
    CAL = Calibrator(arm_host, arm_port)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    lo, hi = CAL.band
    print(f"Pen calibration on http://0.0.0.0:{port}  "
          f"(arm {arm_host}:{arm_port}; reach band {lo}..{hi} mm)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sketchbot pen calibration UI.")
    parser.add_argument("--port", type=int, default=7200)
    parser.add_argument("--arm-host", default="127.0.0.1")
    parser.add_argument("--arm-port", type=int, default=8765)
    args = parser.parse_args()
    raise SystemExit(main(args.port, args.arm_host, args.arm_port))
