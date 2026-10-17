"""Purchased video waiting limits, with isolated SQLite and offline HTTP."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from membership_http import MembershipGateway
from membership_store import MembershipError, MembershipStore
from test_membership_http import activate as activate_http, json_request, membership_env, panel


@pytest.fixture
def queue_members(tmp_path):
    now = [1800000000]
    store = MembershipStore(tmp_path / "members.sqlite3", clock=lambda: now[0])
    admin = store.upsert_identity("https://identity.example", "owner", "Owner")
    admin = store.bootstrap_admin(admin["id"])
    users = [store.upsert_identity("https://identity.example", name, name) for name in ("alice", "bob")]
    values = {"name": "视频套餐", "duration_days": 30, "image_units": 20, "video_units": 20,
              "max_concurrent": 2, "max_video_queued": 2, "backends": ["cloud", "api", "local"]}
    plan = store.save_plan(admin["id"], values)
    return SimpleNamespace(store=store, now=now, admin=admin, alice=users[0], bob=users[1],
                           values=values, plan=plan)


def activate(env, user=None):
    code = env.store.issue_codes(env.admin["id"], env.plan["id"])[0]["code"]
    return env.store.redeem((user or env.alice)["id"], code)


def test_default_and_legacy_edits_preserve_configured_queue_limit(queue_members):
    env = queue_members
    legacy_values = {key: value for key, value in env.values.items() if key != "max_video_queued"}
    default = env.store.save_plan(env.admin["id"], legacy_values)
    assert default["max_video_queued"] == 100
    saved = env.store.save_plan(env.admin["id"], legacy_values | {"name": "改名"}, env.plan["id"])
    assert saved["max_video_queued"] == 2
    assert next(plan for plan in env.store.list_plans() if plan["id"] == saved["id"])["max_video_queued"] == 2
    changed = env.store.save_plan(env.admin["id"], env.values | {"max_video_queued": 100}, env.plan["id"])
    assert changed["max_video_queued"] == 100


@pytest.mark.parametrize("limit", [0, -1, 101, True, False, 1.5, "2", None, [], {}])
def test_queue_limit_requires_integer_in_range(queue_members, limit):
    env = queue_members
    before = env.store.list_plans()
    with pytest.raises(MembershipError, match="视频排队数") as caught:
        env.store.save_plan(env.admin["id"], env.values | {"max_video_queued": limit}, env.plan["id"])
    assert caught.value.code == "invalid_input"
    assert env.store.list_plans() == before


def test_competing_connections_claim_only_one_final_slot_without_quota_loss(queue_members):
    env = queue_members
    activate(env)
    env.store.reserve_job(env.alice["id"], "already-waiting", "video")
    stores = [MembershipStore(env.store.path, clock=lambda: env.now[0]) for _ in range(8)]
    barrier = threading.Barrier(len(stores))

    def reserve(index):
        barrier.wait(timeout=10)
        try:
            return stores[index].reserve_job(env.alice["id"], f"competing-{index}", "video")
        except MembershipError as error:
            return error.code, error.status

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        results = list(pool.map(reserve, range(len(stores))))
    winners = [row for row in results if isinstance(row, dict)]
    assert len(winners) == 1
    assert results.count(("video_queue_limit", 409)) == 7
    assert env.store.get_entitlement(env.alice["id"])["video_available"] == 18
    assert len(env.store.list_unsettled_reservations()) == 2
    assert env.store.reserve_job(env.alice["id"], winners[0]["job_id"], "video") == winners[0]
    assert env.store.get_entitlement(env.alice["id"])["video_available"] == 18
    with pytest.raises(MembershipError) as caught:
        env.store.reserve_job(env.bob["id"], winners[0]["job_id"], "video")
    assert caught.value.code == "reservation_conflict"


def test_only_waiting_videos_of_same_user_consume_queue_slots(queue_members):
    env = queue_members
    activate(env)
    activate(env, env.bob)
    env.store.reserve_job(env.alice["id"], "running-video", "video")
    env.store.start_job("running-video")
    env.store.reserve_job(env.alice["id"], "waiting-image", "image")
    env.store.reserve_job(env.alice["id"], "running-image", "image")
    env.store.start_job("running-image")
    for name in ("first-waiting-video", "second-waiting-video"):
        env.store.reserve_job(env.alice["id"], name, "video")
    before = env.store.get_entitlement(env.alice["id"])
    assert before["video_queued_jobs"] == 2 and before["reserved_jobs"] == 3 and before["running_jobs"] == 2
    with pytest.raises(MembershipError) as caught:
        env.store.reserve_job(env.alice["id"], "rejected-video", "video")
    assert caught.value.code == "video_queue_limit" and caught.value.status == 409
    assert env.store.get_reservation("rejected-video") is None
    assert env.store.get_entitlement(env.alice["id"]) == before
    assert env.store.reserve_job(env.bob["id"], "other-user-video", "video")["state"] == "reserved"
    assert env.store.get_entitlement(env.bob["id"])["video_queued_jobs"] == 1


@pytest.mark.parametrize("outcome", ["started", "cancelled", "error", "done"])
def test_start_or_settlement_releases_waiting_slot(queue_members, monkeypatch, tmp_path, outcome):
    env = queue_members
    env.store.save_plan(env.admin["id"], env.values | {"max_video_queued": 1}, env.plan["id"])
    activate(env)
    env.store.reserve_job(env.alice["id"], "first", "video")
    if outcome == "started":
        env.store.start_job("first")
    else:
        monkeypatch.setenv("JT_MEMBERSHIP_ENABLED", "0")
        gateway = MembershipGateway(tmp_path, store=env.store)
        gateway.enabled = True
        job = {"id": "first", "membership_reserved": True, "status": outcome}
        gateway.settle(job)
        gateway.settle(job)
    assert env.store.get_entitlement(env.alice["id"])["video_queued_jobs"] == 0
    env.store.reserve_job(env.alice["id"], "replacement", "video")
    current = env.store.get_entitlement(env.alice["id"])
    assert current["video_queued_jobs"] == 1
    assert current["video_available"] == (19 if outcome in ("cancelled", "error") else 18)


def test_unconfirmed_error_keeps_reservation_and_queue_slot(queue_members, monkeypatch, tmp_path):
    env = queue_members
    env.store.save_plan(env.admin["id"], env.values | {"max_video_queued": 1}, env.plan["id"])
    activate(env)
    env.store.reserve_job(env.alice["id"], "uncertain", "video")
    monkeypatch.setenv("JT_MEMBERSHIP_ENABLED", "0")
    gateway = MembershipGateway(tmp_path, store=env.store)
    gateway.enabled = True
    gateway.settle({"id": "uncertain", "membership_reserved": True, "status": "error", "submit_started": True})
    with pytest.raises(MembershipError) as caught:
        env.store.reserve_job(env.alice["id"], "blocked", "video")
    assert caught.value.code == "video_queue_limit"
    assert env.store.get_entitlement(env.alice["id"])["video_available"] == 19


def test_issued_codes_freeze_queue_terms_and_renewal_cannot_change_rights(queue_members):
    env = queue_members
    codes = env.store.issue_codes(env.admin["id"], env.plan["id"], 2)
    access_code = env.store.issue_access_codes(env.admin["id"], env.plan["id"])[0]
    env.store.save_plan(env.admin["id"], env.values | {"max_video_queued": 5}, env.plan["id"])
    first = env.store.redeem(env.alice["id"], codes[0]["code"])
    assert first["plan"]["max_video_queued"] == 2
    access_user = env.store.authenticate_access_code(access_code["code"])
    assert env.store.get_entitlement(access_user["id"])["plan"]["max_video_queued"] == 2
    renewed = env.store.redeem(env.alice["id"], codes[1]["code"])
    assert renewed["id"] == first["id"] and renewed["video_available"] == 40
    new_code = env.store.issue_codes(env.admin["id"], env.plan["id"])[0]
    with pytest.raises(MembershipError) as caught:
        env.store.redeem(env.alice["id"], new_code["code"])
    assert caught.value.code == "active_plan_conflict"
    assert env.store.get_entitlement(env.alice["id"]) == renewed
    assert next(code for code in env.store.list_codes(env.admin["id"]) if code["id"] == new_code["id"])["redeemed_at"] is None
    env.now[0] = renewed["expires_at"]
    assert env.store.redeem(env.alice["id"], new_code["code"])["plan"]["max_video_queued"] == 5


def test_v2_migration_and_legacy_snapshots_preserve_data_and_default_to_100(queue_members):
    env = queue_members
    codes = env.store.issue_codes(env.admin["id"], env.plan["id"], 2)
    access_code = env.store.issue_access_codes(env.admin["id"], env.plan["id"])[0]
    env.store.redeem(env.alice["id"], codes[0]["code"])
    env.store.reserve_job(env.alice["id"], "existing-waiter", "video")
    session = env.store.create_session(env.alice["id"])
    tables = ("users", "entitlements", "activation_codes", "login_credentials", "auth_sessions", "reservations")
    with sqlite3.connect(env.store.path) as db:
        for table in ("entitlements", "activation_codes", "login_credentials"):
            for row_id, snapshot in db.execute(f"SELECT id,plan_snapshot FROM {table}").fetchall():
                legacy_plan = json.loads(snapshot)
                legacy_plan.pop("max_video_queued")
                db.execute(f"UPDATE {table} SET plan_snapshot=? WHERE id=?", (json.dumps(legacy_plan), row_id))
        db.execute("ALTER TABLE plans DROP COLUMN max_video_queued")
        db.execute("PRAGMA user_version=2")
        before = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    upgraded = MembershipStore(env.store.path, clock=lambda: env.now[0])
    with sqlite3.connect(upgraded.path) as db:
        assert {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in tables} == before
        assert db.execute("PRAGMA user_version").fetchone()[0] == MembershipStore.SCHEMA_VERSION
        column = next(row for row in db.execute("PRAGMA table_info(plans)") if row[1] == "max_video_queued")
        assert column[2] == "INTEGER" and column[3] == 1 and column[4] == "100"
    assert upgraded.list_plans()[0]["max_video_queued"] == 100
    assert upgraded.get_session(session["token"])["user"]["id"] == env.alice["id"]
    assert upgraded.get_entitlement(env.alice["id"])["plan"]["max_video_queued"] == 100
    assert upgraded.get_reservation("existing-waiter")["state"] == "reserved"
    # Existing and newly issued default-100 terms can renew legacy snapshots.
    assert upgraded.redeem(env.alice["id"], codes[1]["code"])["plan"]["max_video_queued"] == 100
    new_code = upgraded.issue_codes(env.admin["id"], env.plan["id"])[0]
    assert upgraded.redeem(env.alice["id"], new_code["code"])["plan"]["max_video_queued"] == 100
    upgraded.save_plan(env.admin["id"], env.values | {"max_video_queued": 1}, env.plan["id"])
    access_user = upgraded.authenticate_access_code(access_code["code"])
    assert upgraded.get_entitlement(access_user["id"])["plan"]["max_video_queued"] == 100
    # A new catalog limit must not constrain an existing purchased snapshot.
    upgraded.reserve_job(env.alice["id"], "legacy-second", "video")
    upgraded.reserve_job(env.alice["id"], "legacy-third", "video")
    with sqlite3.connect(upgraded.path) as db:
        for snapshot, in db.execute("SELECT plan_snapshot FROM entitlements"):
            assert "max_video_queued" not in json.loads(snapshot)
    assert MembershipStore(upgraded.path, clock=lambda: env.now[0]).get_entitlement(env.alice["id"])["video_queued_jobs"] == 3


@pytest.mark.parametrize("limit", [None, True, "2", 0, 101])
def test_invalid_purchased_queue_terms_cannot_be_redeemed(queue_members, limit):
    env = queue_members
    code = env.store.issue_codes(env.admin["id"], env.plan["id"])[0]
    with sqlite3.connect(env.store.path) as db:
        snapshot = json.loads(db.execute("SELECT plan_snapshot FROM activation_codes WHERE id=?", (code["id"],)).fetchone()[0])
        snapshot["max_video_queued"] = limit
        db.execute("UPDATE activation_codes SET plan_snapshot=? WHERE id=?", (json.dumps(snapshot), code["id"]))
    with pytest.raises(MembershipError, match="视频排队数"):
        env.store.redeem(env.alice["id"], code["code"])
    assert env.store.get_entitlement(env.alice["id"]) is None
    assert env.store.list_codes(env.admin["id"])[0]["redeemed_at"] is None


def test_http_admin_can_save_list_and_preserve_queue_limit(membership_env):
    env = membership_env
    payload = {"name": "视频排队套餐", "duration_days": 30, "video_units": 10, "max_video_queued": 3}
    status, result, _ = json_request(env, "POST", "/api/admin/membership/plans", payload, "admin")
    assert status == 200 and result["plan"]["max_video_queued"] == 3
    plan_id = result["plan"]["id"]
    legacy_payload = {key: value for key, value in payload.items() if key != "max_video_queued"}
    status, result, _ = json_request(env, "POST", "/api/admin/membership/plans", legacy_payload | {"plan_id": plan_id}, "admin")
    assert status == 200 and result["plan"]["max_video_queued"] == 3
    assert json_request(env, "GET", "/api/admin/membership/plans", user="admin")[1]["plans"][0]["max_video_queued"] == 3
    assert json_request(env, "POST", "/api/admin/membership/plans", payload | {"max_video_queued": "3"}, "admin")[0] == 400
    code = env.store.issue_codes(env.users["admin"]["id"], plan_id)[0]["code"]
    status, result, _ = json_request(env, "POST", "/api/membership/redeem", {"code": code}, "alice")
    assert status == 200 and result["membership"]["plan"]["max_video_queued"] == 3
    assert json_request(env, "GET", "/api/auth/me", user="alice")[1]["membership"]["plan"]["max_video_queued"] == 3


@pytest.mark.parametrize("identity,headers,expected", [
    (None, None, "login_required"), ("alice", None, "admin_required"),
    ("admin", {"X-CSRF-Token": None}, "invalid_csrf"),
    ("admin", {"Origin": "https://other.example"}, "invalid_origin"),
    ("unverified", None, "admin_verification_required"),
])
def test_http_plan_limit_change_requires_verified_admin(membership_env, identity, headers, expected):
    env = membership_env
    if identity == "unverified":
        env.sessions["unverified"] = env.store.create_session(env.users["admin"]["id"])
    status, result, _ = json_request(env, "POST", "/api/admin/membership/plans",
                                   {"name": "unauthorized", "duration_days": 1, "max_video_queued": 1}, identity, headers)
    assert status == (401 if identity is None else 403) and result["code"] == expected
    assert env.store.list_plans() == []


def test_http_queue_rejection_does_not_create_job_or_deduct_and_retry_is_idempotent(membership_env):
    env = membership_env
    activate_http(env, max_video_queued=1)
    payload = {"workflow": "member-video", "prompt": "test", "params": {}, "media": {}, "client_request_id": "first-video"}
    status, first, _ = json_request(env, "POST", "/api/video-generate", payload, "alice")
    assert status == 200, first
    status, retry, _ = json_request(env, "POST", "/api/video-generate", payload, "alice")
    assert status == 200 and retry["job_id"] == first["job_id"]
    status, rejected, _ = json_request(env, "POST", "/api/video-generate", payload | {"client_request_id": "second-video"}, "alice")
    assert status == 409 and rejected["code"] == "video_queue_limit"
    assert len(env.panel._jobs) == 1 and len(env.store.list_unsettled_reservations()) == 1
    membership = json_request(env, "GET", "/api/auth/me", user="alice")[1]["membership"]
    assert membership["video_remaining"] == 9 and membership["video_queued_jobs"] == 1
    assert not env.provider_calls
