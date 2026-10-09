import http.client
import json
import time

import pytest

from test_membership_http import activate, json_request, membership_env, put_job, request
from test_server_review_regressions import panel


def test_anonymous_liveness_retains_production_watchdog_contract(membership_env):
    env = membership_env
    status, raw, _ = request(env, "GET", "/api/live")
    result = json.loads(raw)
    assert status == 200 and result["ok"] is True
    assert result["service"] == "comfy-panel"
    assert b'"service":"comfy-panel"' in raw
    assert "active_workers" in result and "max_workers" in result
    assert "Set-Cookie" not in dict(request(env, "GET", "/api/live")[2])
    assert not env.oidc.authorizations and not env.oidc.exchanges


def test_security_headers_and_host_validation_cover_success_error_and_callback(membership_env):
    env = membership_env
    for path in ("/", "/api/auth/me", "/api/jobs", "/api/auth/callback?state=wrong&code=wrong"):
        status, _, headers = request(env, "GET", path)
        headers = {key.lower(): value for key, value in headers}
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["strict-transport-security"].startswith("max-age=")
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "object-src 'none'" in headers["content-security-policy"]
    status, result, _ = json_request(env, "GET", "/api/jobs", user="alice", headers={"Host": "evil.example"})
    assert status == 400 and result["code"] == "invalid_host"
    status, result, _ = json_request(env, "GET", "/api/health", user="alice")
    assert status == 200 and result == {"ok": True, "authenticated": True}


def test_admin_issuance_redemption_and_disable_use_server_authority(membership_env):
    env = membership_env
    for method, path, payload in (("GET", "/api/admin/membership/users", None),
                                  ("GET", "/api/admin/membership/codes", None),
                                  ("GET", "/api/admin/membership/audit", None),
                                  ("POST", "/api/admin/membership/plans", {"name": "free", "duration_days": 30}),
                                  ("POST", "/api/admin/membership/users/disable", {"user_id": env.users["admin"]["id"], "disabled": True})):
        assert json_request(env, method, path, payload, "alice")[0] == 403
    status, created, _ = json_request(env, "POST", "/api/admin/membership/plans", {
        "name": "Offline activation", "duration_days": 30, "image_units": 12, "video_units": 3, "max_concurrent": 1,
    }, "admin")
    assert status == 200
    status, issued, _ = json_request(env, "POST", "/api/admin/membership/codes", {"plan_id": created["plan"]["id"], "count": 1}, "admin")
    assert status == 200
    code = issued["codes"][0]["code"]
    status, metadata, _ = json_request(env, "GET", "/api/admin/membership/codes", user="admin")
    assert status == 200 and code not in json.dumps(metadata) and "code_hash" not in json.dumps(metadata)
    status, result, _ = json_request(env, "POST", "/api/membership/redeem", {"code": code}, "alice")
    assert status == 200 and result["membership"]["image_remaining"] == 12
    assert json_request(env, "POST", "/api/membership/redeem", {"code": code}, "bob")[0] == 400
    assert json_request(env, "GET", "/api/auth/me", user="alice")[1]["user"]["is_admin"] is False
    status, _, _ = json_request(env, "POST", "/api/admin/membership/users/disable", {"user_id": env.users["alice"]["id"], "disabled": True}, "admin")
    assert status == 200 and json_request(env, "GET", "/api/jobs", user="alice")[0] == 401


@pytest.mark.parametrize("path,payload", [
    ("/api/admin/membership/codes", {"plan_id": [], "count": 1}),
    ("/api/admin/membership/codes/revoke", {"code_id": {"bad": "type"}}),
    ("/api/admin/membership/users/disable", {"user_id": [], "disabled": True}),
    ("/api/admin/membership/plans", {"plan_id": [], "name": "plan", "duration_days": 1}),
    ("/api/admin/membership/plans", {"name": "plan", "duration_days": True}),
    ("/api/admin/membership/codes", {"plan_id": "missing", "count": True}),
    ("/api/admin/membership/users/disable", {"user_id": "missing", "disabled": "true"}),
    ("/api/admin/membership/plans", []),
    ("/api/membership/redeem", {"code": ["not-a-code"]}),
])
def test_membership_admin_json_schema_rejects_bad_types_without_crashing(membership_env, path, payload):
    status, result, _ = json_request(membership_env, "POST", path, payload, "admin")
    assert status == 400 and result["error"]


@pytest.mark.parametrize("route", ["/api/generate", "/api/workflow-generate", "/api/ai-app-generate", "/api/video-generate"])
def test_generation_requires_json_object(membership_env, route):
    status, result, _ = json_request(membership_env, "POST", route, ["not-an-object"], "alice")
    assert status == 400 and result["error"]


