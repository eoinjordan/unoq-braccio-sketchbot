"""Branded live gallery web server (stdlib only).

Serves the static gallery page plus:
  GET /gallery.json          -> manifest of published cards (+ brand info)
  GET /gallery/<file>        -> a published postcard PNG

Run:  python -m web.server        # http://<host>:7100
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from sketch_artist import config as cfg

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

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        # Same routing as GET; _send omits the body for HEAD requests.
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path == "/style.css":
            return self._serve_static("style.css", "text/css")
        if path == "/gallery.json":
            return self._serve_manifest()
        if path.startswith("/gallery/"):
            return self._serve_card(unquote(path[len("/gallery/"):]))
        self._send(404, b"Not found", "text/plain")

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


def main(port: int = 7100) -> int:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Sketchbot gallery on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sketchbot live gallery server.")
    parser.add_argument("--port", type=int, default=7100)
    args = parser.parse_args()
    raise SystemExit(main(args.port))
