"""Branded live gallery web server (stdlib only).

Serves the static gallery page plus:
  GET /gallery.json          -> manifest of published cards (+ brand info)
  GET /gallery/<file>        -> a published postcard PNG

Run:  python -m web.server        # http://<host>:7100
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

from sketch_artist import config as cfg
from .control import ControlApp, ControlBusy

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_conf():
    conf = cfg.load_all()
    gallery = conf["branding"]["gallery"]
    brand = conf["branding"]["brand"]
    gallery_dir = cfg.resolve_path(gallery["output_dir"])
    return gallery, brand, gallery_dir


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quieter logs
        pass

    def _send(self, code, body: bytes, ctype: str, headers=None):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, str(value))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def do_HEAD(self):
        # Same routing as GET; _send omits the body for HEAD requests.
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/control", "/index.html"):
            return self._serve_static("control.html", "text/html; charset=utf-8")
        if path in ("/gallery", "/gallery/"):
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path == "/control.css":
            return self._serve_static("control.css", "text/css")
        if path.startswith("/dist/"):
            name = unquote(path[1:])
            if (STATIC_DIR / name).resolve().is_relative_to((STATIC_DIR / "dist").resolve()):
                return self._serve_static(name, mimetypes.guess_type(name)[0] or "application/octet-stream")
            return self._send(404, b"Not found", "text/plain")
        if path == "/api/control/state":
            return self._json(200, self.server.control.state())
        if path == "/api/control/diagnostics":
            probe = parse_qs(urlsplit(self.path).query).get("probe") == ["1"]
            return self._json(200, self.server.control.diagnostics(probe))
        if path in ("/api/camera/face.jpg", "/api/camera/gripper.jpg"):
            try:
                body, health = self.server.control.snapshot(path.split("/")[-1].split(".")[0])
                return self._send(200, body, "image/jpeg", {
                    "X-Face-Detected": int(health["face_detected"]),
                    "X-Face-Detector": int(health["face_detection_available"]),
                })
            except Exception as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/style.css":
            return self._serve_static("style.css", "text/css")
        if path == "/gallery.json":
            return self._serve_manifest()
        if path.startswith("/gallery/"):
            return self._serve_card(unquote(path[len("/gallery/"):]))
        self._send(404, b"Not found", "text/plain")

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, allow_nan=False).encode("utf-8"), "application/json")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        origin = self.headers.get("Origin")
        if (origin and urlsplit(origin).netloc != self.headers.get("Host")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._json(403, {"error": "Cross-origin control is not allowed"})
        if self.headers.get_content_type() != "application/json":
            return self._json(415, {"error": "Expected application/json"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                return self._json(413, {"error": "Invalid request size"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            app = self.server.control
            actions = {
                "/api/control/arm": lambda: app.arm(body.get("confirmed"), body.get("tool_confirmed")),
                "/api/control/stop": app.stop,
                "/api/control/move": lambda: app.move(body),
                "/api/control/preview": lambda: app.preview(body),
                "/api/control/task/prepare": lambda: app.prepare_task(body),
                "/api/control/task/step": lambda: app.advance_task(body),
                "/api/settings/tools": lambda: app.save_tools(body),
                "/api/settings/workspace": lambda: app.save_workspace(body),
                "/api/settings/controls": lambda: app.save_controls(body),
                "/api/settings/camera": lambda: app.save_camera(body.get("role"), body.get("spec")),
            }
            if path not in actions:
                return self._json(404, {"error": "Unknown action"})
            result = actions[path]()
            return self._json(200, result)
        except ControlBusy as exc:
            return self._json(409, {"error": str(exc), "retryable": True})
        except (ValueError, TypeError, KeyError) as exc:
            return self._json(422, {"error": str(exc)})
        except (OSError, RuntimeError) as exc:
            self.server.control.stop()
            return self._json(503, {"error": str(exc)})

    def _serve_static(self, name: str, ctype: str):
        f = STATIC_DIR / name
        if not f.exists():
            return self._send(404, b"Not found", "text/plain")
        self._send(200, f.read_bytes(), ctype)

    def _serve_manifest(self):
        gallery, brand, gallery_dir = _load_conf()
        manifest = Path(gallery_dir) / "manifest.json"
        items = []
        if manifest.exists():
            try:
                items = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                items = []
        payload = {
            "brand": {
                "name": brand.get("name", ""),
                "title": brand.get("title", ""),
                "tagline": brand.get("tagline", ""),
                "primary_hex": brand.get("primary_hex", "#3B47CE"),
                "accent_hex": brand.get("accent_hex", "#00E5A0"),
            },
            "gallery": {
                "title": gallery.get("title", "Live Gallery"),
                "columns": gallery.get("columns", 4),
                "poll_seconds": gallery.get("poll_seconds", 3),
            },
            "items": items,
        }
        self._send(200, json.dumps(payload).encode("utf-8"), "application/json")

    def _serve_card(self, name: str):
        _, _, gallery_dir = _load_conf()
        # Prevent path traversal: only serve a bare filename from the gallery dir.
        safe = Path(name).name
        f = Path(gallery_dir) / safe
        if not f.exists() or f.suffix.lower() != ".png":
            return self._send(404, b"Not found", "text/plain")
        self._send(200, f.read_bytes(), "image/png")


def main(port: int = 7100, bind="0.0.0.0", arm_host="127.0.0.1", arm_port=8765,
         allow_motion=False) -> int:
    server = ThreadingHTTPServer((bind, port), Handler)
    server.control = ControlApp(arm_host, arm_port, allow_motion=allow_motion)
    report = server.control.diagnostics()
    print(f"Sketchbot studio on http://{bind}:{port}; motion {'available but disarmed' if allow_motion else 'disabled'}")
    print(json.dumps({"arm_connected": report["arm"]["connected"], "paper_reachable": report["paper"]["ok"],
                      "video_devices": len(report["devices"]), "default_mode": "preview"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        server.control.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sketchbot live gallery server.")
    parser.add_argument("--port", type=int, default=7100)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--arm-host", default="127.0.0.1")
    parser.add_argument("--arm-port", type=int, default=8765)
    parser.add_argument("--allow-motion", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(args.port, args.bind, args.arm_host, args.arm_port, args.allow_motion))