def test_activation_attempts_are_limited_and_legacy_cookie_does_not_authenticate(membership_env):
    env = membership_env
    for _ in range(10):
        status, _, _ = json_request(env, "POST", "/api/membership/redeem", {"code": "invalid"}, "alice")
        assert status == 400
    status, result, _ = json_request(env, "POST", "/api/membership/redeem", {"code": "invalid"}, "alice")
    assert status == 429 and result["code"] == "rate_limited"
    legacy = "jt_session=" + env.panel._encode_session_cookie(env.users["alice"]["owner_key"])
    assert json_request(env, "GET", "/api/jobs", headers={"Cookie": legacy})[0] == 401


def test_disabling_feature_blocks_upload_before_any_provider_call(membership_env):
    env = membership_env
    activate(env, features=["image"])
    for path in ("/api/workflow-upload", "/api/realcomic-upload", "/api/upload", "/api/upload-start"):
        status, result, _ = json_request(env, "POST", path, {}, "alice")
        assert status == 403 and result["code"] == "feature_forbidden"


def test_read_only_account_can_read_own_results_without_active_plan(membership_env):
    env = membership_env
    job = put_job(env)
    status, result, _ = json_request(env, "GET", "/api/job/" + job["id"], user="alice")
    assert status == 200 and result["id"] == job["id"]
    assert env.store.get_entitlement(env.users["alice"]["id"]) is None


def test_malformed_non_ascii_csrf_and_state_fail_without_crashing(membership_env):
    env = membership_env
    status, result, _ = json_request(env, "POST", "/api/auth/logout", {}, "alice", {"X-CSRF-Token": "é"})
    assert status == 403 and result["code"] == "invalid_csrf"
    status, result, _ = json_request(env, "GET", "/api/auth/callback?state=%C3%A9&code=unused", headers={
        "Cookie": env.gateway.STATE_COOKIE + "=ascii-cookie-value"})
    assert status == 400 and result["code"] == "invalid_login_state"
    assert env.store.get_session(env.sessions["alice"]["token"])
    assert not env.oidc.exchanges


def test_admin_rejects_unknown_fields_instead_of_accepting_privilege_hints(membership_env):
    env = membership_env
    plan = activate(env)
    status, result, _ = json_request(env, "POST", "/api/admin/membership/codes", {
        "plan_id": plan["id"], "count": 1, "is_admin": True,
    }, "admin")
    assert status == 400 and result["error"]
    assert len(env.store.list_codes(env.users["admin"]["id"])) == 1


def test_failed_job_ledger_write_refunds_reserved_units(membership_env, monkeypatch):
    env = membership_env
    activate(env)
    job = {"id": "f" * 12, "style_id": "video", "generation_backend": "cloud", "video_queued": True}
    before = env.store.get_entitlement(env.users["alice"]["id"])["video_available"]

    def cannot_save():
        raise OSError("isolated simulated disk failure")

    monkeypatch.setattr(env.panel, "save_jobs", cannot_save)
    with pytest.raises(OSError):
        env.panel.register_billable_job(job, env.users["alice"]["owner_key"])
    assert job["id"] not in env.panel._jobs
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == before
    assert env.store.get_reservation(job["id"])["state"] == "refunded"


def reserve_review_job(env, job_id="e" * 12, **changes):
    job = put_job(env, job_id=job_id, status="error", membership_reserved=True,
                  submit_started=time.time(), **changes)
    env.store.reserve_job(env.users["alice"]["id"], job_id, "video")
    env.store.start_job(job_id)
    return job


def test_admin_quota_review_is_private_and_cannot_be_used_by_members(membership_env):
    env = membership_env
    activate(env)
    job = reserve_review_job(env, provider_started=time.time())
    for user, status in ((None, 401), ("alice", 403), ("bob", 403)):
        assert json_request(env, "GET", "/api/admin/membership/reservations", user=user)[0] == status
        assert json_request(env, "POST", "/api/admin/membership/reservations/settle", {
            "job_id": job["id"], "success": False, "note": "已核对云端真实记录确认未产生结果",
        }, user)[0] == status
    status, result, _ = json_request(env, "GET", "/api/admin/membership/reservations", user="admin")
    assert status == 200 and len(result["reservations"]) == 1
    row = result["reservations"][0]
    assert row["job_id"] == job["id"] and row["can_settle"] is True
    assert "provider.example" not in json.dumps(result) and "owner_key" not in json.dumps(result)
    assert env.store.get_reservation(job["id"])["state"] == "running"


