from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from membership_store import MembershipError, MembershipStore


@pytest.fixture
def members(tmp_path):
    now = [1800000000]
    store = MembershipStore(tmp_path / "members.sqlite3", clock=lambda: now[0])
    admin = store.upsert_identity("https://identity.example", "admin", "admin")
    admin = store.bootstrap_admin(admin["id"])
    alice = store.upsert_identity("https://identity.example", "alice", "Alice", "alice@example.com")
    bob = store.upsert_identity("https://identity.example", "bob", "Bob")
    plan = store.save_plan(admin["id"], {
        "name": "创作月卡", "duration_days": 30, "image_units": 12, "video_units": 4,
        "max_concurrent": 2, "price_display": "线下付款后领取激活码",
    })
    return store, now, admin, alice, bob, plan


def activate(store, admin, user, plan):
    code = store.issue_codes(admin["id"], plan["id"])[0]["code"]
    return store.redeem(user["id"], code)


def test_identity_is_stable_but_never_grants_admin_or_reassigns_data(members):
    store, _, admin, alice, bob, _ = members
    again = store.upsert_identity("https://identity.example", "alice", "renamed", "changed@example.com")
    assert again["id"] == alice["id"] and again["owner_key"] == alice["owner_key"]
    assert not again["is_admin"]
    other_issuer = store.upsert_identity("https://other.example", "alice", "admin")
    assert other_issuer["id"] != alice["id"] and other_issuer["owner_key"] != alice["owner_key"]
    assert not other_issuer["is_admin"]
    with pytest.raises(MembershipError, match="管理员已经初始化"):
        store.bootstrap_admin(bob["id"])
    with pytest.raises(MembershipError, match="管理员权限"):
        store.list_users(alice["id"])
    with pytest.raises(MembershipError, match="最后一个管理员"):
        store.set_user_disabled(admin["id"], admin["id"], True)


def test_code_is_one_time_atomic_cross_user_and_secret_not_retained(members):
    store, _, admin, alice, bob, plan = members
    item = store.issue_codes(admin["id"], plan["id"])[0]

    def redeem(index):
        try:
            return store.redeem((alice if index % 2 else bob)["id"], item["code"])
        except MembershipError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(redeem, range(24)))
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert results.count("invalid_code") == 23
    metadata = store.list_codes(admin["id"])[0]
    assert metadata["redeemed_by"] == winners[0]["user_id"]
    assert "code" not in metadata and "code_hash" not in metadata
    with sqlite3.connect(store.path) as db:
        dump = "\n".join(db.iterdump())
    assert item["code"] not in dump
    assert sum(store.get_entitlement(user["id"]) is not None for user in (alice, bob)) == 1


def test_same_plan_renewal_adds_units_and_time_and_issued_terms_are_frozen(members):
    store, now, admin, alice, _, plan = members
    codes = store.issue_codes(admin["id"], plan["id"], 3)
    first = store.redeem(alice["id"], codes[0]["code"])
    store.reserve_job(alice["id"], "existing-image", "image", 4)
    now[0] += 86400
    values = {key: plan[key] for key in ("name", "duration_days", "image_units", "video_units", "max_concurrent", "features", "backends", "active", "price_display")}
    values["image_units"] = 100
    store.save_plan(admin["id"], values, plan["id"])
    renewed = store.redeem(alice["id"], codes[1]["code"])
    assert renewed["id"] == first["id"]
    assert renewed["expires_at"] == first["expires_at"] + 30 * 86400
    assert renewed["image_available"] == 20 and renewed["image_granted"] == 24
    alternate = store.save_plan(admin["id"], {"name": "另一个套餐", "duration_days": 1, "image_units": 1})
    alternate_code = store.issue_codes(admin["id"], alternate["id"])[0]
    with pytest.raises(MembershipError) as caught:
        store.redeem(alice["id"], alternate_code["code"])
    assert caught.value.code == "active_plan_conflict"
    assert next(row for row in store.list_codes(admin["id"]) if row["id"] == alternate_code["id"])["redeemed_at"] is None
    now[0] = renewed["expires_at"]
    replacement = store.redeem(alice["id"], alternate_code["code"])
    assert replacement["id"] != renewed["id"] and replacement["image_available"] == 1
    store.settle_job("existing-image", False)
    assert store.get_entitlement(alice["id"])["image_available"] == 1  # Refund belongs to old period.


