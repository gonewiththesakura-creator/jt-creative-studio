import base64
import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import threading
import time
import urllib.error
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_panel():
    # Keep this suite offline and independent from workstation/production secrets.
    names = ("PANEL_SESSION_SECRET", "PANEL_RELEASE_TOKEN")
    previous = {name: os.environ.get(name) for name in names}
    os.environ["PANEL_SESSION_SECRET"] = "offline-review-session-secret"
    os.environ["PANEL_RELEASE_TOKEN"] = "offline-review-release-token"
    try:
        spec = importlib.util.spec_from_file_location(
            "server_review_regressions_panel", ROOT / "server.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


PANEL = _load_panel()
RELEASE_TOKEN = "offline-review-release-token"
SESSION_ID = "review-regression-session-1234567890"


@pytest.fixture
def panel(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    favorites_dir = tmp_path / "favorites"
    jobs_dir.mkdir()
    favorites_dir.mkdir()
    monkeypatch.setattr(PANEL, "DATA_DIR", tmp_path)
    monkeypatch.setattr(PANEL, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(PANEL, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(PANEL, "FAVORITES_DIR", favorites_dir)
    monkeypatch.setattr(PANEL, "FAVORITES_FILE", tmp_path / "favorites.json")
    monkeypatch.setattr(PANEL, "UPLOAD_CAPABILITIES_FILE", tmp_path / "upload_capabilities.json")
    monkeypatch.setattr(PANEL, "UPLOAD_USAGE_FILE", tmp_path / "upload_usage.json")
    monkeypatch.setattr(PANEL, "_jobs", {})
    monkeypatch.setattr(PANEL, "_favorites", {})
    monkeypatch.setattr(PANEL, "_upload_capabilities", {})
    monkeypatch.setattr(PANEL, "_upload_usage", [])
    monkeypatch.setattr(PANEL, "BILLABLE_GLOBAL_HOURLY_LIMIT", 1000)
    monkeypatch.setattr(PANEL, "BILLABLE_GLOBAL_DAILY_LIMIT", 1000)
    monkeypatch.setattr(PANEL, "BILLABLE_SESSION_HOURLY_LIMIT", 1000)
    monkeypatch.setattr(PANEL, "run_job", lambda _job: None)
    if hasattr(PANEL, "PANEL_RELEASE_TOKEN"):
        monkeypatch.setattr(PANEL, "PANEL_RELEASE_TOKEN", RELEASE_TOKEN)
    if hasattr(PANEL, "RELEASE_DRAINING"):
        monkeypatch.setattr(PANEL, "RELEASE_DRAINING", False)
    if hasattr(PANEL, "_release_draining"):
        monkeypatch.setattr(PANEL, "_release_draining", False)
    return PANEL


@contextmanager
def running_server(panel):
    httpd = panel.BoundedHTTPServer(("127.0.0.1", 0), panel.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def request(httpd, method, path, payload=None, cookie=None, token=None):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = "Bearer " + token
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    result = response.status, raw, dict(response.getheaders())
    connection.close()
    return result


def json_request(httpd, method, path, payload=None, cookie=None, token=None):
    status, raw, headers = request(httpd, method, path, payload, cookie, token)
    return status, json.loads(raw or b"{}"), headers


def session_cookie(panel, session_id=SESSION_ID):
    return "jt_session=" + panel._encode_session_cookie(session_id)


def creator_payload(**changes):
    payload = {
        "workflow": "anima02",
        "prompt": "adult portrait in natural light",
        "negative_prompt": "text, watermark",
        "prompt_mode": "manual",
        "width": 768,
        "height": 1024,
        "batch": 1,
        "hd": 0,
        "seed": 321,
        "seed_mode": "fixed",
        "style_id": "sketch",
        "style_variant": "default",
        "mode": "character",
        "generation_backend": "local",
        "client_request_id": "review-creator-default",
    }
    payload.update(changes)
    return payload


def _corrupt_bytes_survive(directory, marker):
    return any(
        path.is_file() and marker in path.read_bytes()
        for path in directory.iterdir()
        if path.name.startswith("jobs")
    )


def test_dreamapi_ratio_allowlist_controls_server_dimensions(panel):
    ratios = {
        "1:1": (1024, 1024),
        "2:3": (1024, 1536),
        "3:2": (1536, 1024),
        "9:16": (864, 1536),
        "16:9": (1536, 864),
    }
    cookie = session_cookie(panel)
    with running_server(panel) as httpd:
        for index, (ratio, expected_size) in enumerate(ratios.items()):
            status, result, _ = json_request(
                httpd,
                "POST",
                "/api/generate",
                creator_payload(
                    generation_backend="api",
                    api_model="gpt-image-2",
                    api_quality="low",
                    api_fit="cover",
                    api_ratio=ratio,
                    # Deliberately valid but wrong: the server must ignore client pixels.
                    width=1600,
                    height=640,
                    client_request_id=f"review-api-ratio-{index}",
                ),
                cookie=cookie,
            )
            assert status == 200, (ratio, status, result)
            job = panel._jobs[result["job_id"]]
            assert (job["width"], job["height"]) == expected_size
            assert job["api_ratio"] == ratio
            job["status"] = "done"

        status, result, _ = json_request(
            httpd,
            "POST",
            "/api/generate",
            creator_payload(
                generation_backend="api",
                api_model="gpt-image-2",
                api_quality="low",
                api_fit="cover",
                api_ratio="4:5",
                width=1024,
                height=1024,
                client_request_id="review-api-ratio-rejected",
            ),
            cookie=cookie,
        )
        assert status == 400, result
        assert "ratio" in result["error"].lower()


@pytest.mark.parametrize("bad_seed", [0, -1, "not-a-seed", 9007199254740992])
def test_fixed_seed_rejects_invalid_values_instead_of_randomizing(panel, bad_seed):
    with running_server(panel) as httpd:
        status, result, _ = json_request(
            httpd,
            "POST",
            "/api/generate",
            creator_payload(seed=bad_seed, client_request_id=f"fixed-seed-{bad_seed}"),
            cookie=session_cookie(panel),
        )
    assert status == 400, result
    assert "seed" in result["error"].lower()
    assert panel._jobs == {}


def test_corrupt_jobs_file_recovers_from_backup_without_erasing_evidence(panel):
    corrupt = b'{"broken": '
    panel.JOBS_FILE.write_bytes(corrupt)
    recovered = {
        "kept-job": {
            "id": "kept-job",
            "status": "done",
            "workflow": "anima02",
            "images": [],
        }
    }
    backup_bytes = json.dumps(recovered).encode("utf-8")
    # Accept either conventional spelling while keeping the behavior assertion strict.
    panel.JOBS_FILE.with_suffix(".bak").write_bytes(backup_bytes)
    panel.JOBS_FILE.with_suffix(panel.JOBS_FILE.suffix + ".bak").write_bytes(backup_bytes)

    panel.load_jobs()

    assert panel._jobs == recovered
    assert _corrupt_bytes_survive(panel.JOBS_FILE.parent, corrupt)


def test_corrupt_jobs_and_backup_fail_closed_without_overwriting_input(panel):
    corrupt = b"not-json-primary"
    panel.JOBS_FILE.write_bytes(corrupt)
    panel.JOBS_FILE.with_suffix(".bak").write_bytes(b"not-json-backup")
    panel.JOBS_FILE.with_suffix(panel.JOBS_FILE.suffix + ".bak").write_bytes(
        b"not-json-backup"
    )

    with pytest.raises(RuntimeError, match="jobs|JSON|corrupt|backup"):
        panel.load_jobs()

    assert _corrupt_bytes_survive(panel.JOBS_FILE.parent, corrupt)
    assert panel._jobs == {}


def test_session_cookie_has_server_side_expiry(panel, monkeypatch):
    ttl = getattr(panel, "SESSION_COOKIE_TTL", 365 * 24 * 60 * 60)
    monkeypatch.setattr(panel.time, "time", lambda: 1_000_000)
    encoded = panel._encode_session_cookie(SESSION_ID)
    assert panel._decode_session_cookie(encoded) == SESSION_ID

    monkeypatch.setattr(panel.time, "time", lambda: 1_000_000 + ttl + 1)
    assert panel._decode_session_cookie(encoded) == ""


def test_legacy_session_cookie_is_accepted_once_and_refreshed(panel):
    signature = base64.urlsafe_b64encode(
        hmac.new(panel.SESSION_SECRET, SESSION_ID.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    legacy = SESSION_ID + "." + signature

    with running_server(panel) as httpd:
        status, _, headers = request(
            httpd, "GET", "/", cookie="jt_session=" + legacy
        )

    assert status == 200
    refreshed = headers.get("Set-Cookie", "")
    assert "jt_session=" in refreshed and "HttpOnly" in refreshed
    assert "SameSite=Strict" in refreshed and "Path=/" in refreshed
    refreshed_value = refreshed.split("jt_session=", 1)[1].split(";", 1)[0]
    assert refreshed_value != legacy
    assert panel._decode_session_cookie(refreshed_value) == SESSION_ID
    max_age = int(refreshed.split("Max-Age=", 1)[1].split(";", 1)[0])
    assert max_age >= 30 * 24 * 60 * 60


def test_jobs_history_filters_owner_before_applying_limit(panel):
    owner_hash = panel._session_hash(SESSION_ID)
    foreign_hash = panel._session_hash("foreign-review-session-1234567890")
    panel._jobs = {
        f"foreign-{index}": {
            "id": f"foreign-{index}",
            "workflow": "anima02",
            "style_id": "sketch",
            "status": "done",
            "created": 10_000 + index,
            "request_session_hash": foreign_hash,
        }
        for index in range(20)
    }
    panel._jobs["owned-old"] = {
        "id": "owned-old",
        "workflow": "anima02",
        "style_id": "sketch",
        "status": "done",
        "created": 1,
        "request_session_hash": owner_hash,
    }

    with running_server(panel) as httpd:
        status, result, _ = json_request(
            httpd,
            "GET",
            "/api/jobs?scope=creator",
            cookie=session_cookie(panel),
        )

    assert status == 200
    assert [row["id"] for row in result] == ["owned-old"]


def test_favorite_limit_is_per_owner_and_never_evicts_another_owner(panel, monkeypatch):
    monkeypatch.setattr(panel, "MAX_FAVORITES", 2)
    owner_a = panel._session_hash("favorite-owner-a-1234567890")
    owner_b = panel._session_hash("favorite-owner-b-1234567890")
    panel._favorites = {
        **{
            f"a-{index}": {
                "id": f"a-{index}",
                "created": index,
                "owner_session_hash": owner_a,
            }
            for index in range(3)
        },
        **{
            f"b-{index}": {
                "id": f"b-{index}",
                "created": index,
                "owner_session_hash": owner_b,
            }
            for index in range(2)
        },
    }

    panel.prune_favorites(owner_a)

    remaining_a = [row for row in panel._favorites.values()
                   if row["owner_session_hash"] == owner_a]
    remaining_b = [row for row in panel._favorites.values()
                   if row["owner_session_hash"] == owner_b]
    assert {row["id"] for row in remaining_a} == {"a-1", "a-2"}
    assert {row["id"] for row in remaining_b} == {"b-0", "b-1"}


def test_creator_favorite_snapshot_survives_sanitization_and_reload(panel):
    snapshot = {
        "source_page": "creator",
        "workflow": "anima02",
        "style": "cold",
        "style_variant": "character_bound",
        "mode": "character",
        "state": {"face": [["round face", "round face"]]},
        "locked": {"face": True},
        "width": 768,
        "height": 1024,
        "batch": 1,
        "hd": 0,
        "prompt_mode": "manual",
        "manual_positive": "adult portrait",
        "manual_negative": "watermark",
        "seed": 123456,
        "seed_mode": "fixed",
        "generation_backend": "api",
        "params": {},
        "media": {"secret": "api/provider-file.png"},
        "media_names": {},
    }
    expected = {
        key: snapshot[key]
        for key in (
            "style",
            "style_variant",
            "mode",
            "state",
            "locked",
            "width",
            "height",
            "batch",
            "hd",
            "prompt_mode",
            "manual_positive",
            "manual_negative",
            "seed",
            "seed_mode",
            "generation_backend",
        )
    }

    clean = panel.public_selection_snapshot(snapshot)
    assert {key: clean.get(key) for key in expected} == expected
    assert clean["media"] == {}

    favorite = {
        "fav": {
            "id": "fav",
            "created": 1,
            "owner_session_hash": panel._session_hash(SESSION_ID),
            "selection_snapshot": snapshot,
        }
    }
    panel.FAVORITES_FILE.write_text(json.dumps(favorite), encoding="utf-8")
    panel._favorites = {}
    panel.load_favorites()
    reloaded = panel._favorites["fav"]["selection_snapshot"]
    assert {key: reloaded.get(key) for key in expected} == expected
    assert reloaded["media"] == {}


def test_transient_rh_query_error_does_not_terminally_fail_accepted_task(panel, monkeypatch):
    attempts = []

    def flaky_query(task_id, job=None):
        attempts.append(task_id)
        if len(attempts) == 1:
            raise urllib.error.URLError("temporary query outage")
        return "SUCCESS", [{"url": "https://example.test/result.png", "fileType": "png"}]

    monkeypatch.setattr(panel, "rh_query", flaky_query)
    monkeypatch.setattr(panel.time, "sleep", lambda _seconds: None)
    job = {
        "id": "accepted-rh-task",
        "workflow": "realism_zi_flowmatch",
        "generation_backend": "cloud",
        "status": "recovering",
        "rh_task_id": "provider-task-123",
        "images": [],
    }
    panel._jobs[job["id"]] = job

    panel.resume_cloud_job(job)

    assert attempts == ["provider-task-123", "provider-task-123"]
    assert job["status"] == "done"
    assert job["provider_status"] == "DONE"
    assert job["error"] is None


def test_runninghub_images_and_videos_share_total_concurrency_limit(panel):
    panel._jobs = {
        "running-image": {
            "id": "running-image",
            "workflow": "realism_zi_flowmatch",
            "generation_backend": "cloud",
            "status": "running",
        },
        "running-video": {
            "id": "running-video",
            "workflow": "h3_t2v_i2v",
            "generation_backend": "cloud",
            "status": "running",
        },
    }
    payload = {
        "workflow": "h3_t2v_i2v",
        "prompt": "slow camera movement",
        "negative_prompt": "",
        "media": {},
        "params": {},
        "client_request_id": "third-runninghub-job",
    }

    with running_server(panel) as httpd:
        status, result, _ = json_request(
            httpd,
            "POST",
            "/api/video-generate",
            payload,
            cookie=session_cookie(panel),
        )

    assert status == 429, result
    assert len(panel._jobs) == 2


def test_management_endpoints_require_bearer_token(panel, monkeypatch):
    starts = []
    monkeypatch.setattr(panel, "get_lora_list", lambda: ["trusted.safetensors"])
    monkeypatch.setattr(
        panel,
        "start_comfy_remote",
        lambda: (starts.append("called") or True, "started"),
    )

    with running_server(panel) as httpd:
        lora_status, _, _ = json_request(httpd, "GET", "/api/loras")
        start_status, _, _ = json_request(httpd, "POST", "/api/comfy/start")
        assert lora_status == 401
        assert start_status == 401
        assert starts == []

        lora_status, loras, _ = json_request(
            httpd, "GET", "/api/loras", token=RELEASE_TOKEN
        )
        start_status, started, _ = json_request(
            httpd, "POST", "/api/comfy/start", token=RELEASE_TOKEN
        )
        assert lora_status == 200 and loras == {"loras": ["trusted.safetensors"]}
        assert start_status == 200 and started["started"] is True
        assert starts == ["called"]


def test_release_drain_is_loopback_only_authenticated_and_blocks_new_work(panel):
    loopback = getattr(panel, "_is_loopback_peer", None) or getattr(
        panel, "is_loopback_peer", None
    )
    assert callable(loopback), "release drain needs a directly testable loopback check"
    assert loopback("127.0.0.1") is True
    assert loopback("::1") is True
    assert loopback("10.0.0.1") is False

    with running_server(panel) as httpd:
        status, _, _ = json_request(
            httpd, "POST", "/api/admin/release-drain", {"enabled": True}
        )
        assert status == 401

        status, state, _ = json_request(
            httpd,
            "POST",
            "/api/admin/release-drain",
            {"enabled": True},
            token=RELEASE_TOKEN,
        )
        assert status == 200, state
        assert state["draining"] is True
        assert set(("draining", "cloud_busy", "local_busy", "api_busy")) <= set(state)

        status, result, _ = json_request(
            httpd,
            "POST",
            "/api/generate",
            creator_payload(client_request_id="blocked-by-release-drain"),
            cookie=session_cookie(panel),
        )
        assert status == 503, result
        assert "release_in_progress" in json.dumps(result)

        upload_status, upload_result, _ = json_request(
            httpd,
            "POST",
            "/api/workflow-upload",
            {},
            cookie=session_cookie(panel),
        )
        assert upload_status == 503, upload_result
        assert "release_in_progress" in json.dumps(upload_result)

        status, state, _ = json_request(
            httpd,
            "POST",
            "/api/admin/release-drain",
            {"enabled": False},
            token=RELEASE_TOKEN,
        )
        assert status == 200 and state["draining"] is False