@pytest.mark.parametrize("changes", [
    {"status": "running"}, {"status": "recovering"}, {"status": "queued"},
    {"queue_hold": True}, {"generation_backend": "api", "api_pending_until": time.time() + 3600},
])
def test_admin_review_refuses_active_or_fenced_work(membership_env, changes):
    env = membership_env
    activate(env)
    job = reserve_review_job(env)
    job.update(changes)
    status, result, _ = json_request(env, "POST", "/api/admin/membership/reservations/settle", {
        "job_id": job["id"], "success": False, "note": "已核对云端真实记录确认未产生结果",
    }, "admin")
    assert status == 409 and result["code"] == "job_not_settleable"
    assert env.store.get_reservation(job["id"])["state"] == "running"
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == 9
    assert not any(row["action"] == "job_settle" for row in env.store.list_audit(env.users["admin"]["id"]))


def test_admin_review_idempotence_and_schema_are_enforced_over_http(membership_env):
    env = membership_env
    activate(env)
    job = reserve_review_job(env)
    valid = {"job_id": job["id"], "success": False, "note": "已核对云端真实记录确认未产生结果"}
    for invalid in ({"job_id": []}, {"success": "false"}, {"note": "不够长"}, {"force": True}):
        assert json_request(env, "POST", "/api/admin/membership/reservations/settle", valid | invalid, "admin")[0] == 400
    for _ in range(2):
        status, result, _ = json_request(env, "POST", "/api/admin/membership/reservations/settle", valid, "admin")
        assert status == 200 and result["reservation"]["state"] == "refunded"
    status, result, _ = json_request(env, "POST", "/api/admin/membership/reservations/settle", valid | {"success": True}, "admin")
    assert status == 409 and result["code"] == "settlement_conflict"
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == 10
    assert len([row for row in env.store.list_audit(env.users["admin"]["id"]) if row["action"] == "job_settle"]) == 1


def test_review_checks_execution_state_while_holding_shared_admission_lock(membership_env):
    """A worker's transition before the lock is released must invalidate review."""
    from concurrent.futures import ThreadPoolExecutor
    import threading

    env = membership_env
    activate(env)
    job = reserve_review_job(env)
    entered = threading.Event()

    def review():
        entered.set()
        return json_request(env, "POST", "/api/admin/membership/reservations/settle", {
            "job_id": job["id"], "success": False, "note": "已核对云端真实记录确认未产生结果",
        }, "admin")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with env.panel._admission_lock:
            pending = pool.submit(review)
            assert entered.wait(2)
            job["status"] = "recovering"
        status, result, _ = pending.result(timeout=10)
    assert status == 409 and result["code"] == "job_not_settleable"
    assert env.store.get_reservation(job["id"])["state"] == "running"


@pytest.mark.parametrize("proof,expected", [
    ({"provider_started": 1}, "running"),
    ({"generation_backend": "local", "comfy_prompt_id": "accepted-local-id"}, "running"),
    ({"generation_backend": "local", "prompt_ids": ["accepted-local-id"]}, "running"),
    ({"provider_result_received_at": 1}, "running"),
    ({"provider_failure_confirmed_at": 1}, "refunded"),
    ({"provider_rejection_confirmed_at": 1}, "refunded"),
    ({"cancel_confirmed_at": 1}, "refunded"),
])
def test_quota_settlement_distinguishes_confirmed_outcome_from_uncertainty(membership_env, proof, expected):
    env = membership_env
    activate(env)
    job = reserve_review_job(env, **proof)
    env.gateway.reconcile([job])
    env.gateway.reconcile([job])
    assert env.store.get_reservation(job["id"])["state"] == expected
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == (10 if expected == "refunded" else 9)


@pytest.mark.parametrize("http_status,expected", [(400, "refunded"), (429, "refunded"), (408, "running"), (500, "running"), (503, "running"), (None, "running")])
def test_api_failure_classification_preserves_uncertain_quota(membership_env, tmp_path, monkeypatch, http_status, expected):
    env = membership_env
    activate(env)
    job = reserve_review_job(env, generation_backend="api", prompt="landscape", width=1024, height=1024)
    monkeypatch.setattr(env.panel, "DREAMAPI_KEY", "isolated-fixture-key")
    monkeypatch.setattr(env.panel, "DREAMAPI_CONNECTION_MODE", "direct")

    def rejected_without_network(*args):
        if http_status is None:
            raise TimeoutError("isolated timeout")
        raise env.panel.DreamAPIHTTPError(http_status, "isolated rejection")

    monkeypatch.setattr(env.panel, "_dreamapi_request_json", rejected_without_network)
    with pytest.raises((env.panel.DreamAPIHTTPError, TimeoutError)):
        env.panel.dreamapi_run_image(job, tmp_path)
    env.gateway.settle(job)
    assert env.store.get_reservation(job["id"])["state"] == expected
    assert bool(job.get("provider_rejection_confirmed_at")) is (expected == "refunded")


