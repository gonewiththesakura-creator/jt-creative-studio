import http.client
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dreamapi_http_server", ROOT / "server.py")
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
httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

BASE = {
    "workflow": "anima02",
    "prompt": "adult woman, ink illustration",
    "negative_prompt": "text, watermark",
    "prompt_mode": "options",
    "width": 768,
    "height": 1024,
    "batch": 1,
    "hd": 0,
    "seed": 321,
    "seed_mode": "fixed",
    "style_id": "sketch",
    "style_variant": "default",
    "mode": "character",
    "generation_backend": "api",
    "api_model": "gpt-image-2.5-flare",
    "api_quality": "high",
    "api_fit": "cover",
    "api_ratio": "9:16",
    "selection_snapshot": {
        "state": {},
        "api_model": "retired-image-model",
        "api_quality": "retired-quality",
        "api_fit": "stretch",
        "api_ratio": "4:5",
    },
    "client_request_id": "api-http-contract-1",
}


COOKIE = "jt_session=" + server._encode_session_cookie("dreamapi-http-session-1234567890")


def post(payload):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    raw = json.dumps(payload).encode()
    connection.request("POST", "/api/generate", raw, {"Content-Type": "application/json", "Cookie": COOKIE})
    response = connection.getresponse()
    data = json.loads(response.read())
    status = response.status
    connection.close()
    return status, data


def get(path):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    connection.request("GET", path, headers={"Cookie": COOKIE})
    response = connection.getresponse()
    data = json.loads(response.read())
    status = response.status
    connection.close()
    return status, data


def test_api_creator_submission_is_accepted_and_idempotent():
    status, data = post(BASE)
    assert status == 200, data
    job = server._jobs[data["job_id"]]
    assert job["generation_backend"] == "api"
    assert job["api_model"] == "gpt-image-2.5-flare"
    assert job["api_quality"] == "high"
    assert job["api_fit"] == "cover"
    assert job["api_transport"] == "images"
    assert job["api_dispatch_profile"] == "native_images"
    assert job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert job["api_action_mode"] == "direct"
    assert {
        key: job["selection_snapshot"][key]
        for key in ("api_model", "api_quality", "api_fit", "api_ratio")
    } == {
        "api_model": "gpt-image-2.5-flare",
        "api_quality": "high",
        "api_fit": "cover",
        "api_ratio": "9:16",
    }
    assert job["batch"] == 1
    assert job["hd"] == 0
    assert job["seed_supported"] is False

    repeat_status, repeat = post(BASE)
    assert repeat_status == 200
    assert repeat["job_id"] == data["job_id"]
    assert repeat["deduplicated"] is True
    assert len(server._jobs) == 1

    job["api_response_id"] = "resp_fixture"
    job["api_upstream_model"] = "unknown"
    job["api_upstream_quality"] = "high"
    job["api_upstream_size"] = "1024x1024"
    read_status, public = get("/api/job/" + job["id"])
    assert read_status == 200
    assert public["seed_supported"] is False
    assert public["api_model"] == "gpt-image-2.5-flare"
    assert public["api_quality"] == "high"
    assert public["api_fit"] == "cover"
    assert public["api_transport"] == "images"
    assert public["api_dispatch_profile"] == "native_images"
    assert public["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert public["api_action_mode"] == "direct"
    assert job["api_response_id"] == "resp_fixture"
    assert "api_response_id" not in public
    assert job["prompt"] == BASE["prompt"]
    assert "prompt" not in public
    assert "negative_prompt" not in public

    history_status, history = get("/api/jobs?scope=creator")
    assert history_status == 200
    history_job = next(row for row in history if row["id"] == job["id"])
    assert history_job["api_upstream_model"] == "unknown"
    assert history_job["api_upstream_quality"] == "high"
    assert history_job["api_upstream_size"] == "1024x1024"
    assert history_job["api_transport"] == "images"
    assert history_job["api_dispatch_profile"] == "native_images"
    assert history_job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert history_job["api_action_mode"] == "direct"


def test_api_creator_rejects_non_single_batch_and_hd():
    for field, value, expected in [
        ("batch", 2, "one image"),
        ("hd", 1, "HD"),
    ]:
        payload = {**BASE, "client_request_id": f"api-bad-{field}", field: value}
        status, data = post(payload)
        assert status == 400, (field, status, data)
        assert expected.lower() in data["error"].lower()


def test_api_creator_rejects_untrusted_model_quality_fit_and_ratio():
    cases = [
        ({"api_model": "gpt-image-private"}, "model"),
        ({"api_model": "gpt-image-2", "api_quality": "max"}, "quality"),
        ({"api_fit": "stretch"}, "fit"),
        ({"api_ratio": "4:5"}, "ratio"),
    ]
    for index, (change, expected) in enumerate(cases):
        payload = {**BASE, "client_request_id": f"api-bad-option-{index}", **change}
        status, data = post(payload)
        assert status == 400, (change, status, data)
        assert expected.lower() in data["error"].lower()


def test_api_creator_rejects_oversized_prompts_before_accepting_a_paid_job():
    for field in ("prompt", "negative_prompt"):
        payload = {**BASE, "client_request_id": "api-long-" + field, field: "x" * 12001}
        status, data = post(payload)
        assert status == 400
        assert "too long" in data["error"].lower()


def test_api_creator_accepts_long_panel_prompt_for_worker_compaction():
    for job in server._jobs.values():
        job["status"] = "done"
    payload = {**BASE, "client_request_id": "api-worker-compaction", "prompt": "x" * 3690}
    status, data = post(payload)
    assert status == 200
    job = server._jobs[data["job_id"]]
    assert len(job["prompt"]) == 3690
    job["status"] = "done"


def test_existing_cloud_and_local_prompt_limits_are_not_changed_by_api_channel():
    for backend in ("cloud", "local"):
        payload = {
            **BASE,
            "generation_backend": backend,
            "client_request_id": "long-existing-" + backend,
            "prompt": "x" * 2001,
        }
        status, data = post(payload)
        assert status == 200, (backend, status, data)
        server._jobs[data["job_id"]]["status"] = "done"


def test_extreme_numeric_strings_are_rejected_before_integer_conversion():
    huge = "9" * 1000
    # API pixel fields are no longer part of the contract; the server ignores
    # them and derives dimensions exclusively from api_ratio.
    for index, field in enumerate(("batch", "hd")):
        payload = {**BASE, "client_request_id": f"api-huge-number-{index}", field: huge}
        status, data = post(payload)
        assert status == 400, (field, status, data)
        assert data["error"] == "invalid numeric parameters"


def teardown_module():
    httpd.shutdown()
    httpd.server_close()
