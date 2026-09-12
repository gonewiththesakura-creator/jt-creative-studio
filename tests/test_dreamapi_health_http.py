import http.client
import http.server
import importlib.util
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dream_health", ROOT / "server.py")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)
SERVER.DREAMAPI_KEY = "fixture-secret-never-serialize"
SERVER.comfy_ok = lambda: (True, "ok")
SERVER._jobs = {"a": {"id": "a", "status": "running", "generation_backend": "api"}}

httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SERVER.Handler)
thread = threading.Thread(target=httpd.serve_forever, daemon=True)
thread.start()
try:
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    conn.request("GET", "/api/health")
    response = conn.getresponse()
    raw = response.read()
    data = json.loads(raw)
    conn.close()
    assert response.status == 200
    assert data["dreamapi_configured"] is True
    assert data["api_busy"] is True
    assert "running_api" not in data
    serialized = raw.decode("utf8")
    assert "fixture-secret-never-serialize" not in serialized
    assert "dreamapi.club" not in serialized
finally:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)
