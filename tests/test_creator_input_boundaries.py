import http.client
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("creator_boundary_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
root = Path(tempfile.mkdtemp())
server.DATA_DIR = root
server.JOBS_DIR = root / "jobs"; server.JOBS_DIR.mkdir()
server.JOBS_FILE = root / "jobs.json"
server.FAVORITES_DIR = root / "favorites"; server.FAVORITES_DIR.mkdir()
server.FAVORITES_FILE = root / "favorites.json"
server._jobs = {}; server._favorites = {}
server.run_job = lambda job: None
COOKIE = "jt_session=" + server._encode_session_cookie("creator-boundary-session-1234567890")
httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

BASE = {
    "workflow": "anima02",
    "prompt": "adult woman, fashion portrait",
    "negative_prompt": "text, watermark",
    "prompt_mode": "manual",
    "width": 768,
    "height": 1024,
    "batch": 1,
    "hd": 0,
    "seed": 321,
    "seed_mode": "fixed",
    "style_id": "retro_manga_luxury",
    "style_variant": "default",
    "mode": "original",
    "generation_backend": "local",
}


def post(payload):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    raw = json.dumps(payload).encode()
    connection.request("POST", "/api/generate", raw, {"Content-Type": "application/json", "Cookie": COOKIE})
    response = connection.getresponse()
    data = json.loads(response.read())
    status = response.status
    connection.close()
    return status, data


def test_creator_submit_requires_idempotency_key():
    status, data = post(BASE)
    assert status == 400
    assert "client_request_id" in data["error"]
    assert server._jobs == {}


def test_creator_submit_rejects_malformed_numbers_without_creating_job():
    for field, value in [
        ("batch", "many"), ("hd", "ultra"), ("width", {}), ("height", []),
    ]:
        payload = {**BASE, "client_request_id": f"bad-{field}", field: value}
        status, data = post(payload)
        assert status == 400, (field, status, data)
        assert data["error"] == "invalid numeric parameters", (field, data)
    assert server._jobs == {}


def teardown_module():
    httpd.shutdown()
    httpd.server_close()