def test_revocation_and_admin_authorization(members):
    store, _, admin, alice, _, plan = members
    with pytest.raises(MembershipError):
        store.issue_codes(alice["id"], plan["id"])
    with pytest.raises(MembershipError):
        store.save_plan(alice["id"], {"name": "x", "duration_days": 2})
    item = store.issue_codes(admin["id"], plan["id"])[0]
    store.revoke_code(admin["id"], item["id"])
    assert store.revoke_code(admin["id"], item["id"])["revoked"]
    with pytest.raises(MembershipError, match="无效或已使用"):
        store.redeem(alice["id"], item["code"])
    used = store.issue_codes(admin["id"], plan["id"])[0]
    store.redeem(alice["id"], used["code"])
    with pytest.raises(MembershipError, match="已兑换"):
        store.revoke_code(admin["id"], used["id"])
    assert {row["action"] for row in store.list_audit(admin["id"])} >= {"code_redeem", "code_revoke", "codes_issue", "plan_save", "admin_bootstrap"}


def test_reservation_is_atomic_across_connections_and_idempotent(members):
    store, _, admin, alice, bob, plan = members
    activate(store, admin, alice, plan)
    activate(store, admin, bob, plan)

    def reserve(index):
        try:
            return store.reserve_job(alice["id"], f"video-{index}", "video")
        except MembershipError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(20)))
    reservations = [result for result in results if isinstance(result, dict)]
    assert len(reservations) == 4 and results.count("quota_exhausted") == 16
    assert store.get_entitlement(alice["id"])["video_available"] == 0
    original = reservations[0]
    assert store.reserve_job(alice["id"], original["job_id"], "video") == original
    with pytest.raises(MembershipError) as caught:
        store.reserve_job(bob["id"], original["job_id"], "video")
    assert caught.value.code == "reservation_conflict"
    assert store.get_entitlement(bob["id"])["video_available"] == 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.settle_job(original["job_id"], False), range(16)))
    assert store.get_entitlement(alice["id"])["video_available"] == 1
    assert store.settle_job(original["job_id"], True)["state"] == "refunded"
    assert store.get_entitlement(alice["id"])["video_available"] == 1


def test_running_limit_is_independent_from_queue_and_settlement_is_final(members):
    store, _, admin, alice, _, plan = members
    activate(store, admin, alice, plan)
    for n in range(4):
        store.reserve_job(alice["id"], f"job-{n}", "video")
    assert store.get_entitlement(alice["id"])["reserved_jobs"] == 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        def start(n):
            try:
                return store.start_job(f"job-{n}")
            except MembershipError as exc:
                return exc.code
        results = list(pool.map(start, range(4)))
    assert results.count("concurrency_limit") == 2
    running = next(result for result in results if isinstance(result, dict))
    store.settle_job(running["job_id"], True)
    store.settle_job(running["job_id"], False)
    assert store.get_entitlement(alice["id"])["video_available"] == 0
    assert store.get_entitlement(alice["id"])["running_jobs"] == 1
    with pytest.raises(MembershipError, match="已结算"):
        store.start_job(running["job_id"])


def test_expiry_features_and_disabled_accounts_are_enforced(members):
    store, now, admin, alice, _, plan = members
    assert not store.can_access(alice["id"], "video", "cloud")
    entitlement = activate(store, admin, alice, plan)
    assert store.can_access(alice["id"], "video", "cloud")
    assert not store.can_access(alice["id"], "video", "local")
    with pytest.raises(MembershipError):
        store.reserve_job(alice["id"], "local", "image", backend="local")
    session = store.create_session(alice["id"])
    store.reserve_job(alice["id"], "pending", "video")
    store.set_user_disabled(admin["id"], alice["id"], True)
    assert store.get_session(session["token"]) is None
    assert not store.get_entitlement(alice["id"])["active"]
    with pytest.raises(MembershipError, match="已停用"):
        store.start_job("pending")
    store.settle_job("pending", False)  # Disabled users still receive settlement/refund.
    store.set_user_disabled(admin["id"], alice["id"], False)
    assert store.get_session(session["token"]) is None
    now[0] = entitlement["expires_at"]
    with pytest.raises(MembershipError) as caught:
        store.reserve_job(alice["id"], "expired", "video")
    assert caught.value.code == "plan_required"


