"""Account boundary tests through the real bounded HTTP server, fully offline."""
import copy
import http.client
import json
import secrets
from types import SimpleNamespace
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from membership_http import MembershipGateway
from membership_store import MembershipStore
from test_server_review_regressions import creator_payload, panel, running_server


class FakeOIDC:
    public_origin = "https://jt.example"
    issuer = "https://login.example"
    client_id = "jt-test-client"

    def __init__(self):
        self.authorizations = []
        self.exchanges = []

    def authorization_url(self, state, nonce, verifier):
        self.authorizations.append((state, nonce, verifier))
        return self.issuer + "/authorize?" + urlencode({"state": state, "nonce": nonce})

    def exchange(self, code, verifier, nonce):
        self.exchanges.append((code, verifier, nonce))
        assert code == "valid-authorization-code"
        return {"iss": self.issuer, "sub": "alice", "name": "Alice", "email": "alice@example.test"}


@pytest.fixture
def membership_env(panel, tmp_path, monkeypatch):
    monkeypatch.setenv("JT_MEMBERSHIP_ENABLED", "1")
    store = MembershipStore(tmp_path / "membership.sqlite3")
    oidc = FakeOIDC()
    gateway = MembershipGateway(tmp_path, store=store, oidc=oidc)
    gateway.reservations_callback = panel.membership_reservations
    users = {name: store.upsert_identity(oidc.issuer, name, name.title()) for name in ("admin", "alice", "bob")}
    users["admin"] = store.bootstrap_admin(users["admin"]["id"])
    # Management fixtures represent a fresh, trusted administrator OIDC login.
    # Dedicated adversarial tests exercise unverified legacy/code sessions.
    sessions = {name: store.create_session(user["id"], oidc_verified=name == "admin") for name, user in users.items()}
    monkeypatch.setattr(panel, "_membership", gateway)
    provider_calls = []

    def forbidden_provider(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("A rejected request must never invoke a provider")

    for name in ("run_job", "rh_upload_file", "rh_upload_temp_file", "download_file_resilient"):
        monkeypatch.setattr(panel, name, forbidden_provider)
    media_calls = []

    def fake_stream(handler, url, filename, **kwargs):
        media_calls.append((url, filename))
        return handler._send(200, b"private-output-bytes", "video/mp4")

    monkeypatch.setattr(panel, "stream_media", fake_stream)
    workflows = copy.deepcopy(panel.WORKFLOWS)
    for name, kind in (("member-workflow", "rh_workflow"), ("member-ai", "ai_app"), ("member-video", "video")):
        workflows[name] = {
            "id": name, "name": name, "kind": kind, "backend": "runninghub", "rh_workflow_id": "fixture-1",
            "rh_ai_app_id": "fixture-2", "rh_media": {},
            "rh_params": {"prompt": {"node": "1", "field": "text", "type": "text", "allow_blank": True}},
        }
    workflows["member-upload"] = {
        "id": "member-upload", "name": "upload fixture", "kind": "rh_workflow", "backend": "runninghub",
        "rh_workflow_id": "fixture-3", "rh_params": {},
        "rh_media": {"source_image": {"node": "1", "field": "image", "type": "image", "required": True}},
    }
    monkeypatch.setattr(panel, "WORKFLOWS", workflows)
    with running_server(panel) as httpd:
        yield SimpleNamespace(panel=panel, store=store, oidc=oidc, gateway=gateway, users=users, sessions=sessions,
                              httpd=httpd, provider_calls=provider_calls, media_calls=media_calls)
    assert not provider_calls, "No test is authorized to submit paid work or transfer material to a provider"


def request(env, method, path, payload=None, user=None, headers=None, raw=None):
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    request_headers = {"Host": "jt.example"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if user:
        session = env.sessions[user]
        request_headers["Cookie"] = env.gateway.COOKIE + "=" + session["token"]
        if method != "GET":
            request_headers["Origin"] = env.gateway.origin
            request_headers["X-CSRF-Token"] = session["csrf"]
    for key, value in (headers or {}).items():
        if value is None:
            request_headers.pop(key, None)
        else:
            request_headers[key] = value
    connection = http.client.HTTPConnection("127.0.0.1", env.httpd.server_port, timeout=10)
    try:
        # Avoid a Windows TCP reset when an early denial closes the connection
        # between http.client's separate header and body writes. Assertions and
        # server authentication remain unchanged; send the fixture atomically.
        send = connection.send
        packet = bytearray()
        connection.send = packet.extend
        connection.request(method, path, body, request_headers)
        connection.send = send
        connection.send(packet)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheaders()
        return result
    finally:
        connection.close()


def json_request(env, method, path, payload=None, user=None, headers=None, raw=None):
    status, body, response_headers = request(env, method, path, payload, user, headers, raw)
    return status, json.loads(body or b"{}"), dict(response_headers)


def activate(env, user="alice", image_units=10, video_units=10, **changes):
    plan = env.store.save_plan(env.users["admin"]["id"], {
        "name": "Test", "duration_days": 30, "image_units": image_units, "video_units": video_units,
        "backends": ["cloud", "api", "local"], **changes,
    })
    code = env.store.issue_codes(env.users["admin"]["id"], plan["id"])[0]["code"]
    env.store.redeem(env.users[user]["id"], code)
    return plan


def put_job(env, owner="alice", job_id="a" * 12, status="done", **changes):
    job = {"id": job_id, "workflow": "member-video", "wf_name": "Test video", "style_id": "video",
           "status": status, "created": time.time(), "generation_backend": "cloud", "video_queued": True,
           "queue_revision": 0, "request_session_hash": env.panel._session_hash(env.users[owner]["owner_key"]),
           "images": [{"remote": True, "url": "https://provider.example/private-output.mp4", "file": "result.mp4", "file_type": "mp4"}],
           "prompt": "private prompt", "params": {"prompt": "private prompt"}, **changes}
    env.panel._jobs[job_id] = job
    return job


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/jobs", None), ("GET", "/api/job/aaaaaaaaaaaa", None),
    ("GET", "/api/video-queue", None), ("GET", "/api/favorites", None),
    ("GET", "/api/favorite-image/aaaaaaaaaaaa", None), ("GET", "/api/result-media/aaaaaaaaaaaa/0", None),
    ("POST", "/api/generate", {}), ("POST", "/api/video-generate", {}),
    ("POST", "/api/workflow-generate", {}), ("POST", "/api/ai-app-generate", {}),
    ("POST", "/api/workflow-upload", {}), ("POST", "/api/upload-start", {}),
])
def test_anonymous_cannot_read_or_mutate_private_apis(membership_env, method, path, payload):
    env = membership_env
    put_job(env)
    status, result, _ = json_request(env, method, path, payload)
    assert status == 401 and result["code"] == "login_required"


