import base64
import http.client
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rh_upload_capabilities", ROOT / "server.py")
panel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(panel)

TMP = Path(tempfile.mkdtemp())
panel.DATA_DIR = TMP
panel.JOBS_DIR = TMP / "jobs"; panel.JOBS_DIR.mkdir()
panel.JOBS_FILE = TMP / "jobs.json"
panel.FAVORITES_DIR = TMP / "favorites"; panel.FAVORITES_DIR.mkdir()
panel.FAVORITES_FILE = TMP / "favorites.json"
panel.UPLOAD_CAPABILITIES_FILE = TMP / "upload_capabilities.json"
panel.UPLOAD_USAGE_FILE = TMP / "upload_usage.json"
panel._jobs = {}
panel._favorites = {}
panel._upload_capabilities = {}
panel._upload_usage = []
panel.run_job = lambda job: None

IMAGE_WF = {
    "id": "image_fixture", "name": "Image fixture", "desc": "test",
    "kind": "rh_workflow", "backend": "runninghub", "rh_workflow_id": "100",
    "rh_media": {"source_image": {"node": "1", "field": "image", "type": "image", "required": True, "label": "源图"}},
    "rh_params": {"instruction": {"node": "2", "field": "text", "type": "text", "required": True, "label": "指令"}},
}
OTHER_WF = {**IMAGE_WF, "id": "other_fixture", "rh_workflow_id": "101"}
VIDEO_WF = {
    "id": "video_fixture", "name": "Video fixture", "desc": "test",
    "kind": "video", "backend": "runninghub", "rh_workflow_id": "102",
    "rh_media": {
        "reference_image": {"node": "1", "field": "image", "type": "image", "required": True, "label": "参考图"},
        "driving_video": {"node": "2", "field": "video", "type": "video", "required": True, "label": "动作视频"},
    },
    "rh_params": {"prompt": {"node": "3", "field": "text", "type": "text", "required": True, "label": "提示词"}},
}
AI_APP_WF = {
    "id": "ai_fixture", "name": "AI fixture", "desc": "test",
    "kind": "ai_app", "backend": "runninghub", "rh_ai_app_id": "103",
    "rh_media": {"source_image": {"node": "1", "field": "image", "type": "image", "required": True, "label": "源图"}},
    "rh_params": {"requirements": {"node": "2", "field": "text", "type": "text", "allow_blank": True, "label": "要求"}},
    "params_defaults": {"requirements": ""},
}
panel.WORKFLOWS = dict(panel.WORKFLOWS)
panel.WORKFLOWS.update({w["id"]: w for w in (IMAGE_WF, OTHER_WF, VIDEO_WF, AI_APP_WF)})

uploaded = []
def fake_upload(data, filename, ctype, timeout=120):
    uploaded.append((filename, ctype, len(data)))
    return f"api/provider-private-{len(uploaded)}{Path(filename).suffix}"
panel.rh_upload_file = fake_upload