def test_sessions_and_login_state_are_unpredictable_one_use_and_expiring(members):
    store, now, admin, alice, _, _ = members
    session = store.create_session(alice["id"], ttl=60)
    assert store.get_session(session["token"])["user"]["id"] == alice["id"]
    assert store.verify_csrf(session["token"], session["csrf"])
    assert not store.verify_csrf(session["token"], "wrong")
    assert store.get_session("bad") is None
    state = store.create_login_state("/video")
    with sqlite3.connect(store.path) as db:
        dump = "\n".join(db.iterdump())
    assert session["token"] not in dump and state["state"] not in dump
    assert session["token"] not in json.dumps(store.list_audit(admin["id"]))
    assert store.consume_login_state(state["state"])["verifier"] == state["verifier"]
    with pytest.raises(MembershipError):
        store.consume_login_state(state["state"])
    for invalid in ("https://evil.example", "//evil.example", "/\\evil.example", "/\r\nLocation:evil"):
        with pytest.raises(MembershipError):
            store.create_login_state(invalid)
    expiring = store.create_login_state(ttl=30)
    now[0] += 60
    assert store.get_session(session["token"]) is None
    with pytest.raises(MembershipError):
        store.consume_login_state(expiring["state"])
    new = store.create_session(alice["id"])
    store.revoke_session(new["token"])
    assert store.get_session(new["token"]) is None


@pytest.mark.parametrize("invalid", [
    {"duration_days": 0}, {"duration_days": True}, {"image_units": -1},
    {"max_concurrent": 21}, {"image_units": 1.5}, {"backends": ["admin"]},
    {"features": ["override"]}, {"active": "true"}, {"is_admin": True},
])
def test_plan_rejects_unbounded_or_unknown_privileges(members, invalid):
    store, _, admin, _, _, _ = members
    with pytest.raises(MembershipError):
        store.save_plan(admin["id"], {"name": "bad", "duration_days": 30, **invalid})


def test_rate_limit_and_sessions_survive_store_reopen(members):
    store, now, _, alice, _, _ = members
    session = store.create_session(alice["id"])
    assert store.take_rate_limit("ip", "redeem", 2, 60)["allowed"]
    reopened = MembershipStore(store.path, clock=lambda: now[0])
    assert reopened.get_session(session["token"])["user"]["owner_key"] == alice["owner_key"]
    assert reopened.take_rate_limit("ip", "redeem", 2, 60)["allowed"]
    blocked = store.take_rate_limit("ip", "redeem", 2, 60)
    assert not blocked["allowed"] and blocked["retry_after"] > 0
    now[0] += 60
    assert reopened.take_rate_limit("ip", "redeem", 2, 60)["allowed"]


def test_server_ownership_lookup_and_unsettled_keyset_pagination(members):
    store, _, admin, alice, _, plan = members
    assert store.get_user_by_owner_key(alice["owner_key"])["id"] == alice["id"]
    assert store.get_user_by_owner_key("not-an-owner") is None
    activate(store, admin, alice, plan)
    for name in ("job-a", "job-b", "job-c"):
        store.reserve_job(alice["id"], name, "video")
    store.start_job("job-b")
    store.settle_job("job-c", True)
    assert [row["job_id"] for row in store.list_unsettled_reservations(limit=1)] == ["job-a"]
    assert [row["job_id"] for row in store.list_unsettled_reservations(after_job_id="job-a")] == ["job-b"]


