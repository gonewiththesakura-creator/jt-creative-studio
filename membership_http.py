"""HTTP boundary for account sessions; existing media ownership stays server-side."""
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import os
import re
import time
import urllib.parse

from membership_store import MembershipError, MembershipStore


class MembershipGateway:
    COOKIE = "__Host-jt_account"
    STATE_COOKIE = "__Host-jt_login"
    # Flush private media cached by older releases before changing/using an
    # account. Do not clear storage or cookies: appearance and sessions survive.
    CACHE_BOUNDARY_HEADERS = {"Clear-Site-Data": '"cache"'}

    def __init__(self, data_dir, store=None, oidc=None):
        self.enabled = os.environ.get("JT_MEMBERSHIP_ENABLED", "0") == "1"
        self.store = store
        self.oidc = oidc
        self._settled_jobs = set()
        self.origin = os.environ.get("JT_PUBLIC_ORIGIN", "").rstrip("/")
        self.login_mode = os.environ.get('JT_LOGIN_MODE', 'oidc')
        if self.login_mode not in ('oidc', 'access_code'):
            raise RuntimeError('Unsupported account login mode')
        if self.enabled:
            from membership_auth import OIDCClient
            self.oidc = oidc or OIDCClient.from_env()
            self.origin = self.oidc.public_origin
            self.store = store or MembershipStore(data_dir / "membership.sqlite3")

    @staticmethod
    def cookie(handler, name):
        try:
            jar = http.cookies.SimpleCookie(handler.headers.get("Cookie", ""))
            return jar[name].value if name in jar else ""
        except http.cookies.CookieError:
            return ""

    def session(self, handler):
        if not self.enabled:
            return None
        if not hasattr(handler, "_membership_session"):
            handler._membership_session = self.store.get_session(self.cookie(handler, self.COOKIE))
        return handler._membership_session

    def owner_key(self, handler):
        session = self.session(handler)
        return session["user"]["owner_key"] if session else ""

    @staticmethod
    def public_user(user):
        return {key: user.get(key) for key in ("id", "username", "email", "is_admin", "disabled", "created_at")} | {
            "display_name": user.get("username") or user.get("email") or "JT 用户"}

    def entitlement(self, user_id):
        result = self.store.get_entitlement(user_id)
        if result:
            result = dict(result)
            result["image_remaining"] = result["image_available"]
            result["video_remaining"] = result["video_available"]
        return result

    @staticmethod
    def reply(handler, code, data, headers=None):
        handler._send(code, json.dumps(data, ensure_ascii=False).encode(), headers={
            "Cache-Control": "no-store", **(headers or {})})

    def error(self, handler, error):
        self.reply(handler, error.status, {"error": str(error), "code": error.code})

    def rate(self, subject, action, limit, window=60):
        row = self.store.take_rate_limit(subject, action, limit, window)
        if not row["allowed"]:
            raise MembershipError("rate_limited", "操作过于频繁，请稍后再试", 429)

    @staticmethod
    def peer(handler):
        # Only trust this header from the loopback reverse proxy. Nginx must
        # overwrite it with remote_addr and block direct public backend access.
        peer = handler.client_address[0]
        if ipaddress.ip_address(peer).is_loopback:
            candidate = handler.headers.get("X-Real-IP", "")
            try:
                peer = str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
        return peer

    def guard(self, handler, path, write=False):
        """Return True iff handled/rejected; called before every API handler."""
        if not self.enabled:
            if path == "/api/auth/me" and not write:
                self.reply(handler, 200, {"enabled": False, "authenticated": False})
                return True
            return False
        try:
            # Release management is separately authenticated, loopback-only;
            # the public reverse proxy denies this exact endpoint.
            if path == "/api/admin/release-drain":
                return False
            if path == "/api/live":
                # Preserve the watchdog's service marker and compact JSON.
                return False
            if not path.startswith("/api/"):
                return False
            host = handler.headers.get("Host", "")
            if host.lower() != urllib.parse.urlsplit(self.origin).netloc.lower():
                raise MembershipError("invalid_host", "访问地址不正确", 400)
            if not write and path in ("/api/auth/me", "/api/auth/login", "/api/auth/callback"):
                return self.auth_get(handler, path)
            if path == '/api/auth/code-login':
                if not write or self.login_mode != 'access_code':
                    raise MembershipError('not_found', '接口不存在', 404)
                return self.code_login(handler)
            session = self.session(handler)
            if not session:
                raise MembershipError("login_required", "请先登录工作台", 401)
            user = session["user"]
            self.rate(user["id"], "api_read" if not write else "api_write", 900 if not write else 600)
            if write:
                if handler.headers.get("Origin") != self.origin:
                    raise MembershipError("invalid_origin", "请求来源不正确，请刷新页面", 403)
                csrf = handler.headers.get("X-CSRF-Token", "")
                if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', csrf) or not hmac.compare_digest(session["csrf"], csrf):
                    raise MembershipError("invalid_csrf", "页面已过期，请刷新后重试", 403)
            if path.startswith("/api/upload-direct-"):
                raise MembershipError("unsupported_upload", "请刷新页面后使用账户上传", 410)
            if write and path in ("/api/upload", "/api/upload-start", "/api/upload-chunk", "/api/upload-finish",
                                   "/api/workflow-upload", "/api/realcomic-upload"):
                self.store.require_access(user["id"], "upload", "cloud")
                if path not in ("/api/upload-chunk",):
                    self.rate(user["id"], "upload", 60)
            if write and path.endswith("generate"):
                self.rate(user["id"], "generate", 30)
            if write and path == '/api/favorites':
                self.store.require_access(user['id'], 'favorites')
            if path == "/api/auth/logout" and write:
                self.store.revoke_session(self.cookie(handler, self.COOKIE))
                logout_url = '' if self.login_mode == 'access_code' else self.oidc.issuer + '/api/logout?' + urllib.parse.urlencode({
                    'client_id': self.oidc.client_id, 'post_logout_redirect_uri': self.origin + '/'})
                self.reply(handler, 200, {"ok": True, "logout_url": logout_url}, {
                    **self.CACHE_BOUNDARY_HEADERS, "Set-Cookie": self.cookie_header(self.COOKIE, "", 0)})
                return True
            if path == "/api/membership/redeem" and write:
                self.rate(user["id"], "redeem", 10, 600)
                body = self.body(handler)
                if set(body) != {'code'}:
                    raise MembershipError('invalid_input', '请求字段不正确')
                self.store.redeem(user["id"], body.get("code"))
                self.reply(handler, 200, {"membership": self.entitlement(user["id"])})
                return True
            if path.startswith("/api/admin/membership/"):
                if not user["is_admin"]:
                    raise MembershipError("admin_required", "需要管理员权限", 403)
                if not session.get("admin_verified_until"):
                    raise MembershipError("admin_verification_required", "管理操作需要重新验证管理员身份，请点击管理员验证", 403)
                self.rate(user["id"], "admin", 60)
                return self.admin(handler, path, write, user["id"])
            if path == "/api/health":
                # Provider endpoints, credentials and transport details are not
                # part of a member's health response.
                self.reply(handler, 200, {"ok": True, "authenticated": True})
                return True
            return False
        except MembershipError as error:
            self.error(handler, error)
            return True

    @staticmethod
    def body(handler):
        try:
            body = handler._read_json(32 * 1024)
        except Exception:
            raise MembershipError("invalid_json", "请求数据格式不正确") from None
        if not isinstance(body, dict):
            raise MembershipError("invalid_json", "请求数据格式不正确")
        return body

    @staticmethod
    def cookie_header(name, value, ttl):
        return f"{name}={value}; Path=/; Max-Age={ttl}; Secure; HttpOnly; SameSite=Lax"

    def code_login(self, handler):
        # Anonymous authentication still requires a same-origin JSON request.
        # Never accept the credential in a URL, cookie or form-urlencoded body.
        if (handler.headers.get('Origin') != self.origin
                or handler.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none')):
            raise MembershipError('invalid_origin', '请求来源不正确，请刷新页面', 403)
        self.rate(self.peer(handler), 'code_login', 20, 600)
        if (handler.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json'
                or urllib.parse.urlsplit(handler.path).query):
            raise MembershipError('invalid_input', '请求数据格式不正确')
        body = self.body(handler)
        if set(body) != {'code'}:
            raise MembershipError('invalid_input', '请求字段不正确')
        try:
            user = self.store.authenticate_access_code(body.get('code'))
            session = self.store.create_session(user['id'], access_credential_id=user['access_credential_id'])
        except MembershipError:
            raise MembershipError('invalid_access_code', '激活码无效或已停用，请核对后重试', 401) from None
        # The new token is independent of the reusable login credential.
        self.store.revoke_session(self.cookie(handler, self.COOKIE))
        self.reply(handler, 200, {'ok': True}, {
            **self.CACHE_BOUNDARY_HEADERS, 'Set-Cookie': self.cookie_header(self.COOKIE, session['token'], 43200)})
        return True

    def auth_get(self, handler, path):
        if path == "/api/auth/me":
            session = self.session(handler)
            payload = {"enabled": True, "authenticated": bool(session), "login_url": "/api/auth/login",
                       'login_method': self.login_mode, 'admin_login_available': True}
            if session:
                payload.update(user=self.public_user(session["user"]), csrf_token=session["csrf"],
                               membership=self.entitlement(session["user"]["id"]))
                if session["user"]["is_admin"]:
                    expires = session.get("admin_verified_until", 0)
                    payload.update(admin_verification_required=not bool(expires),
                                   admin_verification_expires_at=expires,
                                   admin_verify_url="/api/auth/login?return_to=%2F")
            self.reply(handler, 200, payload, self.CACHE_BOUNDARY_HEADERS)
            return True
        self.rate(self.peer(handler), "login", 20, 600)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
        if path == "/api/auth/login":
            state = self.store.create_login_state(query.get("return_to", ["/"])[0])
            url = self.oidc.authorization_url(state["state"], state["nonce"], state["verifier"])
            self.reply(handler, 302, {}, {"Location": url, "Set-Cookie": self.cookie_header(self.STATE_COOKIE, state["state"], 300)})
        else:
            state = query.get("state", [""])[0]
            bound = self.cookie(handler, self.STATE_COOKIE)
            if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', state) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', bound) or not hmac.compare_digest(state, bound):
                raise MembershipError("invalid_login_state", "登录校验失败，请重新登录")
            row = self.store.consume_login_state(state)
            claims = self.oidc.exchange(query.get("code", [""])[0], row["verifier"], row["nonce"])
            if self.login_mode == 'access_code':
                existing = self.store.get_user_by_identity(self.oidc.issuer, claims['sub'])
                if not existing or not existing['is_admin'] or existing['disabled']:
                    raise MembershipError('access_code_required', '请回到工作台使用管理员发放的激活码登录', 403)
            user = self.store.upsert_identity(self.oidc.issuer, claims["sub"],
                username=claims.get("name") or claims.get("preferred_username") or "JT 用户", email=claims.get("email") or "")
            if self.login_mode == 'access_code' and not user['is_admin']:
                raise MembershipError('access_code_required', '请回到工作台使用管理员发放的激活码登录', 403)
            # Rotate even if the browser had an earlier session.
            self.store.revoke_session(self.cookie(handler, self.COOKIE))
            session = self.store.create_session(user["id"], oidc_verified=True)
            handler.send_response(302)
            handler.send_header("Content-Length", "0")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Clear-Site-Data", self.CACHE_BOUNDARY_HEADERS["Clear-Site-Data"])
            handler.send_header("Location", row["return_to"])
            handler.send_header("Set-Cookie", self.cookie_header(self.COOKIE, session["token"], 43200))
            handler.send_header("Set-Cookie", self.cookie_header(self.STATE_COOKIE, "", 0))
            handler.end_headers()
        return True

    def admin(self, handler, path, write, actor):
        action = path.removeprefix("/api/admin/membership/")
        body = self.body(handler) if write else {}
        schemas = {
            'plans': {'plan_id', 'name', 'duration_days', 'image_units', 'video_units', 'max_concurrent', 'features', 'backends', 'active', 'price_display'},
            'codes': {'plan_id', 'count', 'note'}, 'codes/revoke': {'code_id'},
            'access-codes': {'plan_id', 'count', 'note'}, 'access-codes/revoke': {'code_id'},
            'users/rotate-code': {'user_id', 'note'},
            'users/disable': {'user_id', 'disabled'},
            'reservations/settle': {'job_id', 'success', 'note'},
        }
        if write and set(body) - schemas.get(action, set()):
            raise MembershipError('invalid_input', '请求字段不正确')
        for key in ('plan_id', 'code_id', 'user_id'):
            if key in body and (not isinstance(body[key], str) or not re.fullmatch(r'[0-9a-f]{32}', body[key])):
                raise MembershipError('invalid_input', '记录编号不正确')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
        try:
            offset = int(query.get("offset", ["0"])[0])
        except ValueError:
            raise MembershipError("invalid_offset", "分页参数不正确") from None
        if action == "plans":
            if write:
                plan_id = body.pop("plan_id", None)
                result = {"plan": self.store.save_plan(actor, body, plan_id)}
            else:
                result = {"plans": self.store.list_plans(False)}
        elif action == "codes":
            result = {"codes": self.store.issue_codes(actor, body.get("plan_id"), body.get("count", 1), body.get("note", ""))
                      if write else self.store.list_codes(actor, offset=offset)}
        elif action == "codes/revoke" and write:
            result = self.store.revoke_code(actor, body.get("code_id"))
        elif action == 'access-codes':
            result = {'codes': self.store.issue_access_codes(actor, body.get('plan_id'), body.get('count', 1), body.get('note', ''))
                      if write else self.store.list_access_codes(actor, offset=offset)}
        elif action == 'access-codes/revoke' and write:
            result = self.store.revoke_access_code(actor, body.get('code_id'))
        elif action == 'users/rotate-code' and write:
            result = {'code': self.store.rotate_access_code(actor, body.get('user_id'), body.get('note', ''))}
        elif action == "users" and not write:
            result = {"users": [self.public_user(u) | {"membership": self.entitlement(u["id"])}
                                 for u in self.store.list_users(actor, offset=offset)]}
        elif action == "users/disable" and write:
            result = {"user": self.public_user(self.store.set_user_disabled(actor, body.get("user_id"), body.get("disabled")))}
        elif action == "audit" and not write:
            result = {"events": self.store.list_audit(actor, offset=offset)}
        elif action == 'reservations' and not write:
            result = self.reservations_callback(actor, None)
        elif action == 'reservations/settle' and write:
            if not isinstance(body.get('job_id'), str) or not re.fullmatch(r'[0-9a-f]{12}', body['job_id']):
                raise MembershipError('invalid_input', '任务编号不正确')
            result = self.reservations_callback(actor, body)
        else:
            raise MembershipError("not_found", "接口不存在", 404)
        self.reply(handler, 200, result)
        return True

    def reserve(self, job, owner_key):
        if not self.enabled:
            return None
        try:
            user = self.store.get_user_by_owner_key(owner_key)
            if not user:
                raise MembershipError("login_required", "请先登录工作台", 401)
            kind = "video" if job.get("style_id") == "video" else "image"
            self.store.reserve_job(user["id"], job["id"], kind, 1 if kind == "video" else max(1, int(job.get("batch") or 1)),
                                   job.get("generation_backend", "cloud"))
            if not job.get("video_queued"):
                try:
                    self.store.start_job(job["id"])
                except MembershipError:
                    self.store.settle_job(job["id"], False)
                    raise
            job["owner_user_id"] = user["id"]
            job["membership_reserved"] = True
            return None
        except MembershipError as error:
            return {"error": str(error), "code": error.code, "status": error.status}

    def settle(self, job):
        if not self.enabled or not job.get("membership_reserved") or job['id'] in self._settled_jobs:
            return
        # Uncertain external submissions keep their reservation. Never invent
        # a failed provider result just to release quota.
        status = job.get("status")
        if status == "done":
            self.store.settle_job(job["id"], True)
            self._settled_jobs.add(job['id'])
        elif status in ("error", "cancelled") and not job.get("queue_hold"):
            confirmed = (job.get("provider_failure_confirmed_at") or job.get("provider_rejection_confirmed_at") or job.get("cancel_confirmed_at")
                         or (not job.get("submit_started") and not job.get("rh_task_id") and not job.get("provider_started")
                             and not job.get('comfy_prompt_id') and not job.get('prompt_ids')))
            if confirmed:
                self.store.settle_job(job["id"], False)
                self._settled_jobs.add(job['id'])

    def reconcile(self, jobs):
        if not self.enabled:
            return
        for job in jobs:
            self.settle(job)

    def reconcile_startup(self, jobs):
        if not self.enabled:
            return
        # Missing JSON jobs are not proof of an unsubmitted reservation: a
        # recovered backup can be older than SQL. Keep those for admin review,
        # including across repeated restarts, rather than inventing a refund.
        self.reconcile(jobs.values())

    def security_headers(self, handler):
        if not self.enabled:
            return
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "same-origin")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        handler.send_header("Strict-Transport-Security", "max-age=31536000")
        handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
