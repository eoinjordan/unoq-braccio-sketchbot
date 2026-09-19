"""Isolated browser-test server; only a software arm and temporary settings."""

import shutil
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sketch_artist import config
from sketch_artist.sim import SimArmAgent
from sketch_artist.gallery import render_postcard, publish
from sketch_artist.planner import plan
from web.control import ControlApp, REST_POSE
from web.server import Handler
from web import server as web_server


with tempfile.TemporaryDirectory(prefix="sketchbot-browser-") as directory:
    for name in ("cameras", "workspace", "drawing", "branding", "scenes"):
        shutil.copy(config.CONFIG_DIR / f"{name}.yaml", directory)
    workspace = config.load_all(directory)["workspace"]
    branding = config.load_all(directory)["branding"]
    gallery_dir = Path(directory) / "gallery"
    gallery_dir.mkdir()
    branding["gallery"]["output_dir"] = str(gallery_dir)
    strokes = [[(0, 45), (50, 0), (100, 45)], [(15, 45), (15, 100), (85, 100), (85, 45)],
               [(40, 100), (40, 65), (60, 65), (60, 100)]]
    postcard = render_postcard(plan(strokes, workspace), workspace, branding,
                               str(gallery_dir / "preview.png"), title="Simulation preview")
    publish(postcard, branding, title="Simulation preview")
    web_server._load_conf = lambda: (branding["gallery"], branding["brand"], gallery_dir)
    with SimArmAgent(workspace) as agent:
        agent.simulator.apply_move(REST_POSE)
        app = ControlApp(port=agent.port, config_dir=directory, allow_motion=True)
        app.save_camera("face", {"enabled": False})
        app.save_camera("gripper", {"enabled": False})
        server = ThreadingHTTPServer(("127.0.0.1", 7119), Handler)
        server.control = app
        try:
            server.serve_forever()
        finally:
            app.close()
            server.server_close()