import http.client
import ast
import importlib.util
import json
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("public_quota", ROOT / "server.py")
panel = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(panel)
TMP = Path(tempfile.mkdtemp())
panel.DATA_DIR = TMP
panel.JOBS_DIR = TMP / "jobs"; panel.JOBS_DIR.mkdir()
panel.JOBS_FILE = TMP / "jobs.json"
panel.FAVORITES_DIR = TMP / "favorites"; panel.FAVORITES_DIR.mkdir()
panel.FAVORITES_FILE = TMP / "favorites.json"
panel.UPLOAD_CAPABILITIES_FILE = TMP / "upload_capabilities.json"
panel._jobs = {}; panel._favorites = {}; panel._upload_capabilities = {}
panel.BILLABLE_GLOBAL_HOURLY_LIMIT = 1
panel.BILLABLE_GLOBAL_DAILY_LIMIT = 2
panel.BILLABLE_SESSION_HOURLY_LIMIT = 1
panel.run_job = lambda job: None

httpd = panel.BoundedHTTPServer(("127.0.0.1", 0), panel.Handler)
thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
COOKIE = "jt_session=" + panel._encode_session_cookie("quota-session-1234567890")

BASE = {
    "workflow": "anima02", "prompt": "adult portrait", "negative_prompt": "",
    "prompt_mode": "manual", "width": 768, "height": 1024, "batch": 1,
    "hd": 0, "seed": 1, "seed_mode": "fixed", "style_id": "sketch",
    "style_variant": "default", "mode": "original",
}


def post(payload, cookie=COOKIE):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    raw = json.dumps(payload).encode()
    connection.request("POST", "/api/generate", raw, {
        "Content-Type": "application/json", "Cookie": cookie,
    })
    response = connection.getresponse()
    data = json.loads(response.read() or b"{}")
    headers = dict(response.getheaders())
    status = response.status
    connection.close()
    return status, data, headers