def test_api_result_download_failure_remains_visible_for_manual_review(membership_env, tmp_path, monkeypatch):
    env = membership_env
    activate(env)
    job = reserve_review_job(env, generation_backend="api", prompt="landscape", width=1024, height=1024)
    monkeypatch.setattr(env.panel, "DREAMAPI_KEY", "isolated-fixture-key")
    monkeypatch.setattr(env.panel, "_dreamapi_request_json", lambda *args: {"data": [{"url": "https://media.example/private.png"}]})
    monkeypatch.setattr(env.panel, "_dreamapi_download_image", lambda *args: (_ for _ in ()).throw(OSError("isolated download failure")))
    with pytest.raises(RuntimeError, match="download failed"):
        env.panel.dreamapi_run_image(job, tmp_path)
    env.gateway.settle(job)
    assert job["provider_result_received_at"]
    assert env.store.get_reservation(job["id"])["state"] == "running"
    status, result, _ = json_request(env, "GET", "/api/admin/membership/reservations", user="admin")
    assert status == 200 and "结果保存未完成" in result["reservations"][0]["reason"]


def test_startup_never_infers_orphan_refund_from_missing_execution_history(membership_env):
    env = membership_env
    activate(env)
    unknown = reserve_review_job(env, provider_started=time.time())
    orphan_id = "f" * 12
    env.store.reserve_job(env.users["alice"]["id"], orphan_id, "video")
    env.gateway.reconcile_startup(env.panel._jobs)
    assert env.store.get_reservation(orphan_id)["state"] == "reserved"
    env.gateway.reconcile_startup(env.panel._jobs)
    assert env.store.get_reservation(orphan_id)["state"] == "reserved"
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == 8
    assert env.store.get_reservation(unknown["id"])["state"] == "running"
    unknown.update(provider_failure_confirmed_at=time.time())
    env.gateway.reconcile_startup(env.panel._jobs)
    assert env.store.get_reservation(unknown["id"])["state"] == "refunded"
    assert env.store.get_reservation(orphan_id)["state"] == "reserved"
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == 9


@pytest.mark.parametrize("source", ["primary", "backup", "missing"])
def test_repeated_ledger_recovery_never_automatically_refunds_missing_tasks(membership_env, source):
    env = membership_env
    panel = env.panel
    activate(env)
    orphan_id = "f" * 12
    env.store.reserve_job(env.users["alice"]["id"], orphan_id, "video")
    job = {"a" * 12: {"id": "a" * 12, "status": "queued", "images": []}}
    if source == "primary":
        panel.JOBS_FILE.write_text(json.dumps(job), encoding="utf-8")
    elif source == "backup":
        panel.JOBS_FILE.write_text("{incomplete-json", encoding="utf-8")
        panel.JOBS_FILE.with_suffix(".json.bak").write_text(json.dumps(job), encoding="utf-8")
    for _ in range(2):
        panel.load_jobs()
        env.gateway.reconcile_startup(panel._jobs)
        assert panel._jobs == (job if source != "missing" else {})
        assert env.store.get_reservation(orphan_id)["state"] == "reserved"
        assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == 9


@pytest.mark.parametrize("age,expected", [(10, 409), (360, 200)])
def test_missing_execution_history_requires_wait_and_explicit_admin_review(membership_env, monkeypatch, age, expected):
    env = membership_env
    activate(env)
    orphan_id = "f" * 12
    monkeypatch.setattr(env.store, "clock", lambda: time.time() - age)
    env.store.reserve_job(env.users["alice"]["id"], orphan_id, "video")
    status, listed, _ = json_request(env, "GET", "/api/admin/membership/reservations", user="admin")
    assert status == 200 and len(listed["reservations"]) == 1
    row = listed["reservations"][0]
    assert row["can_settle"] is (expected == 200) and "账本缺失" in row["reason"]
    status, result, _ = json_request(env, "POST", "/api/admin/membership/reservations/settle", {
        "job_id": orphan_id, "success": False, "note": "已核对云端真实记录确认未产生结果",
    }, "admin")
    assert status == expected
    if expected == 409:
        assert result["code"] == "job_not_settleable"
    assert env.store.get_reservation(orphan_id)["state"] == ("refunded" if expected == 200 else "reserved")
    assert env.store.get_entitlement(env.users["alice"]["id"])["video_available"] == (10 if expected == 200 else 9)