def test_tasks_queue_favorites_and_media_are_isolated_between_accounts(membership_env):
    env = membership_env
    activate(env, user="bob")
    alice = put_job(env)
    put_job(env, "bob", "b" * 12)
    queued = put_job(env, job_id="c" * 12, status="queued", images=[])
    private_file = env.panel.FAVORITES_DIR / "favorite.mp4"
    private_file.write_bytes(b"private-favorite-bytes")
    env.panel._favorites["d" * 12] = {"id": "d" * 12, "job_id": alice["id"], "created": time.time(),
        "owner_session_hash": alice["request_session_hash"], "image_path": str(private_file),
        "original_url": "https://provider.example/private-favorite.mp4", "favorite_media_type": "video/mp4",
        "image_url": "/api/favorite-image/" + "d" * 12}
    for path in ("/api/jobs?scope=video&limit=30", "/api/video-queue"):
        status, result, _ = json_request(env, "GET", path, user="bob")
        rows = result["jobs"] if isinstance(result, dict) else result
        assert status == 200 and {row["id"] for row in rows} == {"b" * 12}
    assert json_request(env, "GET", "/api/favorites", user="bob")[1] == []
    for path in ("/api/job/" + alice["id"], "/api/result-media/" + alice["id"] + "/0",
                 "/api/rh-preview/" + alice["id"] + "/0", "/api/image/" + alice["id"] + "/secret.png",
                 "/api/preview/" + alice["id"] + "/secret.png", "/api/favorite-image/" + "d" * 12,
                 "/api/favorite-preview/" + "d" * 12):
        assert request(env, "GET", path, user="bob")[0] == 404
    assert json_request(env, "POST", "/api/favorites", {"job_id": alice["id"], "image_index": 0}, "bob")[0] == 404
    assert json_request(env, "POST", "/api/video-queue", {"job_id": queued["id"], "action": "cancel", "revision": 0}, "bob")[0] == 404
    assert json_request(env, "POST", "/api/video-generate", {"redo_job_id": alice["id"], "client_request_id": "steal-redo"}, "bob")[0] == 404
    assert queued["status"] == "queued" and not env.media_calls
    status, details, _ = json_request(env, "GET", "/api/job/" + alice["id"], user="alice")
    assert status == 200 and details["images"][0]["url"] == "/api/result-media/" + alice["id"] + "/0"
    assert "provider.example" not in json.dumps(details)
    status, body, _ = request(env, "GET", details["images"][0]["url"], user="alice")
    assert status == 200 and body == b"private-output-bytes" and len(env.media_calls) == 1
    status, favorites, _ = json_request(env, "GET", "/api/favorites", user="alice")
    assert status == 200 and "original_url" not in favorites[0] and "owner_session_hash" not in favorites[0]


