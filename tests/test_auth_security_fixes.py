"""Adversarial auth regressions: no external identity/provider calls."""
import sqlite3
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from membership_store import MembershipError, MembershipStore
from test_membership_store import members
from test_membership_http import membership_env, json_request, request
from test_server_review_regressions import panel


@pytest.mark.parametrize("target", [
    "/\t/attacker.invalid", "/\r/attacker.invalid", "/\n/attacker.invalid", "//attacker.invalid",
    "https://attacker.invalid", "/\\attacker.invalid", "/%09/attacker.invalid", "/%2509/attacker.invalid",
    "/video?next=%00", "/video?next=%0d%0aLocation%3Ahttps%3A%2F%2Fevil.example",
    "/video?next=%25250a", "/video?next=%C2%85", "/video?next=%7f", "/video?next=\x1f",
    "/video?next=\x7f", "/video?next=\u200b", "/video?next=%5C", "/video?next=%GG",
    "/video?next=%", "/video?next=%FF", "/../video", "/static/video.html", "/api/auth/logout",
    "/video/../../", "/%76ideo", " /video", "", None, "/video?x=" + "x" * 500,
])
def test_return_url_rejects_browser_normalization_and_encoded_controls(members, target):
    store = members[0]
    with pytest.raises(MembershipError) as caught:
        store.create_login_state(target)
    assert caught.value.code == "invalid_return_to"


@pytest.mark.parametrize("target", ["/", "/video", "/realism", "/promptgen",
    "/video?task=abc&foo=a%20b&redirect=https%3A%2F%2Fexample.test#selected",
    "/?appearance=gold&mix=50%25", "/video?word=%E4%B8%AD%E6%96%87"])
def test_return_url_preserves_valid_page_query_and_fragment(members, target):
    store = members[0]
    state = store.create_login_state(target)
    assert state["return_to"] == target
    assert store.consume_login_state(state["state"])["return_to"] == target


def test_old_pending_unsafe_login_state_is_rejected_on_callback(members):
    store = members[0]
    state = store.create_login_state("/video")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE login_states SET return_to=?", ("/\t/attacker.invalid",))
    with pytest.raises(MembershipError, match="返回地址"):
        store.consume_login_state(state["state"])


def test_admin_assurance_is_session_bound_expires_and_cascades(members):
    store, now, admin, alice, _, _ = members
    legacy = store.create_session(admin["id"])
    verified = store.create_session(admin["id"], oidc_verified=True)
    ordinary = store.create_session(alice["id"], oidc_verified=True)
    assert store.get_session(legacy["token"])["admin_verified_until"] == 0
    assert store.get_session(ordinary["token"])["admin_verified_until"] == 0
    assert store.get_session(verified["token"])["admin_verified_until"] == now[0] + 900
    reopened = MembershipStore(store.path, clock=lambda: now[0])
    assert reopened.get_session(verified["token"])["admin_verified_until"] == now[0] + 900
    now[0] += 900
    assert reopened.get_session(verified["token"])["admin_verified_until"] == 0
    assert reopened.get_session(verified["token"])["user"]["id"] == admin["id"]
    store.revoke_session(verified["token"])
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM admin_session_verifications").fetchone()[0] == 0


def test_additive_assurance_migration_preserves_legacy_sessions_and_entitlements(members):
    store, now, admin, alice, _, plan = members
    store.redeem(alice["id"], store.issue_codes(admin["id"], plan["id"])[0]["code"])
    entitlement = store.get_entitlement(alice["id"])
    session = store.create_session(admin["id"])
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE admin_session_verifications")
    updated = MembershipStore(store.path, clock=lambda: now[0])
    assert updated.get_entitlement(alice["id"]) == entitlement
    assert updated.get_session(session["token"])["admin_verified_until"] == 0
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_admin_code_never_grants_management_even_with_forged_request_claims(membership_env):
    env = membership_env
    env.gateway.login_mode = "access_code"
    code = env.store.rotate_access_code(env.users["admin"]["id"], env.users["admin"]["id"])["code"]
    status, _, headers = json_request(env, "POST", "/api/auth/code-login", {"code": code},
                                     headers={"Origin": env.gateway.origin})
    assert status == 200 and headers["Clear-Site-Data"] == '"cache"'
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    status, me, headers = json_request(env, "GET", "/api/auth/me", headers={"Cookie": cookie})
    assert me["user"]["is_admin"] and me["admin_verification_required"]
    assert me["admin_verification_expires_at"] == 0
    assert headers["Clear-Site-Data"] == '"cache"'
    auth = {"Cookie": cookie, "Origin": env.gateway.origin, "X-CSRF-Token": me["csrf_token"],
            "X-Admin-Verified": "true", "X-OIDC-Verified": "true"}
    for method, path, body in [("GET", "/api/admin/membership/users?oidc_verified=true", None),
                              ("GET", "/api/admin/membership/access-codes", None),
                              ("POST", "/api/admin/membership/plans", {"oidc_verified": True})]:
        status, result, _ = json_request(env, method, path, body, headers=auth)
        assert status == 403 and result["code"] == "admin_verification_required"
    assert json_request(env, "GET", "/api/jobs", headers=auth)[0] == 200
    status, result, headers = json_request(env, "POST", "/api/auth/logout", {}, headers=auth)
    assert status == 200 and result["ok"]
    assert headers["Clear-Site-Data"] == '"cache"'


