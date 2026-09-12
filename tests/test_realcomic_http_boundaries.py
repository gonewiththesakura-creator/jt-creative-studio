import base64
import http.client
import http.server
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("realcomic_http", ROOT / "server.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp())
m.DATA_DIR = root
m.JOBS_DIR = root / "jobs"; m.JOBS_DIR.mkdir()
m.JOBS_FILE = root / "jobs.json"
m.FAVORITES_DIR = root / "favorites"; m.FAVORITES_DIR.mkdir()
m.FAVORITES_FILE = root / "favorites.json"
m.UPLOAD_CAPABILITIES_FILE = root / "upload_capabilities.json"
m._jobs = {}; m._favorites = {}; m._upload_capabilities = {}
uploaded = []

def fake_upload(data, filename, ctype, timeout=120):
    uploaded.append((filename, ctype, len(data)))
    return "api/trusted-source.png"

m.rh_upload_file = fake_upload
m.run_job = lambda job: None
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), m.Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
port = server.server_port


def post(path, payload, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection.request("POST", path, body, headers)
    response = connection.getresponse()
    data = json.loads(response.read() or b"{}")
    set_cookie = response.getheader("Set-Cookie")
    status = response.status
    connection.close()
    return status, data, set_cookie

try:
    status, data, _ = post("/api/realcomic-upload", {
        "workflow": "realcomic", "input_key": "source_image",
        "filename": "fake.png", "data": base64.b64encode(b"not an image").decode(),
    })
    assert status == 400 and "image" in data["error"].lower() and not uploaded, (status, data, uploaded)

    png = bytes((137, 80, 78, 71, 13, 10, 26, 10)) + b"valid-fixture"
    status, data, set_cookie = post("/api/realcomic-upload", {
        "workflow": "realcomic", "input_key": "source_image",
        "filename": "fixture.png", "data": base64.b64encode(png).decode(),
    })
    assert status == 200 and data.get("uploadToken") and "fileName" not in data
    assert uploaded == [("fixture.png", "image/png", len(png))]
    assert set_cookie and "SameSite=Strict" in set_cookie and "HttpOnly" in set_cookie
    cookie = set_cookie.split(";", 1)[0]

    payload = {
        "workflow": "realcomic", "media": {"source_image": data["uploadToken"], "evil": "must-drop"},
        "params": {"requirements": "保留构图", "evil": "must-drop"},
        "client_request_id": "same-realcomic", "webappId": "attacker-app",
        "nodeInfoList": [{"nodeId": "999", "fieldName": "evil", "fieldValue": "evil"}],
    }
    status, missing_id, _ = post("/api/ai-app-generate", {**payload, "client_request_id": ""}, cookie)
    assert status == 400 and "client_request_id" in missing_id["error"], (status, missing_id)
    status, first, _ = post("/api/ai-app-generate", payload, cookie)
    assert status == 200 and first.get("job_id"), (status, first)
    jid = first["job_id"]; job = m._jobs[jid]
    assert job["media"] == {"source_image": "fixture.png"}
    assert job["provider_media"] == {"source_image": "api/trusted-source.png"}
    assert job["params"] == {"requirements": "保留构图"}
    assert "webappId" not in job and "nodeInfoList" not in job
    status, second, _ = post("/api/ai-app-generate", payload, cookie)
    assert status == 200 and second == {
        "job_id": jid, "existing_job": jid, "deduplicated": True,
        "message": "same request already accepted",
    }, (status, second)

    m._jobs[jid]["status"] = "done"
    m._jobs["busy-cloud"] = {"id": "busy-cloud", "status": "running", "generation_backend": "cloud"}
    status, busy, _ = post("/api/ai-app-generate", {**payload, "client_request_id": "different"}, cookie)
    assert status == 429 and "running_job" not in busy and "running_jobs" not in busy, (status, busy)
    del m._jobs["busy-cloud"]
    m._jobs["busy-local"] = {"id": "busy-local", "status": "running", "generation_backend": "local"}
    status, parallel, _ = post("/api/ai-app-generate", {**payload, "client_request_id": "parallel-cloud"}, cookie)
    assert status == 200 and parallel.get("job_id") not in (jid, "busy-local"), (status, parallel)
    print("REALCOMIC_HTTP_BOUNDARIES_OK", {
        "invalid_magic": 400, "trusted_upload": uploaded[0],
        "opaque_upload_token": True, "deduplicated": second["deduplicated"],
        "cloud_busy": "redacted", "local_does_not_block_cloud": parallel["job_id"],
    })
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=3)
