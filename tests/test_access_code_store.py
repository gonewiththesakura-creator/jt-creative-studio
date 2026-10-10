"""Long-lived account codes preserve identity and grant purchased terms once."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import sqlite3

import pytest

from membership_store import MembershipError, MembershipStore


@pytest.fixture
def accounts(tmp_path):
    now = [1800000000]
    store = MembershipStore(tmp_path / "members.sqlite3", clock=lambda: now[0])
    admin = store.upsert_identity("https://identity.example", "owner", "Owner")
    admin = store.bootstrap_admin(admin["id"])
    existing = store.upsert_identity("https://identity.example", "existing", "Existing member")
    plan = store.save_plan(admin["id"], {
        "name": "月度套餐", "duration_days": 30, "image_units": 12, "video_units": 4,
        "max_concurrent": 2, "backends": ["cloud"],
    })
    return store, now, admin, existing, plan


def issued(accounts, count=1):
    store, _, admin, _, plan = accounts
    return store.issue_access_codes(admin["id"], plan["id"], count)


def open_session(store, user):
    return store.create_session(user["id"], access_credential_id=user["access_credential_id"])


def test_identity_lookup_is_exact_and_never_creates_or_updates_an_account(accounts):
    store, _, admin, existing, _ = accounts
    before = store.list_users(admin["id"])
    assert store.get_user_by_identity(admin["issuer"], admin["subject"]) == admin
    assert store.get_user_by_identity(existing["issuer"], existing["subject"]) == existing
    assert store.get_user_by_identity("https://other.example", admin["subject"]) is None
    assert store.get_user_by_identity(admin["issuer"], "not-registered") is None
    assert store.list_users(admin["id"]) == before
    store.set_user_disabled(admin["id"], existing["id"], True)
    assert store.get_user_by_identity(existing["issuer"], existing["subject"])["disabled"] is True


def test_first_use_freezes_purchased_terms_and_starts_expiry_at_login(accounts):
    store, now, admin, _, plan = accounts
    credential = issued(accounts)[0]
    assert re.fullmatch(r"JT-A-(?:[0-9A-F]{8}-){5}[0-9A-F]{8}", credential["code"])
    assert credential["user_id"] is None and credential["activated_at"] is None
    assert len(store.list_users(admin["id"])) == 2
    updated = {key: plan[key] for key in ("name", "duration_days", "image_units", "video_units", "max_concurrent", "features", "backends", "active", "price_display")}
    store.save_plan(admin["id"], updated | {"duration_days": 1, "image_units": 999, "active": False}, plan["id"])
    now[0] += 45 * 86400
    user = store.authenticate_access_code(credential["code"])
    entitlement = store.get_entitlement(user["id"])
    assert entitlement["starts_at"] == now[0]
    assert entitlement["expires_at"] == now[0] + 30 * 86400
    assert entitlement["image_available"] == 12 and entitlement["video_available"] == 4
    assert user["is_admin"] is False and user["disabled"] is False
    assert store.get_user(user["id"])["owner_key"] == user["owner_key"]
    assert store.get_reservation("unused") is None
    item = store.list_access_codes(admin["id"])[0]
    assert item["user_id"] == user["id"] and item["activated_at"] == now[0]
    assert item["login_count"] == 1 and item["last_used_at"] == now[0]


def test_concurrent_repeated_login_creates_one_account_and_one_entitlement(accounts):
    store, _, admin, _, _ = accounts
    code = issued(accounts)[0]["code"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        users = list(pool.map(lambda _: store.authenticate_access_code(code), range(32)))
    assert len({user["id"] for user in users}) == 1
    assert len({user["owner_key"] for user in users}) == 1
    assert len(store.list_users(admin["id"])) == 3
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM entitlements WHERE user_id=?", (users[0]["id"],)).fetchone()[0] == 1
    assert store.get_entitlement(users[0]["id"])["image_available"] == 12
    assert store.list_access_codes(admin["id"])[0]["login_count"] == 32
    events = store.list_audit(admin["id"])
    assert len([row for row in events if row["action"] == "access_code_activate"]) == 1


def test_two_codes_are_isolated_and_same_code_cross_device_keeps_owner(accounts):
    store, _, _, _, _ = accounts
    first, second = issued(accounts, 2)
    alice = store.authenticate_access_code(first["code"])
    bob = store.authenticate_access_code(second["code"])
    assert alice["id"] != bob["id"] and alice["owner_key"] != bob["owner_key"]
    laptop = open_session(store, alice)
    desktop = open_session(store, store.authenticate_access_code(first["code"]))
    assert laptop["token"] != desktop["token"]
    assert store.get_session(laptop["token"])["user"]["owner_key"] == store.get_session(desktop["token"])["user"]["owner_key"]
    store.reserve_job(alice["id"], "private-history", "video", 2)
    assert store.get_entitlement(alice["id"])["video_available"] == 2
    assert store.get_entitlement(bob["id"])["video_available"] == 4
    with pytest.raises(MembershipError, match="记录冲突"):
        store.reserve_job(bob["id"], "private-history", "video", 2)


def test_normalized_login_accepts_case_and_whitespace_but_renewal_codes_are_distinct(accounts):
    store, _, admin, existing, plan = accounts
    code = issued(accounts)[0]["code"]
    canonical = store.authenticate_access_code(code)
    varied = " \t" + " \n".join(code.lower().split("-"))  # Missing separators is still invalid.
    with pytest.raises(MembershipError):
        store.authenticate_access_code(varied)
    varied = "\t " + code.lower().replace("-", " - \n") + "\u3000"
    assert store.authenticate_access_code(varied)["id"] == canonical["id"]
    renewal = store.issue_codes(admin["id"], plan["id"])[0]["code"]
    with pytest.raises(MembershipError) as caught:
        store.authenticate_access_code(renewal)
    assert caught.value.code == "invalid_access_code"
    with pytest.raises(MembershipError) as caught:
        store.redeem(existing["id"], code)
    assert caught.value.code == "invalid_code"


@pytest.mark.parametrize("code", [None, [], {}, 123, "", "JT-A-", "x" * 257,
    "JT-A-" + "-".join(["F" * 8] * 6), "JT-A-" + "-".join(["Ｇ" * 8] * 6),
    "JT-A-12345678-12345678-12345678-12345678-12345678-1234567\x00"])
def test_invalid_or_unissued_code_cannot_create_an_account(accounts, code):
    store, _, admin, _, _ = accounts
    with pytest.raises(MembershipError) as caught:
        store.authenticate_access_code(code)
    assert caught.value.code == "invalid_access_code" and caught.value.status == 401
    assert len(store.list_users(admin["id"])) == 2


def test_expired_code_can_login_and_renew_original_account_without_reset(accounts):
    store, now, admin, _, plan = accounts
    code = issued(accounts)[0]["code"]
    original = store.authenticate_access_code(code)
    store.reserve_job(original["id"], "old-result", "video")
    store.settle_job("old-result", True)
    before = store.get_entitlement(original["id"])
    now[0] = before["expires_at"] + 86400
    returned = store.authenticate_access_code(code)
    assert returned["id"] == original["id"] and returned["owner_key"] == original["owner_key"]
    assert store.get_session(open_session(store, returned)["token"])
    assert not store.can_access(returned["id"], "video", "cloud")
    assert store.get_entitlement(returned["id"])["video_available"] == 3
    renewal = store.issue_codes(admin["id"], plan["id"])[0]["code"]
    renewed = store.redeem(returned["id"], renewal)
    assert renewed["starts_at"] == now[0] and renewed["video_available"] == 4
    assert store.authenticate_access_code(code)["id"] == original["id"]
    assert store.get_entitlement(original["id"])["id"] == renewed["id"]
    assert store.get_reservation("old-result")["user_id"] == original["id"]


def test_rotation_preserves_owner_and_entitlement_but_invalidates_old_code_and_sessions(accounts):
    store, _, admin, _, _ = accounts
    old = issued(accounts)[0]
    user = store.authenticate_access_code(old["code"])
    sessions = [open_session(store, user) for _ in range(2)]
    store.reserve_job(user["id"], "keep-history", "image", 3)
    before = store.get_entitlement(user["id"])
    replacement = store.rotate_access_code(admin["id"], user["id"], "用户遗失旧码")
    assert replacement["code"] != old["code"] and replacement["user_id"] == user["id"]
    with pytest.raises(MembershipError):
        store.authenticate_access_code(old["code"])
    assert all(store.get_session(session["token"]) is None for session in sessions)
    current = store.authenticate_access_code(replacement["code"])
    assert current["id"] == user["id"] and current["owner_key"] == user["owner_key"]
    assert store.get_entitlement(user["id"]) == before
    assert store.get_reservation("keep-history")["user_id"] == user["id"]
    latest_session = open_session(store, current)
    store.revoke_access_code(admin["id"], old["id"])  # Old-code replay cannot revoke the new session.
    assert store.get_session(latest_session["token"])


@pytest.mark.parametrize("change", ["rotate", "revoke", "disable"])
def test_revocation_between_authentication_and_session_creation_cannot_mint_session(accounts, change):
    store, _, admin, _, _ = accounts
    old = issued(accounts)[0]
    stale = store.authenticate_access_code(old["code"])
    if change == "rotate":
        store.rotate_access_code(admin["id"], stale["id"])
    elif change == "revoke":
        store.revoke_access_code(admin["id"], old["id"])
    else:
        store.set_user_disabled(admin["id"], stale["id"], True)
    with pytest.raises(MembershipError):
        open_session(store, stale)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id=?", (stale["id"],)).fetchone()[0] == 0


def test_disable_and_reenable_never_resurrect_old_credential(accounts):
    store, _, admin, _, _ = accounts
    code = issued(accounts)[0]["code"]
    user = store.authenticate_access_code(code)
    session = open_session(store, user)
    store.set_user_disabled(admin["id"], user["id"], True)
    assert store.get_session(session["token"]) is None
    store.set_user_disabled(admin["id"], user["id"], False)
    with pytest.raises(MembershipError):
        store.authenticate_access_code(code)
    new = store.rotate_access_code(admin["id"], user["id"])
    assert store.authenticate_access_code(new["code"])["owner_key"] == user["owner_key"]


def test_unused_revocation_and_admin_permissions_are_enforced(accounts):
    store, _, admin, existing, plan = accounts
    credential = issued(accounts)[0]
    for action in (lambda: store.issue_access_codes(existing["id"], plan["id"]),
                   lambda: store.list_access_codes(existing["id"]),
                   lambda: store.rotate_access_code(existing["id"], admin["id"]),
                   lambda: store.revoke_access_code(existing["id"], credential["id"])):
        with pytest.raises(MembershipError) as caught:
            action()
        assert caught.value.code == "admin_required"
    first = store.revoke_access_code(admin["id"], credential["id"])
    assert store.revoke_access_code(admin["id"], credential["id"]) == first
    with pytest.raises(MembershipError):
        store.authenticate_access_code(credential["code"])
    assert len(store.list_users(admin["id"])) == 2
    assert len([item for item in store.list_audit(admin["id"]) if item["action"] == "access_code_revoke"]) == 1


def test_existing_owner_and_customer_binding_preserves_roles_without_granting_plan(accounts):
    store, _, admin, existing, _ = accounts
    for user in (admin, existing):
        credential = store.rotate_access_code(admin["id"], user["id"], "迁移原账户")
        authenticated = store.authenticate_access_code(credential["code"])
        assert authenticated["is_admin"] == user["is_admin"]
        assert authenticated["owner_key"] == user["owner_key"] and authenticated["id"] == user["id"]
        assert store.get_entitlement(user["id"]) is None
        assert credential["plan_id"] is None
        assert open_session(store, authenticated)


def test_access_code_secrets_are_not_persisted_or_listed(accounts):
    store, _, admin, _, _ = accounts
    credentials = issued(accounts, 3)
    user = store.authenticate_access_code(credentials[0]["code"])
    credentials.append(store.rotate_access_code(admin["id"], user["id"]))
    with sqlite3.connect(store.path) as db:
        dump = "\n".join(db.iterdump())
        assert all(len(row[0]) == 64 for row in db.execute("SELECT code_hash FROM login_credentials"))
    visible = json.dumps(store.list_access_codes(admin["id"]) + store.list_audit(admin["id"]))
    assert "code_hash" not in visible and "plan_snapshot" not in visible
    assert all(item["code"] not in dump and item["code"] not in visible for item in credentials)
    assert len(store.list_access_codes(admin["id"], limit=2, offset=2)) == 2


def test_first_activation_rolls_back_all_identity_and_quota_changes_if_audit_fails(accounts, monkeypatch):
    store, _, admin, _, _ = accounts
    credential = issued(accounts)[0]
    def audit_failure(*args, **kwargs):
        raise sqlite3.OperationalError("isolated audit write failure")
    with monkeypatch.context() as patch:
        patch.setattr(store, "_audit", audit_failure)
        with pytest.raises(sqlite3.OperationalError):
            store.authenticate_access_code(credential["code"])
    assert len(store.list_users(admin["id"])) == 2
    assert store.list_access_codes(admin["id"])[0]["user_id"] is None
    user = store.authenticate_access_code(credential["code"])
    assert store.get_entitlement(user["id"])["image_available"] == 12


def test_schema_upgrade_preserves_existing_users_sessions_renewals_and_reservations(accounts):
    store, now, admin, existing, plan = accounts
    renewal = store.issue_codes(admin["id"], plan["id"], 2)
    store.redeem(existing["id"], renewal[0]["code"])
    session = store.create_session(existing["id"])
    store.reserve_job(existing["id"], "before-migration", "video")
    snapshot = store.get_entitlement(existing["id"])
    with sqlite3.connect(store.path) as db:
        # Recreate the actual v1 boundary: all existing tables, no credentials.
        db.execute("DROP TABLE login_credentials")
        db.execute("PRAGMA user_version=1")
    upgraded = MembershipStore(store.path, clock=lambda: now[0])
    assert upgraded.get_entitlement(existing["id"]) == snapshot
    assert upgraded.get_session(session["token"])["user"]["owner_key"] == existing["owner_key"]
    assert upgraded.get_reservation("before-migration")["state"] == "reserved"
    assert upgraded.list_access_codes(admin["id"]) == []
    upgraded.redeem(existing["id"], renewal[1]["code"])
    credential = upgraded.rotate_access_code(admin["id"], existing["id"])
    reopened = MembershipStore(store.path, clock=lambda: now[0])
    assert reopened.authenticate_access_code(credential["code"])["id"] == existing["id"]
    assert reopened.get_entitlement(existing["id"])["video_available"] == 7
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