def test_oidc_callback_grants_fresh_admin_assurance_and_safe_return(membership_env, monkeypatch):
    env = membership_env
    env.gateway.login_mode = "access_code"
    monkeypatch.setattr(env.oidc, "exchange", lambda *args: {"iss": env.oidc.issuer, "sub": "admin", "name": "Admin"})
    target = "/video?task=known&filter=done#selection"
    status, _, headers = json_request(env, "GET", "/api/auth/login?" + urlencode({"return_to": target}))
    assert status == 302
    state = parse_qs(urlsplit(headers["Location"]).query)["state"][0]
    status, _, raw_headers = request(env, "GET", "/api/auth/callback?" + urlencode({
        "state": state, "code": "valid-authorization-code"}),
        headers={"Cookie": headers["Set-Cookie"].split(";", 1)[0]})
    headers = dict(raw_headers)
    assert status == 302 and headers["Location"] == target
    assert headers["Clear-Site-Data"] == '"cache"'
    account = next(value.split(";", 1)[0] for name, value in raw_headers if name == "Set-Cookie" and value.startswith(env.gateway.COOKIE + "="))
    status, me, _ = json_request(env, "GET", "/api/auth/me", headers={"Cookie": account})
    assert me["admin_verification_required"] is False
    assert me["admin_verification_expires_at"] > env.store._now()
    assert json_request(env, "GET", "/api/admin/membership/users", headers={"Cookie": account})[0] == 200
    now = env.store._now()
    env.store.clock = lambda: now + 901
    status, result, _ = json_request(env, "GET", "/api/admin/membership/users", headers={"Cookie": account})
    assert status == 403 and result["code"] == "admin_verification_required"
    assert json_request(env, "GET", "/api/jobs", headers={"Cookie": account})[0] == 200


def test_unsafe_return_to_rejected_before_identity_redirect(membership_env):
    env = membership_env
    for target in ("/\t/attacker.invalid", "/video?next=%2509", "/api/auth/logout"):
        status, result, headers = json_request(env, "GET", "/api/auth/login?" + urlencode({"return_to": target}))
        assert status == 400 and result["code"] == "invalid_return_to"
        assert "Location" not in headers
    assert not env.oidc.authorizations


def test_anonymous_me_also_clears_only_legacy_cache(membership_env):
    status, me, headers = json_request(membership_env, "GET", "/api/auth/me")
    assert status == 200 and not me["authenticated"]
    assert headers["Clear-Site-Data"] == '"cache"'
    assert "no-store" in headers["Cache-Control"]


def test_real_browser_legacy_media_cache_is_cleared_before_account_use(membership_env, monkeypatch):
    from playwright.sync_api import sync_playwright

    env = membership_env
    origin = "http://127.0.0.1:" + str(env.httpd.server_port)
    env.gateway.origin = origin
    env.gateway.COOKIE = "offline_cache_regression_session"
    fid = "f" * 12
    value = b"private-alice-legacy-cache-fixture"
    fixture = env.panel.FAVORITES_DIR / (fid + ".png")
    fixture.write_bytes(value)
    env.panel._favorites[fid] = {"id": fid, "image_path": str(fixture), "favorite_media_type": "image/png",
        "owner_session_hash": env.panel._session_hash(env.users["alice"]["owner_key"])}
    original = env.panel.Handler._write_stream
    original_header = env.panel.Handler.send_header

    def legacy_header(handler, name, value):
        if handler.path == "/api/favorite-image/" + fid and name.lower() == "vary":
            return  # Old release did not partition cached media by Cookie.
        return original_header(handler, name, value)

    def legacy_stream(handler, path, ctype, download_name=None, cache_control=None, allow_range=False):
        # Emulate a cached response served by the old release. New no-store
        # headers alone cannot invalidate a browser's existing fresh cache.
        return original(handler, path, ctype, download_name=download_name,
                        cache_control="private, max-age=86400", allow_range=allow_range)

    monkeypatch.setattr(env.panel.Handler, "_write_stream", legacy_stream)
    monkeypatch.setattr(env.panel.Handler, "send_header", legacy_header)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            def account(name):
                context.clear_cookies()
                context.add_cookies([{"name": env.gateway.COOKIE, "value": env.sessions[name]["token"], "url": origin}])

            def fetch_media():
                return page.evaluate("""async path=>{const r=await fetch(path);return {status:r.status,body:await r.text()}}""",
                                     "/api/favorite-image/" + fid)

            account("alice")
            page.goto(origin + "/api/live")
            page.evaluate("localStorage.setItem('jt-appearance-cache-test','gold')")
            assert fetch_media() == {"status": 200, "body": value.decode()}
            env.store.revoke_session(env.sessions["alice"]["token"])
            account("bob")
            # Confirm this is a real old-cache reproduction before migration.
            assert fetch_media() == {"status": 200, "body": value.decode()}
            me = page.evaluate("async()=>await(await fetch('/api/auth/me',{cache:'no-store'})).json()")
            assert me["user"]["id"] == env.users["bob"]["id"]
            assert fetch_media()["status"] == 404
            assert page.evaluate("localStorage.getItem('jt-appearance-cache-test')") == "gold"
            assert any(item["name"] == env.gateway.COOKIE for item in context.cookies())
        finally:
            context.close()
            browser.close()