def test_upload_capabilities_cannot_be_replayed_by_other_account(membership_env):
    env = membership_env
    activate(env, "bob")
    token = env.panel.issue_upload_capability("provider-private-file.png", "member-upload", "source_image", "image", "reference.png", env.users["alice"]["owner_key"])
    status, result, _ = json_request(env, "POST", "/api/workflow-generate", {
        "workflow": "member-upload", "media": {"source_image": token}, "params": {}, "client_request_id": "stolen-upload",
    }, "bob")
    assert status == 400 and "session mismatch" in result["error"]
    assert not env.panel._jobs and not env.store.list_unsettled_reservations()
    for path in ("/api/upload-direct-start", "/api/upload-direct-register", "/api/upload-direct-verify"):
        assert json_request(env, "POST", path, {}, "bob")[0] == 410


@pytest.mark.parametrize("route,workflow,backend", [
    ("/api/generate", "anima02", "cloud"), ("/api/generate", "anima02", "local"),
    ("/api/generate", "anima02", "api"), ("/api/workflow-generate", "member-workflow", "cloud"),
    ("/api/ai-app-generate", "member-ai", "cloud"), ("/api/video-generate", "member-video", "cloud"),
])
@pytest.mark.parametrize("has_plan", [False, True])
def test_all_generation_routes_reject_missing_plan_or_exhausted_units(membership_env, route, workflow, backend, has_plan):
    env = membership_env
    if has_plan:
        activate(env, image_units=0, video_units=0)
    payload = creator_payload(generation_backend=backend, api_model="gpt-image-2.5-flare", api_quality="medium") if route == "/api/generate" else {
        "workflow": workflow, "prompt": "safe prompt", "media": {}, "params": {}, "client_request_id": "blocked-generation",
    }
    status, result, _ = json_request(env, "POST", route, payload, "alice")
    assert status == 403, result
    assert result["code"] == ("quota_exhausted" if has_plan else "plan_required")
    assert not env.panel._jobs and not env.store.list_unsettled_reservations()


def test_account_session_and_csrf_survive_restart_but_logout_revokes(membership_env):
    env = membership_env
    status, me, _ = json_request(env, "GET", "/api/auth/me", user="alice")
    assert status == 200 and me["authenticated"] and me["csrf_token"] == env.sessions["alice"]["csrf"]
    assert "owner_key" not in me["user"] and "subject" not in me["user"]
    old_token = env.sessions["alice"]["token"]
    for changes, expected in (({"X-CSRF-Token": None}, "invalid_csrf"),
                              ({"X-CSRF-Token": env.sessions["bob"]["csrf"]}, "invalid_csrf"),
                              ({"Origin": "https://evil.example"}, "invalid_origin"),
                              ({"Origin": None}, "invalid_origin")):
        status, result, _ = json_request(env, "POST", "/api/auth/logout", {}, "alice", changes)
        assert status == 403 and result["code"] == expected
        assert env.store.get_session(old_token)
    env.gateway.store = MembershipStore(env.store.path)
    assert json_request(env, "GET", "/api/auth/me", user="alice")[1]["authenticated"]
    status, result, headers = json_request(env, "POST", "/api/auth/logout", {}, "alice")
    assert status == 200 and result["ok"] and "Max-Age=0" in headers["Set-Cookie"]
    assert env.store.get_session(old_token) is None
    assert json_request(env, "GET", "/api/jobs", user="alice")[0] == 401


def test_login_state_is_browser_bound_single_use_and_rotates_session(membership_env):
    env = membership_env
    status, _, headers = json_request(env, "GET", "/api/auth/login?return_to=%2Fvideo")
    assert status == 302
    state = parse_qs(urlsplit(headers["Location"]).query)["state"][0]
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert cookie.startswith(env.gateway.STATE_COOKIE + "=")
    assert all(flag in headers["Set-Cookie"] for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"))
    callback = "/api/auth/callback?" + urlencode({"state": state, "code": "valid-authorization-code"})
    assert json_request(env, "GET", callback)[0] == 400
    assert not env.oidc.exchanges
    old_token = env.sessions["alice"]["token"]
    old_cookie = env.gateway.COOKIE + "=" + old_token
    status, _, response_headers = request(env, "GET", callback, headers={"Cookie": cookie + "; " + old_cookie})
    assert status == 302 and dict(response_headers)["Location"] == "/video"
    set_cookies = [value for key, value in response_headers if key.lower() == "set-cookie"]
    account_cookie = next(value for value in set_cookies if value.startswith(env.gateway.COOKIE + "="))
    new_token = account_cookie.split(";", 1)[0].split("=", 1)[1]
    assert new_token != old_token and env.store.get_session(old_token) is None
    assert env.store.get_session(new_token)["user"]["id"] == env.users["alice"]["id"]
    assert json_request(env, "GET", callback, headers={"Cookie": cookie})[0] == 400
    assert len(env.oidc.exchanges) == 1