@pytest.mark.parametrize("success,expected", [(True, "consumed"), (False, "refunded")])
def test_admin_settlement_is_final_audited_and_idempotent(members, success, expected):
    store, _, admin, alice, _, plan = members
    activate(store, admin, alice, plan)
    store.reserve_job(alice["id"], "verified-job", "image", 3)
    store.start_job("verified-job")
    note = "  已核对云端真实任务状态及计费结果  "
    first = store.admin_settle_job(admin["id"], "verified-job", success, note)
    assert first["state"] == expected
    assert store.admin_settle_job(admin["id"], "verified-job", success, note) == first
    with pytest.raises(MembershipError) as caught:
        store.admin_settle_job(admin["id"], "verified-job", not success, note)
    assert caught.value.code == "settlement_conflict" and caught.value.status == 409
    entitlement = store.get_entitlement(alice["id"])
    assert entitlement["image_available"] == (9 if success else 12)
    assert entitlement["running_jobs"] == 0
    audits = [row for row in store.list_audit(admin["id"]) if row["action"] == "job_settle"]
    assert len(audits) == 1
    audit = audits[0]
    assert audit["actor_id"] == admin["id"] and audit["target_id"] == "verified-job"
    assert audit["details"] == {
        "user_id": alice["id"], "entitlement_id": first["entitlement_id"],
        "kind": "image", "units": 3, "backend": "cloud", "previous_state": "running",
        "state": expected, "success": success, "note": note.strip(),
    }


def test_admin_settlement_rejects_non_admin_without_quota_or_audit_changes(members):
    store, _, admin, alice, bob, plan = members
    activate(store, admin, alice, plan)
    original = store.reserve_job(alice["id"], "private-job", "video")
    for user in (alice, bob):
        with pytest.raises(MembershipError) as caught:
            store.admin_settle_job(user["id"], "private-job", False, "已核对确认任务失败且未计费")
        assert caught.value.code == "admin_required" and caught.value.status == 403
    assert store.get_reservation("private-job") == original
    assert store.get_entitlement(alice["id"])["video_available"] == 3
    assert not any(row["action"] == "job_settle" for row in store.list_audit(admin["id"]))
    with pytest.raises(MembershipError) as caught:
        store.admin_settle_job(admin["id"], "missing-job", False, "已核对确认任务失败且未计费")
    assert caught.value.code == "reservation_missing" and caught.value.status == 404


@pytest.mark.parametrize("success,note", [
    (0, "已核对确认任务失败且未计费"), (1, "已核对确认任务失败且未计费"),
    ("false", "已核对确认任务失败且未计费"), (None, "已核对确认任务失败且未计费"),
    (False, "九个字以下"), (False, " " * 10), (False, "x" * 501),
    (False, ["说明不是字符串"]), (False, "已核对确认\x00任务失败且未计费"),
])
def test_admin_settlement_requires_strict_outcome_and_explanation(members, success, note):
    store, _, admin, alice, _, plan = members
    activate(store, admin, alice, plan)
    original = store.reserve_job(alice["id"], "validation-job", "video")
    with pytest.raises(MembershipError) as caught:
        store.admin_settle_job(admin["id"], "validation-job", success, note)
    assert caught.value.code == "invalid_input"
    assert store.get_reservation("validation-job") == original
    assert store.get_entitlement(alice["id"])["video_available"] == 3


def test_concurrent_admin_settlement_refunds_and_audits_exactly_once(members):
    store, _, admin, alice, _, plan = members
    activate(store, admin, alice, plan)
    store.reserve_job(alice["id"], "concurrent-review", "video", 2)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: store.admin_settle_job(
            admin["id"], "concurrent-review", False, "已核对云端真实记录确认未产生结果"), range(24)))
    assert all(result == results[0] for result in results)
    assert results[0]["state"] == "refunded"
    assert store.get_entitlement(alice["id"])["video_available"] == 4
    assert len([row for row in store.list_audit(admin["id"]) if row["action"] == "job_settle"]) == 1


def test_admin_settlement_rolls_back_refund_when_audit_cannot_be_written(members, monkeypatch):
    store, _, admin, alice, _, plan = members
    activate(store, admin, alice, plan)
    original = store.reserve_job(alice["id"], "audit-failure", "image", 2)

    def failed_audit(*args, **kwargs):
        raise sqlite3.OperationalError("audit write failed")

    monkeypatch.setattr(store, "_audit", failed_audit)
    with pytest.raises(sqlite3.OperationalError):
        store.admin_settle_job(admin["id"], "audit-failure", False, "已核对云端真实记录确认未产生结果")
    assert store.get_reservation("audit-failure") == original
    assert store.get_entitlement(alice["id"])["image_available"] == 10