server = panel.BoundedHTTPServer(("127.0.0.1", 0), panel.Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

PNG = b"\x89PNG\r\n\x1a\n" + b"safe-fixture"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"safe-video-fixture"


def request(method, path, payload=None, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    body = None if payload is None else json.dumps(payload).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    raw = response.read()
    data = json.loads(raw or b"{}")
    set_cookie = response.getheader("Set-Cookie")
    status = response.status
    connection.close()
    return status, data, set_cookie


def cookie_pair(header):
    assert header
    return header.split(";", 1)[0]


def session_id(cookie):
    return panel._decode_session_cookie(cookie.split("=", 1)[1])


def upload(path, workflow, input_key, filename, data, cookie=None):
    return request("POST", path, {
        "workflow": workflow, "input_key": input_key, "filename": filename,
        "data": base64.b64encode(data).decode(),
    }, cookie)


def upload_with_headers(path, workflow, input_key, filename, data, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    raw = json.dumps({
        "workflow": workflow, "input_key": input_key, "filename": filename,
        "data": base64.b64encode(data).decode(),
    }).encode()
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection.request("POST", path, raw, headers)
    response = connection.getresponse()
    payload = json.loads(response.read() or b"{}")
    response_headers = dict(response.getheaders())
    status = response.status
    connection.close()
    return status, payload, response_headers


def image_generate(workflow, token, request_id, cookie):
    return request("POST", "/api/workflow-generate", {
        "workflow": workflow,
        "media": {"source_image": token},
        "params": {"instruction": "保持构图"},
        "client_request_id": request_id,
    }, cookie)


def video_generate(image_token, video_token, request_id, cookie):
    return request("POST", "/api/video-generate", {
        "workflow": "video_fixture", "prompt": "gentle motion",
        "media": {"reference_image": image_token, "driving_video": video_token},
        "params": {"prompt": "gentle motion"},
        "client_request_id": request_id,
    }, cookie)


def test_upload_returns_opaque_session_bound_capability_and_hides_provider_name():
    status, result, set_cookie = upload(
        "/api/workflow-upload", "image_fixture", "source_image", "safe.png", PNG
    )
    assert status == 200
    token = result["uploadToken"]
    assert token.startswith("upl_") and len(token) >= 40
    assert "fileName" not in result
    assert "provider-private" not in json.dumps(result)
    cookie = cookie_pair(set_cookie)

    status, accepted, _ = image_generate("image_fixture", token, "same-session", cookie)
    assert status == 200 and accepted.get("job_id")
    job = panel._jobs[accepted["job_id"]]
    assert job["provider_media"] == {"source_image": "api/provider-private-1.png"}
    assert "provider-private" not in json.dumps(job.get("media"), ensure_ascii=False)
    assert "provider-private" not in json.dumps(job.get("selection_snapshot"), ensure_ascii=False)

    status, public_job, _ = request("GET", "/api/job/" + accepted["job_id"], cookie=cookie)
    assert status == 200
    assert "provider-private" not in json.dumps(public_job)
    assert token not in json.dumps(public_job)


def test_workflow_bootstrap_sets_the_upload_session_before_parallel_uploads():
    status, workflows, set_cookie = request("GET", "/api/workflows")
    assert status == 200 and isinstance(workflows, list)
    assert set_cookie and "jt_session=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    assert session_id(cookie_pair(set_cookie))


def test_session_cookie_is_signed_and_tampering_is_rejected():
    _, _, set_cookie = request("GET", "/api/workflows")
    cookie = cookie_pair(set_cookie)
    encoded = cookie.split("=", 1)[1]
    assert "." in encoded
    assert panel._decode_session_cookie(encoded)
    tampered = encoded[:-1] + ("A" if encoded[-1] != "A" else "B")
    assert panel._decode_session_cookie(tampered) == ""


def test_public_uploads_are_bounded_per_session_and_globally(monkeypatch):
    panel._upload_usage = []
    monkeypatch.setattr(panel, "UPLOAD_SESSION_HOURLY_LIMIT", 1, raising=False)
    monkeypatch.setattr(panel, "UPLOAD_GLOBAL_HOURLY_LIMIT", 2, raising=False)
    monkeypatch.setattr(panel, "UPLOAD_SESSION_HOURLY_BYTES", 10_000_000, raising=False)
    monkeypatch.setattr(panel, "UPLOAD_GLOBAL_HOURLY_BYTES", 20_000_000, raising=False)

    _, _, set_cookie = request("GET", "/api/workflows")
    cookie_a = cookie_pair(set_cookie)
    before = len(uploaded)
    status, first, _ = upload_with_headers(
        "/api/workflow-upload", "image_fixture", "source_image", "a.png", PNG, cookie_a)
    assert status == 200 and first["uploadToken"].startswith("upl_")
    status, blocked, headers = upload_with_headers(
        "/api/workflow-upload", "image_fixture", "source_image", "b.png", PNG, cookie_a)
    assert status == 429 and blocked["scope"] == "session_hour"
    assert int(headers.get("Retry-After", "0")) > 0
    assert len(uploaded) == before + 1

    _, _, set_cookie = request("GET", "/api/workflows")
    cookie_b = cookie_pair(set_cookie)
    status, second, _ = upload_with_headers(
        "/api/workflow-upload", "image_fixture", "source_image", "c.png", PNG, cookie_b)
    assert status == 200 and second["uploadToken"].startswith("upl_")

    _, _, set_cookie = request("GET", "/api/workflows")
    cookie_c = cookie_pair(set_cookie)
    status, blocked, _ = upload_with_headers(
        "/api/workflow-upload", "image_fixture", "source_image", "d.png", PNG, cookie_c)
    assert status == 429 and blocked["scope"] == "global_hour"
    assert len(uploaded) == before + 2


def test_upload_usage_persists_across_restart_and_byte_limit_has_no_off_by_one(tmp_path, monkeypatch):
    panel.UPLOAD_USAGE_FILE = tmp_path / "upload_usage.json"
    panel._upload_usage = []
    monkeypatch.setattr(panel, "UPLOAD_SESSION_HOURLY_LIMIT", 20)
    monkeypatch.setattr(panel, "UPLOAD_GLOBAL_HOURLY_LIMIT", 100)
    monkeypatch.setattr(panel, "UPLOAD_SESSION_HOURLY_BYTES", len(PNG))
    monkeypatch.setattr(panel, "UPLOAD_GLOBAL_HOURLY_BYTES", 10 * len(PNG))

    session = "restart-quota-session"
    assert panel.reserve_upload_attempt(session, len(PNG), now=10000) is None
    assert panel.UPLOAD_USAGE_FILE.is_file()
    stored = json.loads(panel.UPLOAD_USAGE_FILE.read_text(encoding="utf8"))
    assert len(stored) == 1
    assert stored[0]["bytes"] == len(PNG)
    assert stored[0]["session_hash"] == panel._session_hash(session)

    panel._upload_usage = []
    monkeypatch.setattr(panel.time, "time", lambda: 10001)
    panel.load_upload_usage()
    blocked = panel.reserve_upload_attempt(session, 1, now=10001)
    assert blocked["scope"] == "session_bytes"
    assert blocked["retry_after"] > 0


def test_forged_cross_workflow_cross_slot_and_cross_session_capabilities_are_rejected():
    status, image, set_cookie = upload(
        "/api/workflow-upload", "image_fixture", "source_image", "safe.png", PNG
    )
    assert status == 200
    cookie = cookie_pair(set_cookie)
    token = image["uploadToken"]

    status, forged, _ = image_generate("image_fixture", "upl_" + "x" * 43, "forged", cookie)
    assert status == 400 and "upload" in forged["error"].lower()

    status, cross_workflow, _ = image_generate("other_fixture", token, "cross-workflow", cookie)
    assert status == 400 and "workflow" in cross_workflow["error"].lower()

    status, cross_session, _ = image_generate("image_fixture", token, "cross-session", "jt_session=another-session-id")
    assert status == 428 and "open the panel" in cross_session["error"].lower()

    status, video_image, _ = upload(
        "/api/upload", "video_fixture", "reference_image", "safe.png", PNG, cookie
    )
    assert status == 200
    status, video, _ = upload(
        "/api/upload", "video_fixture", "driving_video", "safe.mp4", MP4, cookie
    )
    assert status == 200
    status, cross_slot, _ = video_generate(
        video_image["uploadToken"], video_image["uploadToken"], "cross-slot", cookie)
    assert status == 400 and "input" in cross_slot["error"].lower()


def test_upload_rejects_unsafe_filenames_fake_media_and_mismatched_slot_before_provider_upload():
    before = len(uploaded)
    cases = [
        ("/api/workflow-upload", "image_fixture", "source_image", "../escape.png", PNG),
        ("/api/workflow-upload", "image_fixture", "source_image", 'bad\"\r\nX-Evil: 1.png', PNG),
        ("/api/workflow-upload", "image_fixture", "source_image", "fake.png", b"not-image"),
        ("/api/upload", "video_fixture", "driving_video", "fake.mp4", b"not-video"),
        ("/api/upload", "video_fixture", "reference_image", "video.mp4", MP4),
        ("/api/upload", "video_fixture", "driving_video", "image.png", PNG),
        ("/api/upload", "video_fixture", "not_a_slot", "safe.mp4", MP4),
    ]
    for path, workflow, input_key, filename, data in cases:
        status, result, _ = upload(path, workflow, input_key, filename, data)
        assert status == 400, (filename, status, result)
    assert len(uploaded) == before


def test_provider_upload_errors_are_not_reflected_to_public_clients(monkeypatch):
    monkeypatch.setattr(panel, "rh_upload_file", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("https://private.internal/path apiKey=super-secret node 123")))
    status, result, _ = upload(
        "/api/workflow-upload", "image_fixture", "source_image", "safe.png", PNG
    )
    assert status == 502
    assert result["error"] == "RunningHub上传失败，请稍后重试"
    raw = json.dumps(result)
    assert "private.internal" not in raw and "super-secret" not in raw and "node 123" not in raw


def test_valid_video_and_image_capabilities_submit_once_with_private_provider_values():
    status, image, set_cookie = upload(
        "/api/upload", "video_fixture", "reference_image", "reference.png", PNG
    )
    assert status == 200
    cookie = cookie_pair(set_cookie)
    status, video, _ = upload(
        "/api/upload", "video_fixture", "driving_video", "motion.mp4", MP4, cookie
    )
    assert status == 200
    status, accepted, _ = request("POST", "/api/video-generate", {
        "workflow": "video_fixture", "prompt": "gentle motion",
        "media": {"reference_image": image["uploadToken"], "driving_video": video["uploadToken"]},
        "params": {"prompt": "gentle motion"}, "client_request_id": "video-once",
        "selection_snapshot": {"media": {"reference_image": "api/attacker.png"}, "evil": "keep"},
    }, cookie)
    assert status == 200 and accepted.get("job_id")
    job = panel._jobs[accepted["job_id"]]
    assert set(job["provider_media"]) == {"reference_image", "driving_video"}
    assert all(value.startswith("api/provider-private-") for value in job["provider_media"].values())
    assert all("provider-private" not in value for value in job["media"].values())
    assert job["selection_snapshot"]["media"] == {}
    assert "attacker" not in json.dumps(job["selection_snapshot"])


def test_ai_app_upload_and_generate_use_the_same_private_capability_contract():
    for job in panel._jobs.values():
        job["status"] = "done"
    status, uploaded_image, set_cookie = upload(
        "/api/realcomic-upload", "ai_fixture", "source_image", "source.png", PNG
    )
    assert status == 200 and "uploadToken" in uploaded_image and "fileName" not in uploaded_image
    cookie = cookie_pair(set_cookie)
    payload = {
        "workflow": "ai_fixture", "media": {"source_image": uploaded_image["uploadToken"]},
        "params": {"requirements": ""}, "client_request_id": "ai-app-once",
        "selection_snapshot": {"media": {"source_image": uploaded_image["uploadToken"]}, "evil": "keep"},
    }
    status, accepted, _ = request("POST", "/api/ai-app-generate", payload, cookie)
    assert status == 200 and accepted.get("job_id")
    job = panel._jobs[accepted["job_id"]]
    assert job["provider_media"] == {"source_image": uploaded[-1] and f"api/provider-private-{len(uploaded)}.png"}
    assert job["media"] == {"source_image": "source.png"}
    assert job["selection_snapshot"]["media"] == {}
    assert uploaded_image["uploadToken"] not in json.dumps(job["selection_snapshot"])

    status, rejected, _ = request("POST", "/api/ai-app-generate", {
        **payload, "media": {"source_image": "api/forged.png"},
        "client_request_id": "ai-app-forged",
    }, cookie)
    assert status == 400 and "upload" in rejected["error"].lower()


def test_uploaded_workflow_idempotency_is_session_and_effective_payload_bound():
    for job in panel._jobs.values():
        job["status"] = "done"

    status, image_a, set_cookie = upload(
        "/api/workflow-upload", "image_fixture", "source_image", "a.png", PNG
    )
    assert status == 200
    cookie_a = cookie_pair(set_cookie)
    token_a = image_a["uploadToken"]
    request_id = "shared-uploaded-request-id"

    status, first, _ = image_generate("image_fixture", token_a, request_id, cookie_a)
    assert status == 200 and first.get("job_id")
    status, duplicate, _ = image_generate("image_fixture", token_a, request_id, cookie_a)
    assert status == 200 and duplicate["job_id"] == first["job_id"]
    assert duplicate["deduplicated"] is True

    status, conflict, _ = request("POST", "/api/workflow-generate", {
        "workflow": "image_fixture", "media": {"source_image": token_a},
        "params": {"instruction": "不同的有效指令"},
        "client_request_id": request_id,
    }, cookie_a)
    assert status == 409
    assert conflict["error"] == "client_request_id already used with different request payload"

    panel._jobs[first["job_id"]]["status"] = "done"
    status, image_b, set_cookie = upload(
        "/api/workflow-upload", "image_fixture", "source_image", "b.png", PNG
    )
    assert status == 200
    cookie_b = cookie_pair(set_cookie)
    status, independent, _ = image_generate(
        "image_fixture", image_b["uploadToken"], request_id, cookie_b)
    assert status == 200 and independent.get("job_id") != first["job_id"]
    assert independent.get("deduplicated") is not True


def test_video_idempotency_rejects_same_session_payload_drift():
    for job in panel._jobs.values():
        job["status"] = "done"
    status, image, set_cookie = upload(
        "/api/upload", "video_fixture", "reference_image", "idempotent.png", PNG
    )
    assert status == 200
    cookie = cookie_pair(set_cookie)
    status, video, _ = upload(
        "/api/upload", "video_fixture", "driving_video", "idempotent.mp4", MP4, cookie
    )
    assert status == 200
    request_id = "video-effective-request"
    status, first, _ = video_generate(
        image["uploadToken"], video["uploadToken"], request_id, cookie)
    assert status == 200 and first.get("job_id")
    status, duplicate, _ = video_generate(
        image["uploadToken"], video["uploadToken"], request_id, cookie)
    assert status == 200 and duplicate["job_id"] == first["job_id"]
    assert duplicate["deduplicated"] is True

    status, conflict, _ = request("POST", "/api/video-generate", {
        "workflow": "video_fixture", "prompt": "different valid motion",
        "media": {"reference_image": image["uploadToken"],
                  "driving_video": video["uploadToken"]},
        "params": {"prompt": "different valid motion"},
        "client_request_id": request_id,
    }, cookie)
    assert status == 409
    assert conflict["error"] == "client_request_id already used with different request payload"


def test_upload_capability_survives_restart_as_hash_only_and_main_loads_it(monkeypatch):
    token = panel.issue_upload_capability(
        "api/private-restart.png", "image_fixture", "source_image",
        "image", "restart.png", "restart-session-1234567890")
    raw = panel.UPLOAD_CAPABILITIES_FILE.read_text(encoding="utf8")
    assert token not in raw
    assert panel._upload_token_hash(token) in raw
    panel._upload_capabilities = {}
    panel.load_upload_capabilities()
    provider, public = panel.resolve_upload_capabilities(
        IMAGE_WF, {"source_image": token}, "restart-session-1234567890")
    assert provider == {"source_image": "api/private-restart.png"}
    assert public == {"source_image": "restart.png"}
    source = (ROOT / "server.py").read_text(encoding="utf8")
    main_body = source.split("def main():", 1)[1]
    assert "load_upload_capabilities()" in main_body


def test_public_job_and_history_strip_provider_media_tokens_and_snapshot_media():
    owner_id = "privacy-owner-session-1234567890"
    owner_cookie = "jt_session=" + panel._encode_session_cookie(owner_id)
    panel._jobs["private-job"] = {
        "id": "private-job", "workflow": "image_fixture", "status": "done",
        "generation_backend": "cloud", "created": 1,
        "request_session_hash": panel._session_hash(owner_id),
        "media": {"source_image": "api/legacy-media-secret.png"},
        "provider_media": {"source_image": "api/private-secret.png"},
        "rh_task_id": "2099999999999999999",
        "rh_task_ids": ["2099999999999999998"],
        "comfy_prompt_id": "provider-comfy-prompt-secret",
        "prompt_ids": ["provider-comfy-prompt-secret-2"],
        "api_response_id": "resp_provider_secret",
        "error": "RH task failed at node 123 SecretNode: internal traceback details",
        "selection_snapshot": {
            "source_page": "realism", "workflow": "image_fixture",
            "params": {}, "media": {"source_image": "api/legacy-private.png"},
            "media_names": {"source_image": "source.png"},
        },
        "images": [],
    }
    for path in ("/api/job/private-job", "/api/jobs?scope=realism"):
        status, result, _ = request("GET", path, cookie=owner_cookie)
        assert status == 200
        raw = json.dumps(result)
        rows = [result] if isinstance(result, dict) else result
        target = next(row for row in rows if row.get("id") == "private-job")
        assert "private-secret" not in raw
        assert "legacy-private" not in raw
        assert "provider_media" not in raw
        assert "legacy-media-secret" not in raw
        assert "2099999999999999999" not in raw
        assert "provider-comfy-prompt-secret" not in raw
        assert "resp_provider_secret" not in raw
        assert "SecretNode" not in raw and "node 123" not in raw
        assert target["error"] == "云端任务失败；请使用面板任务号 private-job 联系维护人员"
        for key in ("rh_task_id", "rh_task_ids", "comfy_prompt_id", "prompt_ids", "api_response_id"):
            assert key not in target
        assert target["selection_snapshot"]["media"] == {}
        assert target.get("media") in ({}, None)


def test_favorites_list_strips_legacy_provider_media_and_upload_tokens():
    owner_id = "favorite-owner-session-1234567890"
    owner_cookie = "jt_session=" + panel._encode_session_cookie(owner_id)
    panel._favorites = {
        "legacy": {
            "id": "legacy", "created": 1,
            "owner_session_hash": panel._session_hash(owner_id),
            "selection_snapshot": {
                "source_page": "realism", "workflow": "image_fixture", "params": {},
                "media": {"source_image": "api/legacy-private.png"},
                "media_names": {"source_image": "source.png"},
            },
            "image_url": "/api/favorite-image/legacy",
            "preview_url": "/api/favorite-preview/legacy",
            "image_path": r"C:\\private\\panel_data\\favorites\\legacy.png",
            "original_url": "https://provider.example/signed-private-result?token=secret",
            "provider_media": {"source_image": "api/private.png"},
        }
    }
    status, result, _ = request("GET", "/api/favorites", cookie=owner_cookie)
    assert status == 200
    raw = json.dumps(result)
    assert "legacy-private" not in raw and "upl_" not in raw
    assert "image_path" not in result[0]
    assert "original_url" not in result[0]
    assert "provider_media" not in result[0]
    assert "panel_data" not in raw and "provider.example" not in raw
    assert result[0]["image_url"] == "/api/favorite-image/legacy"
    assert result[0]["preview_url"] == "/api/favorite-preview/legacy"
    assert result[0]["selection_snapshot"]["media"] == {}


def test_cross_session_job_history_favorite_and_media_access_is_denied():
    owner_id = "owner-session-1234567890"
    owner_cookie = "jt_session=" + panel._encode_session_cookie(owner_id)
    attacker_cookie = "jt_session=" + panel._encode_session_cookie("attacker-session-1234567890")
    owner_hash = panel._session_hash(owner_id)
    favorite_file = panel.FAVORITES_DIR / "owned.png"
    favorite_file.write_bytes(PNG)
    panel._jobs["owned-job"] = {
        "id": "owned-job", "workflow": "image_fixture", "status": "done",
        "generation_backend": "cloud", "created": 1,
        "request_session_hash": owner_hash,
        "images": [{"url": "/api/image/owned-job/result.png", "file": "result.png"}],
    }
    panel._favorites = {
        "owned-favorite": {
            "id": "owned-favorite", "job_id": "owned-job", "image_index": 0,
            "created": 1, "owner_session_hash": owner_hash,
            "image_url": "/api/favorite-image/owned-favorite",
            "preview_url": "/api/favorite-preview/owned-favorite",
            "image_path": str(favorite_file), "favorite_media_type": "image/png",
            "selection_snapshot": {},
        }
    }
    for path in (
        "/api/job/owned-job", "/api/image/owned-job/result.png",
        "/api/local-preview/owned-job/result.webp",
    ):
        status, _, _ = request("GET", path, cookie=attacker_cookie)
        assert status in (403, 404), (path, status)
    status, history, _ = request("GET", "/api/jobs?scope=realism", cookie=attacker_cookie)
    assert status == 200 and not any(row.get("id") == "owned-job" for row in history)
    status, favorites, _ = request("GET", "/api/favorites", cookie=attacker_cookie)
    assert status == 200 and not any(row.get("id") == "owned-favorite" for row in favorites)
    for path in ("/api/favorite-image/owned-favorite", "/api/favorite-preview/owned-favorite"):
        status, _, _ = request("GET", path, cookie=attacker_cookie)
        assert status in (403, 404), (path, status)
    # Owner can still read metadata and favorite media.
    assert request("GET", "/api/job/owned-job", cookie=owner_cookie)[0] == 200
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    connection.request("GET", "/api/favorite-image/owned-favorite", headers={"Cookie": owner_cookie})
    response = connection.getresponse()
    payload = response.read()
    assert response.status == 200 and payload.startswith(b"\x89PNG\r\n\x1a\n")
    connection.close()


def teardown_module():
    server.shutdown(); server.server_close(); thread.join(timeout=3)
