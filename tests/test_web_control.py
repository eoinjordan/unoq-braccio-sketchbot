"""HTTP integration tests run against the real threaded server and TCP simulator."""

import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from sketch_artist import config
from web.control import ControlApp, REST_POSE
from web.server import Handler


@pytest.fixture
def web_app(tmp_path, sim_agent):
    for name in ("cameras", "workspace", "drawing", "branding", "scenes"):
        shutil.copy(config.CONFIG_DIR / f"{name}.yaml", tmp_path)
    sim_agent.simulator.apply_move(REST_POSE)
    app = ControlApp(port=sim_agent.port, config_dir=tmp_path, allow_motion=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.control = app
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}", app, sim_agent
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)
    app.close()


def request(base, path, body=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    data = json.dumps(body).encode() if body is not None else None
    call = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        response = urllib.request.urlopen(call, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read())


def test_http_startup_preview_and_guarded_motion(web_app):
    base, app, agent = web_app
    count = agent.simulator.move_count
    code, state = request(base, "/api/control/state")
    assert code == 200 and not state["armed"]
    code, target = request(base, "/api/control/preview", {"x": 15, "y": 15, "z": 10})
    assert code == 200 and len(target["angles"]) == 6
    assert agent.simulator.move_count == count
    assert request(base, "/api/control/move", {"joint": "base", "delta": 1})[0] == 422
    code, session = request(base, "/api/control/arm", {"confirmed": True})
    assert code == 200
    body = {"token": session["token"], "held": True, "joint": "base", "delta": 0.5}
    assert request(base, "/api/control/move", body)[0] == 200
    assert agent.simulator.move_count == count + 1
    assert request(base, "/api/control/stop", {})[0] == 200
    assert request(base, "/api/control/move", body)[0] == 422


def test_cross_origin_arm_request_is_rejected(web_app):
    base, app, agent = web_app
    assert request(base, "/api/control/arm", {"confirmed": True}, "http://untrusted.example")[0] == 403
    assert app.token is None


def test_busy_http_response_is_retryable_and_leaves_session_armed(web_app):
    base, app, agent = web_app
    code, session = request(base, "/api/control/arm", {"confirmed": True})
    assert code == 200
    before = agent.simulator.move_count
    with app.command_lock:
        code, result = request(base, "/api/control/move", {
            "token": session["token"], "held": True, "joint": "base", "delta": 0.5})
    assert code == 409
    assert result["retryable"] is True
    assert app.token == session["token"]
    assert agent.simulator.move_count == before


@pytest.mark.parametrize("failure", [BrokenPipeError, ConnectionResetError])
@pytest.mark.parametrize("stage", ["headers", "body"])
def test_client_disconnect_during_response_closes_cleanly(failure, stage):
    handler = object.__new__(Handler)
    handler.command = "GET"
    handler.close_connection = False
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock(side_effect=failure() if stage == "headers" else None)
    handler.wfile = Mock()
    if stage == "body":
        handler.wfile.write.side_effect = failure()
    handler._json(200, {"armed": False})
    assert handler.close_connection


def test_camera_and_paper_menu_save_roundtrip(web_app):
    base, app, agent = web_app
    assert request(base, "/api/settings/workspace", {"paper": {"rotation_deg": -60}})[0] == 200
    assert request(base, "/api/settings/camera", {"role": "face", "spec": {
        "format": "snapshot", "url": "http://127.0.0.1:1/capture", "mounted_on_arm": False}})[0] == 200
    code, state = request(base, "/api/control/state")
    assert state["workspace"]["paper"]["rotation_deg"] == -60
    assert state["cameras"]["face"]["mounted_on_arm"] is False