def get(path, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    headers = {"Cookie": cookie} if cookie else {}
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    data = response.read()
    response_headers = dict(response.getheaders())
    status = response.status
    connection.close()
    return status, data, response_headers


def test_all_html_entrypoints_preseed_an_isolated_billing_session():
    for path in ("/", "/promptgen", "/realism", "/video"):
        status, data, headers = get(path)
        assert status == 200 and b"<!doctype html>" in data[:200].lower()
        cookie = headers.get("Set-Cookie", "")
        assert "jt_session=" in cookie
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
        cookie_pair = cookie.split(";", 1)[0]
        status, _, repeated_headers = get(path, cookie_pair)
        assert status == 200
        assert "Set-Cookie" not in repeated_headers

    status, _, headers = get("/static/previews/style-cold.webp")
    assert status == 200
    assert "Set-Cookie" not in headers


def test_global_billable_limit_blocks_new_cloud_and_api_but_not_idempotent_or_local():
    first = {**BASE, "generation_backend": "cloud", "client_request_id": "quota-first"}
    status, accepted, _ = post(first)
    assert status == 200 and accepted.get("job_id")

    status, duplicate, _ = post(first)
    assert status == 200 and duplicate["job_id"] == accepted["job_id"]
    assert duplicate["deduplicated"] is True

    panel._jobs[accepted["job_id"]]["status"] = "done"
    status, blocked, headers = post({
        **BASE, "generation_backend": "api", "client_request_id": "quota-second-api",
        "api_model": "gpt-image-2.5-flare", "api_quality": "low", "api_fit": "cover",
    })
    assert status == 429 and "limit" in blocked["error"].lower()
    assert int(headers["Retry-After"]) > 0

    status, local, _ = post({
        **BASE, "generation_backend": "local", "client_request_id": "quota-local",
    })
    assert status == 200 and local.get("job_id")


def test_idempotency_is_bound_to_session_and_effective_payload():
    for job in panel._jobs.values():
        job["status"] = "done"
    cookie_a = "jt_session=" + panel._encode_session_cookie("idempotency-session-a-1234567890")
    cookie_b = "jt_session=" + panel._encode_session_cookie("idempotency-session-b-1234567890")
    base = {
        **BASE, "generation_backend": "local",
        "client_request_id": "same-public-id", "prompt": "adult portrait A",
    }
    status, first, _ = post(base, cookie_a)
    assert status == 200 and first.get("job_id")

    status, duplicate, _ = post(base, cookie_a)
    assert status == 200
    assert duplicate["job_id"] == first["job_id"]
    assert duplicate["deduplicated"] is True

    status, conflict, _ = post({**base, "prompt": "adult portrait B"}, cookie_a)
    assert status == 409
    assert conflict["error"] == "client_request_id already used with different request payload"
    assert len([job for job in panel._jobs.values()
                if job.get("client_request_id") == "same-public-id"]) == 1

    panel._jobs[first["job_id"]]["status"] = "done"
    status, independent, _ = post(base, cookie_b)
    assert status == 200 and independent.get("job_id") != first["job_id"]
    assert independent.get("deduplicated") is not True


def test_generation_requires_preissued_signed_session_and_rejects_long_request_id():
    payload = {**BASE, "generation_backend": "local", "client_request_id": "needs-session"}
    status, error, _ = post(payload, cookie="")
    assert status == 428
    assert error["error"] == "open the panel page before submitting a generation task"

    status, error, _ = post(payload, cookie="jt_session=forged-session-1234567890")
    assert status == 428

    status, error, _ = post({**payload, "client_request_id": "x" * 97})
    assert status == 400 and "client_request_id" in error["error"]


def test_creator_route_rejects_non_creator_workflow_and_recovering_blocks_without_id_leak():
    original = panel.WORKFLOWS["anima02"]
    panel.WORKFLOWS["not-creator"] = {
        "id": "not-creator", "name": "not creator", "kind": "video",
        "backend": "runninghub",
    }
    try:
        status, error, _ = post({
            **BASE, "workflow": "not-creator", "generation_backend": "local",
            "client_request_id": "wrong-route",
        })
        assert status == 400 and error["error"] == "not a creator image workflow"

        panel._jobs["private-recovering-job"] = {
            "id": "private-recovering-job", "status": "recovering",
            "generation_backend": "cloud", "request_session_hash": "other",
        }
        status, busy, _ = post({
            **BASE, "generation_backend": "cloud", "client_request_id": "blocked-recovery",
        })
        assert status == 429
        assert "running_job" not in busy and "private-recovering-job" not in json.dumps(busy)
    finally:
        panel.WORKFLOWS["anima02"] = original
        panel.WORKFLOWS.pop("not-creator", None)
        panel._jobs.pop("private-recovering-job", None)


def test_quota_counts_persisted_billable_jobs_only_and_records_private_session_hash():
    # Self-contained seed: no dependence on jobs created by earlier tests.
    # One synthetic billable cloud job (as register_billable_job persists it)
    # plus one local job without any quota fields.
    session_id = COOKIE.split("=", 1)[1]
    now = time.time()
    cloud_job = {
        "id": "quota-seed-cloud-job",
        "generation_backend": "cloud",
        "billable_quota_recorded": True,
        "created": now,
        "quota_session_hash": panel._session_hash(session_id),
        "status": "done",
    }
    local_job = {
        "id": "quota-seed-local-job",
        "generation_backend": "local",
        "status": "done",
    }
    with panel._lock_jobs:
        panel._jobs.clear()
        panel._jobs[cloud_job["id"]] = cloud_job
        panel._jobs[local_job["id"]] = local_job

    assert cloud_job.get("quota_session_hash") == panel._session_hash(session_id)
    assert local_job.get("quota_session_hash") is None
    status = panel.billable_quota_status(session_id)
    assert status["global_hour"] == 1 and status["global_day"] == 1
    assert status["session_hour"] == 1 and status["blocked"] is True


def test_release_gate_requires_rate_limits_when_auth_is_disabled():
    source = (ROOT / "server.py").read_text(encoding="utf8")
    assert "BILLABLE_GLOBAL_HOURLY_LIMIT" in source
    assert "BILLABLE_GLOBAL_DAILY_LIMIT" in source
    assert "BILLABLE_SESSION_HOURLY_LIMIT" in source
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "register_billable_job"]
    assert len(calls) == 4


def teardown_module():
    httpd.shutdown(); httpd.server_close(); thread.join(timeout=3)
