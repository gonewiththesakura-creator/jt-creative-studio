"""JT account entitlements, activation codes and sessions.

External identities and JT access codes identify accounts; this database is the
single source of truth for JT plans, remaining units and reservations. No entitlement is inferred
from client input or from an identity-provider role. Every value-changing
operation uses an immediate SQLite transaction, including code redemption and
quota reservation. Plain activation codes and session tokens are never stored.
"""

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata
import urllib.parse
import uuid


class MembershipError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _hash(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _login_return_to(value):
    """Only application pages may be a login destination, never arbitrary URLs.

    Validate before URL parsing (which strips some controls), including encoded
    controls from nested query encodings. Keep valid query/fragment bytes intact.
    """
    def unsafe(text):
        return "\\" in text or any(unicodedata.category(ch).startswith("C") for ch in text)

    if (not isinstance(value, str) or not 1 <= len(value) <= 500 or not value.startswith("/") or unsafe(value)
            or re.search(r"%(?![0-9A-Fa-f]{2})", value)):
        raise MembershipError("invalid_return_to", "登录返回地址不正确")
    try:
        parts = urllib.parse.urlsplit(value)
        if parts.scheme or parts.netloc or parts.path not in ("/", "/promptgen", "/realism", "/video"):
            raise ValueError("Unknown application page")
        decoded = value
        # Each changing iteration consumes at least one percent-escape. This
        # catches double/nested encoded TAB/CR/LF/backslashes without truncation.
        for _ in range(len(value)):
            if unsafe(decoded):
                raise ValueError("Control character in return URL")
            after = urllib.parse.unquote(decoded, errors="strict")
            if after == decoded:
                break
            decoded = after
        # HTTP Location is ASCII; preserve already encoded query data and URL
        # delimiters while safely serializing a valid Unicode query/fragment.
        return urllib.parse.quote(value, safe="/?#%&=:+,;@!$'()*-._~")
    except (ValueError, UnicodeError):
        raise MembershipError("invalid_return_to", "登录返回地址不正确") from None


def _text(value, name, maximum=200, required=True):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise MembershipError("invalid_input", f"{name}不正确")
    value = value.strip()
    if required and not value:
        raise MembershipError("invalid_input", f"{name}不能为空")
    return value


def _integer(value, name, minimum=0, maximum=1000000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MembershipError("invalid_input", f"{name}不正确")
    return value


def _public_user(row):
    if row is None:
        return None
    return {**dict(row), "disabled": bool(row["disabled"]), "is_admin": bool(row["is_admin"])}


def _public_plan(row):
    if row is None:
        return None
    return {**dict(row), "features": json.loads(row["features"]),
            "backends": json.loads(row["backends"]), "active": bool(row["active"]),
            "max_video_queued": _integer(row["max_video_queued"], "视频排队数", 1, 100)}


def _plan_snapshot(snapshot):
    """Normalize legacy purchased terms for reading without rewriting them."""
    plan = json.loads(snapshot)
    plan["max_video_queued"] = _integer(plan.get("max_video_queued", 100), "视频排队数", 1, 100)
    return plan


class MembershipStore:
    SCHEMA_VERSION = 2
    FEATURES = frozenset(("image", "video", "upload", "history", "favorites"))
    BACKENDS = frozenset(("cloud", "api", "local"))

    def __init__(self, path, clock=time.time):
        self.path = Path(path).resolve()
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, self.SCHEMA_VERSION):
                raise RuntimeError("Unsupported membership database version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                    username TEXT NOT NULL, email TEXT NOT NULL, owner_key TEXT NOT NULL UNIQUE,
                    disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN(0,1)),
                    is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN(0,1)),
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    UNIQUE(issuer,subject)
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, duration_days INTEGER NOT NULL,
                    image_units INTEGER NOT NULL, video_units INTEGER NOT NULL,
                    max_concurrent INTEGER NOT NULL, features TEXT NOT NULL, backends TEXT NOT NULL,
                    max_video_queued INTEGER NOT NULL DEFAULT 100,
                    active INTEGER NOT NULL CHECK(active IN(0,1)), price_display TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entitlements (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    plan_id TEXT NOT NULL REFERENCES plans(id), plan_snapshot TEXT NOT NULL,
                    starts_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    image_granted INTEGER NOT NULL, video_granted INTEGER NOT NULL,
                    image_available INTEGER NOT NULL CHECK(image_available>=0),
                    video_available INTEGER NOT NULL CHECK(video_available>=0),
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entitlement_user ON entitlements(user_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS activation_codes (
                    id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE,
                    code_hint TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES plans(id),
                    plan_snapshot TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id),
                    created_at INTEGER NOT NULL, note TEXT NOT NULL,
                    redeemed_by TEXT REFERENCES users(id), redeemed_at INTEGER,
                    entitlement_id TEXT REFERENCES entitlements(id), revoked_at INTEGER,
                    CHECK(NOT(redeemed_at IS NOT NULL AND revoked_at IS NOT NULL))
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    csrf TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_user ON auth_sessions(user_id);
                CREATE TABLE IF NOT EXISTS admin_session_verifications (
                    token_hash TEXT PRIMARY KEY REFERENCES auth_sessions(token_hash) ON DELETE CASCADE,
                    verified_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_states (
                    state_hash TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL,
                    return_to TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    entitlement_id TEXT NOT NULL REFERENCES entitlements(id),
                    kind TEXT NOT NULL CHECK(kind IN('image','video')), units INTEGER NOT NULL CHECK(units>0),
                    backend TEXT NOT NULL, state TEXT NOT NULL
                        CHECK(state IN('reserved','running','consumed','refunded')),
                    created_at INTEGER NOT NULL, started_at INTEGER, settled_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS reservation_user ON reservations(user_id,state);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT REFERENCES users(id),
                    action TEXT NOT NULL, target_id TEXT NOT NULL, details TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_buckets (
                    bucket_key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_credentials (
                    id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, code_hint TEXT NOT NULL,
                    plan_id TEXT REFERENCES plans(id), plan_snapshot TEXT,
                    created_by TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL,
                    note TEXT NOT NULL, user_id TEXT REFERENCES users(id), activated_at INTEGER,
                    entitlement_id TEXT REFERENCES entitlements(id), last_used_at INTEGER,
                    login_count INTEGER NOT NULL DEFAULT 0 CHECK(login_count>=0), revoked_at INTEGER,
                    CHECK(user_id IS NOT NULL OR (plan_id IS NOT NULL AND plan_snapshot IS NOT NULL))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS login_credential_active_user ON login_credentials(user_id)
                    WHERE user_id IS NOT NULL AND revoked_at IS NULL;
            """)
            # Additive, backward-compatible migration: keep v2 readable by the
            # previous server for rollback; purchased snapshots stay untouched.
            if "max_video_queued" not in {row["name"] for row in db.execute("PRAGMA table_info(plans)")}:
                db.execute("ALTER TABLE plans ADD COLUMN max_video_queued INTEGER NOT NULL DEFAULT 100")
            db.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
            db.commit()
        self._restrict_files()

    def _now(self):
        value = float(self.clock())
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("Invalid system time")
        return int(value)

    def _restrict_files(self):
        # On Windows the service directory ACL must also restrict its account.
        # chmod is still useful on POSIX deployments, including WAL/SHM files.
        for suffix in ("", "-wal", "-shm"):
            try:
                os.chmod(str(self.path) + suffix, 0o600)
            except OSError:
                pass

    @contextmanager
    def _connection(self, write=False):
        db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA synchronous=FULL")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()
            self._restrict_files()

    def _user(self, db, user_id, enabled=True):
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise MembershipError("unknown_user", "账户不存在", 401)
        if enabled and row["disabled"]:
            raise MembershipError("account_disabled", "账户已停用", 403)
        return row

    def _admin(self, db, actor_id):
        row = self._user(db, actor_id)
        if not row["is_admin"]:
            raise MembershipError("admin_required", "需要管理员权限", 403)
        return row

    def _audit(self, db, actor_id, action, target_id, details=None):
        db.execute("INSERT INTO audit_events(actor_id,action,target_id,details,created_at) VALUES(?,?,?,?,?)",
                   (actor_id, action, target_id, json.dumps(details or {}, ensure_ascii=False), self._now()))

    def upsert_identity(self, issuer, subject, username="", email=""):
        issuer = _text(issuer, "身份来源", 500)
        subject = _text(subject, "身份标识", 300)
        username = _text(username, "用户名", 150, False)
        email = _text(email, "邮箱", 320, False)
        now = self._now()
        with self._connection(True) as db:
            db.execute("""INSERT INTO users(id,issuer,subject,username,email,owner_key,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(issuer,subject)
                          DO UPDATE SET username=excluded.username,email=excluded.email,updated_at=excluded.updated_at""",
                       (uuid.uuid4().hex, issuer, subject, username, email, secrets.token_urlsafe(32), now, now))
            row = db.execute("SELECT * FROM users WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
            return _public_user(row)

    def get_user(self, user_id):
        with self._connection() as db:
            return _public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def get_user_by_identity(self, issuer, subject):
        """Read an exact trusted identity without registering or updating a user."""
        issuer = _text(issuer, "身份来源", 500)
        subject = _text(subject, "身份标识", 300)
        with self._connection() as db:
            return _public_user(db.execute("SELECT * FROM users WHERE issuer=? AND subject=?",
                                           (issuer, subject)).fetchone())

    def get_user_by_owner_key(self, owner_key):
        """Trusted server lookup; owner keys must never be exposed as credentials."""
        if not isinstance(owner_key, str) or not 20 <= len(owner_key) <= 100:
            return None
        with self._connection() as db:
            return _public_user(db.execute("SELECT * FROM users WHERE owner_key=?", (owner_key,)).fetchone())

    def list_users(self, actor_id, limit=100, offset=0):
        limit = _integer(limit, "数量", 1, 100)
        offset = _integer(offset, "偏移", 0, 1000000)
        with self._connection() as db:
            self._admin(db, actor_id)
            return [_public_user(row) for row in db.execute(
                "SELECT * FROM users ORDER BY created_at DESC,id LIMIT ? OFFSET ?", (limit, offset))]

    def bootstrap_admin(self, user_id):
        """Trusted local CLI only; never expose this bootstrap as an HTTP route."""
        with self._connection(True) as db:
            row = self._user(db, user_id)
            if row["is_admin"]:
                return _public_user(row)
            if db.execute("SELECT 1 FROM users WHERE is_admin=1 LIMIT 1").fetchone():
                raise MembershipError("admin_exists", "管理员已经初始化", 409)
            db.execute("UPDATE users SET is_admin=1,updated_at=? WHERE id=?", (self._now(), user_id))
            self._audit(db, user_id, "admin_bootstrap", user_id)
            return _public_user(self._user(db, user_id))

    def set_user_disabled(self, actor_id, user_id, disabled):
        if not isinstance(disabled, bool):
            raise MembershipError("invalid_input", "账户状态不正确")
        with self._connection(True) as db:
            self._admin(db, actor_id)
            row = self._user(db, user_id, False)
            if disabled and row["is_admin"] and not db.execute(
                    "SELECT 1 FROM users WHERE is_admin=1 AND disabled=0 AND id<>?", (user_id,)).fetchone():
                raise MembershipError("last_admin", "不能停用最后一个管理员", 409)
            db.execute("UPDATE users SET disabled=?,updated_at=? WHERE id=?", (int(disabled), self._now(), user_id))
            if disabled:
                db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
                db.execute("UPDATE login_credentials SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                           (self._now(), user_id))
            self._audit(db, actor_id, "user_disable" if disabled else "user_enable", user_id)
            return _public_user(self._user(db, user_id, False))

    def _plan_values(self, values):
        allowed = {"name", "duration_days", "image_units", "video_units", "max_concurrent", "max_video_queued", "features", "backends", "active", "price_display"}
        if not isinstance(values, dict) or set(values) - allowed:
            raise MembershipError("invalid_plan", "套餐字段不正确")
        result = {"name": _text(values.get("name"), "套餐名称", 100),
                  "duration_days": _integer(values.get("duration_days"), "有效天数", 1, 3660),
                  "image_units": _integer(values.get("image_units", 0), "图片额度", 0, 1000000),
                  "video_units": _integer(values.get("video_units", 0), "视频额度", 0, 1000000),
                  "max_concurrent": _integer(values.get("max_concurrent", 1), "并发数", 1, 20),
                  "max_video_queued": _integer(values.get("max_video_queued", 100), "视频排队数", 1, 100),
                  "price_display": _text(values.get("price_display", ""), "价格说明", 100, False)}
        for field, choices, default in (("features", self.FEATURES, ["image", "video", "upload", "history", "favorites"]),
                                        ("backends", self.BACKENDS, ["cloud"])):
            items = values.get(field, default)
            if not isinstance(items, list) or not items or len(items) > len(choices) or any(
                    not isinstance(item, str) or item not in choices for item in items):
                raise MembershipError("invalid_plan", "套餐功能范围不正确")
            result[field] = sorted(set(items))
        result["active"] = values.get("active", True)
        if not isinstance(result["active"], bool):
            raise MembershipError("invalid_plan", "套餐状态不正确")
        return result

    def save_plan(self, actor_id, values, plan_id=None):
        queue_limit_supplied = isinstance(values, dict) and "max_video_queued" in values
        values = self._plan_values(values)
        now = self._now()
        with self._connection(True) as db:
            self._admin(db, actor_id)
            if plan_id is not None:
                existing = db.execute("SELECT max_video_queued FROM plans WHERE id=?", (plan_id,)).fetchone()
                if existing is None:
                    raise MembershipError("plan_not_found", "套餐不存在", 404)
                if not queue_limit_supplied:
                    # Older admin clients must not reset a configured limit.
                    values["max_video_queued"] = existing["max_video_queued"]
            plan_id = plan_id or uuid.uuid4().hex
            db.execute("""INSERT INTO plans(id,name,duration_days,image_units,video_units,max_concurrent,max_video_queued,features,backends,active,price_display,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,duration_days=excluded.duration_days,
                image_units=excluded.image_units,video_units=excluded.video_units,max_concurrent=excluded.max_concurrent,max_video_queued=excluded.max_video_queued,
                features=excluded.features,backends=excluded.backends,active=excluded.active,price_display=excluded.price_display,updated_at=excluded.updated_at""",
                       (plan_id, values["name"], values["duration_days"], values["image_units"], values["video_units"],
                        values["max_concurrent"], values["max_video_queued"], json.dumps(values["features"]), json.dumps(values["backends"]),
                        int(values["active"]), values["price_display"], now, now))
            self._audit(db, actor_id, "plan_save", plan_id, values)
            return _public_plan(db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())

    def list_plans(self, active_only=True):
        with self._connection() as db:
            sql = "SELECT * FROM plans" + (" WHERE active=1" if active_only else "") + " ORDER BY created_at,id"
            return [_public_plan(row) for row in db.execute(sql)]

    def issue_codes(self, actor_id, plan_id, count=1, note=""):
        count = _integer(count, "激活码数量", 1, 100)
        note = _text(note, "备注", 500, False)
        now = self._now()
        with self._connection(True) as db:
            self._admin(db, actor_id)
            plan = _public_plan(db.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone())
            if plan is None:
                raise MembershipError("plan_not_found", "套餐不存在或已停用", 404)
            snapshot = json.dumps(plan, ensure_ascii=False)
            result = []
            for _ in range(count):
                value = secrets.token_hex(16).upper()
                code = "JT-" + "-".join(value[i:i + 8] for i in range(0, 32, 8))
                code_id = uuid.uuid4().hex
                db.execute("""INSERT INTO activation_codes(id,code_hash,code_hint,plan_id,plan_snapshot,created_by,created_at,note)
                              VALUES(?,?,?,?,?,?,?,?)""",
                           (code_id, _hash(code), code[-4:], plan_id, snapshot, actor_id, now, note))
                result.append({"id": code_id, "code": code, "plan_id": plan_id, "created_at": now})
            self._audit(db, actor_id, "codes_issue", plan_id, {"count": count, "note": note})
            return result

    def list_codes(self, actor_id, limit=100, offset=0):
        limit = _integer(limit, "数量", 1, 100)
        offset = _integer(offset, "偏移", 0, 1000000)
        with self._connection() as db:
            self._admin(db, actor_id)
            return [dict(row) for row in db.execute("""SELECT id,code_hint,plan_id,created_by,created_at,note,
                redeemed_by,redeemed_at,entitlement_id,revoked_at FROM activation_codes ORDER BY created_at DESC,id LIMIT ? OFFSET ?""",
                                                   (limit, offset))]

    def revoke_code(self, actor_id, code_id):
        with self._connection(True) as db:
            self._admin(db, actor_id)
            row = db.execute("SELECT * FROM activation_codes WHERE id=?", (code_id,)).fetchone()
            if row is None:
                raise MembershipError("code_not_found", "激活码不存在", 404)
            if row["redeemed_at"] is not None:
                raise MembershipError("code_used", "已兑换的激活码不能作废", 409)
            if row["revoked_at"] is None:
                db.execute("UPDATE activation_codes SET revoked_at=? WHERE id=?", (self._now(), code_id))
                self._audit(db, actor_id, "code_revoke", code_id)
            return {"id": code_id, "revoked": True}

    @staticmethod
    def _normalize_access_code(code):
        if not isinstance(code, str) or len(code) > 256:
            raise MembershipError("invalid_access_code", "登录激活码无效或已停用", 401)
        code = "".join(code.split()).upper()
        if not re.fullmatch(r"JT-A-(?:[0-9A-F]{8}-){5}[0-9A-F]{8}", code):
            raise MembershipError("invalid_access_code", "登录激活码无效或已停用", 401)
        return code

    @staticmethod
    def _public_access_code(row):
        if row is None:
            return None
        fields = ("id", "code_hint", "plan_id", "created_by", "created_at", "note", "user_id",
                  "activated_at", "entitlement_id", "last_used_at", "login_count", "revoked_at")
        result = {key: row[key] for key in fields}
        result["plan_name"] = json.loads(row["plan_snapshot"])["name"] if row["plan_snapshot"] else None
        return result

    def _new_access_code(self, db, actor_id, plan_id, snapshot, note, user_id=None, entitlement_id=None):
        value = secrets.token_hex(24).upper()
        code = "JT-A-" + "-".join(value[i:i + 8] for i in range(0, len(value), 8))
        code_id, now = uuid.uuid4().hex, self._now()
        db.execute("""INSERT INTO login_credentials(id,code_hash,code_hint,plan_id,plan_snapshot,
            created_by,created_at,note,user_id,entitlement_id) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (code_id, _hash(code), code[-4:], plan_id, snapshot, actor_id, now, note, user_id, entitlement_id))
        row = db.execute("SELECT * FROM login_credentials WHERE id=?", (code_id,)).fetchone()
        return self._public_access_code(row) | {"code": code}

    def issue_access_codes(self, actor_id, plan_id, count=1, note=""):
        """Issue unused account credentials; the purchased term starts on first login."""
        actor_id = _text(actor_id, "管理员编号", 128)
        plan_id = _text(plan_id, "套餐编号", 128)
        count = _integer(count, "登录激活码数量", 1, 100)
        note = _text(note, "备注", 500, False)
        with self._connection(True) as db:
            self._admin(db, actor_id)
            plan = _public_plan(db.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone())
            if plan is None:
                raise MembershipError("plan_not_found", "套餐不存在或已停用", 404)
            snapshot = json.dumps(plan, ensure_ascii=False)
            result = [self._new_access_code(db, actor_id, plan_id, snapshot, note) for _ in range(count)]
            self._audit(db, actor_id, "access_codes_issue", plan_id, {"count": count, "note": note})
            return result

    def authenticate_access_code(self, code):
        """Authenticate an account without redeeming or renewing the code again.

        The returned access_credential_id is trusted server context, not public
        user data. Pass it to create_session so a concurrent revocation cannot
        mint a new session after this authentication transaction finishes.
        """
        code = self._normalize_access_code(code)
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM login_credentials WHERE code_hash=?", (_hash(code),)).fetchone()
            if row is None or row["revoked_at"] is not None:
                raise MembershipError("invalid_access_code", "登录激活码无效或已停用", 401)
            now = self._now()
            user_id = row["user_id"]
            if user_id is None:
                user_id = uuid.uuid4().hex
                db.execute("""INSERT INTO users(id,issuer,subject,username,email,owner_key,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (user_id, "urn:jt:access-code", user_id,
                    "用户 " + user_id[:8], "", secrets.token_urlsafe(32), now, now))
                entitlement_id = self._grant_entitlement(db, user_id, row["plan_id"], row["plan_snapshot"], now)
                db.execute("UPDATE login_credentials SET user_id=?,entitlement_id=? WHERE id=?",
                           (user_id, entitlement_id, row["id"]))
                self._audit(db, user_id, "access_code_activate", row["id"],
                            {"plan_id": row["plan_id"], "entitlement_id": entitlement_id})
            user = _public_user(self._user(db, user_id))
            db.execute("""UPDATE login_credentials SET activated_at=COALESCE(activated_at,?),
                last_used_at=?,login_count=login_count+1 WHERE id=?""", (now, now, row["id"]))
            return user | {"access_credential_id": row["id"]}

    def list_access_codes(self, actor_id, limit=100, offset=0):
        limit = _integer(limit, "数量", 1, 100)
        offset = _integer(offset, "偏移", 0, 1000000)
        with self._connection() as db:
            self._admin(db, actor_id)
            return [self._public_access_code(row) for row in db.execute(
                "SELECT * FROM login_credentials ORDER BY created_at DESC,id LIMIT ? OFFSET ?", (limit, offset))]

    def rotate_access_code(self, actor_id, user_id, note=""):
        """Bind a replacement credential to an existing account, preserving its data."""
        actor_id = _text(actor_id, "管理员编号", 128)
        user_id = _text(user_id, "账户编号", 128)
        note = _text(note, "备注", 500, False)
        with self._connection(True) as db:
            self._admin(db, actor_id)
            self._user(db, user_id, False)
            current = self._entitlement(db, user_id)
            db.execute("UPDATE login_credentials SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                       (self._now(), user_id))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            result = self._new_access_code(db, actor_id, current["plan_id"] if current else None,
                current["plan_snapshot"] if current else None, note, user_id, current["id"] if current else None)
            self._audit(db, actor_id, "access_code_rotate", result["id"], {"user_id": user_id, "note": note})
            return result

    def revoke_access_code(self, actor_id, code_id):
        actor_id = _text(actor_id, "管理员编号", 128)
        code_id = _text(code_id, "登录激活码编号", 128)
        with self._connection(True) as db:
            self._admin(db, actor_id)
            row = db.execute("SELECT * FROM login_credentials WHERE id=?", (code_id,)).fetchone()
            if row is None:
                raise MembershipError("code_not_found", "登录激活码不存在", 404)
            if row["revoked_at"] is None:
                db.execute("UPDATE login_credentials SET revoked_at=? WHERE id=?", (self._now(), code_id))
                if row["user_id"] is not None:
                    db.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["user_id"],))
                self._audit(db, actor_id, "access_code_revoke", code_id, {"user_id": row["user_id"]})
            return self._public_access_code(db.execute("SELECT * FROM login_credentials WHERE id=?", (code_id,)).fetchone())

    def _entitlement(self, db, user_id):
        return db.execute("SELECT * FROM entitlements WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (user_id,)).fetchone()

    def _entitlement_view(self, db, user_id):
        row = self._entitlement(db, user_id)
        if row is None:
            return None
        result = dict(row)
        result["plan"] = _plan_snapshot(result.pop("plan_snapshot"))
        user = self._user(db, user_id, False)
        result["active"] = not user["disabled"] and row["expires_at"] > self._now()
        counts = {item["state"]: item["n"] for item in db.execute(
            "SELECT state,COUNT(*) AS n FROM reservations WHERE user_id=? AND state IN('reserved','running') GROUP BY state", (user_id,))}
        result["reserved_jobs"] = counts.get("reserved", 0)
        result["running_jobs"] = counts.get("running", 0)
        result["video_queued_jobs"] = db.execute(
            "SELECT COUNT(*) FROM reservations WHERE user_id=? AND kind='video' AND state='reserved'", (user_id,)).fetchone()[0]
        return result

    def _grant_entitlement(self, db, user_id, plan_id, snapshot, now):
        """Apply frozen purchased terms in the caller's immediate transaction."""
        plan = _plan_snapshot(snapshot)
        current = self._entitlement(db, user_id)
        if current is not None and current["expires_at"] > now:
            if current["plan_id"] != plan_id:
                raise MembershipError("active_plan_conflict", "当前套餐尚未到期，请到期后兑换其他套餐", 409)
            old_plan = _plan_snapshot(current["plan_snapshot"])
            if any(old_plan[key] != plan[key] for key in ("max_concurrent", "max_video_queued", "features", "backends")):
                raise MembershipError("active_plan_conflict", "此激活码的套餐功能已调整，请当前套餐到期后兑换", 409)
            entitlement_id = current["id"]
            if (current["image_granted"] + plan["image_units"] > 100000000 or
                    current["video_granted"] + plan["video_units"] > 100000000 or
                    current["expires_at"] + plan["duration_days"] * 86400 > now + 36600 * 86400):
                raise MembershipError("entitlement_limit", "套餐累计额度或期限超过上限", 409)
            db.execute("""UPDATE entitlements SET expires_at=expires_at+?,image_granted=image_granted+?,video_granted=video_granted+?,
                image_available=image_available+?,video_available=video_available+?,updated_at=? WHERE id=?""",
                       (plan["duration_days"] * 86400, plan["image_units"], plan["video_units"], plan["image_units"], plan["video_units"], now, entitlement_id))
        else:
            entitlement_id = uuid.uuid4().hex
            db.execute("""INSERT INTO entitlements(id,user_id,plan_id,plan_snapshot,starts_at,expires_at,image_granted,video_granted,
                          image_available,video_available,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (entitlement_id, user_id, plan_id, snapshot, now, now + plan["duration_days"] * 86400,
                        plan["image_units"], plan["video_units"], plan["image_units"], plan["video_units"], now, now))
        return entitlement_id

    def redeem(self, user_id, code):
        code = _text(code, "激活码", 80).upper()
        if not re.fullmatch(r"JT-(?:[0-9A-F]{8}-){3}[0-9A-F]{8}", code):
            raise MembershipError("invalid_code", "激活码无效或已使用", 400)
        now = self._now()
        with self._connection(True) as db:
            self._user(db, user_id)
            row = db.execute("SELECT * FROM activation_codes WHERE code_hash=?", (_hash(code),)).fetchone()
            if row is None or row["redeemed_at"] is not None or row["revoked_at"] is not None:
                raise MembershipError("invalid_code", "激活码无效或已使用", 400)
            entitlement_id = self._grant_entitlement(db, user_id, row["plan_id"], row["plan_snapshot"], now)
            db.execute("UPDATE activation_codes SET redeemed_by=?,redeemed_at=?,entitlement_id=? WHERE id=?",
                       (user_id, now, entitlement_id, row["id"]))
            self._audit(db, user_id, "code_redeem", row["id"], {"plan_id": row["plan_id"], "entitlement_id": entitlement_id})
            return self._entitlement_view(db, user_id)

    def get_entitlement(self, user_id):
        with self._connection() as db:
            self._user(db, user_id, False)
            return self._entitlement_view(db, user_id)

    def _access(self, db, user_id, feature, backend=None):
        self._user(db, user_id)
        row = self._entitlement(db, user_id)
        if row is None or row["expires_at"] <= self._now():
            raise MembershipError("plan_required", "套餐未开通或已到期，请兑换激活码", 403)
        plan = _plan_snapshot(row["plan_snapshot"])
        if feature not in plan["features"] or (backend is not None and backend not in plan["backends"]):
            raise MembershipError("feature_forbidden", "当前套餐未开通此功能", 403)
        return row, plan

    def require_access(self, user_id, feature, backend=None):
        with self._connection() as db:
            self._access(db, user_id, feature, backend)
            return self._entitlement_view(db, user_id)

    def can_access(self, user_id, feature, backend=None):
        try:
            self.require_access(user_id, feature, backend)
            return True
        except MembershipError:
            return False

    def reserve_job(self, user_id, job_id, kind, units=1, backend="cloud"):
        job_id = _text(job_id, "任务编号", 128)
        units = _integer(units, "任务额度", 1, 1000000)
        if kind not in ("image", "video") or backend not in self.BACKENDS:
            raise MembershipError("invalid_job", "任务类型不正确")
        with self._connection(True) as db:
            self._user(db, user_id)
            existing = db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in (("user_id", user_id), ("kind", kind), ("units", units), ("backend", backend))):
                    raise MembershipError("reservation_conflict", "任务额度记录冲突", 409)
                return dict(existing)
            row, plan = self._access(db, user_id, kind, backend)
            if kind == "video":
                queued = db.execute("SELECT COUNT(*) FROM reservations WHERE user_id=? AND kind='video' AND state='reserved'",
                                    (user_id,)).fetchone()[0]
                if queued >= plan["max_video_queued"]:
                    raise MembershipError("video_queue_limit", f"当前套餐最多允许 {plan['max_video_queued']} 个视频等待，排队已满，请等待任务开始或取消排队任务后重试", 409)
            column = kind + "_available"
            if row[column] < units:
                raise MembershipError("quota_exhausted", "当前套餐剩余额度不足", 403)
            db.execute(f"UPDATE entitlements SET {column}={column}-?,updated_at=? WHERE id=?", (units, self._now(), row["id"]))
            db.execute("""INSERT INTO reservations(job_id,user_id,entitlement_id,kind,units,backend,state,created_at)
                          VALUES(?,?,?,?,?,?,'reserved',?)""", (job_id, user_id, row["id"], kind, units, backend, self._now()))
            return dict(db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone())

    def start_job(self, job_id):
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise MembershipError("reservation_missing", "任务没有额度记录", 409)
            self._user(db, row["user_id"])
            if row["state"] == "running":
                return dict(row)
            if row["state"] != "reserved":
                raise MembershipError("reservation_settled", "任务额度已结算", 409)
            _, plan = self._access(db, row["user_id"], row["kind"], row["backend"])
            running = db.execute("SELECT COUNT(*) FROM reservations WHERE user_id=? AND state='running'", (row["user_id"],)).fetchone()[0]
            if running >= plan["max_concurrent"]:
                raise MembershipError("concurrency_limit", "当前套餐并发已满，任务继续排队", 409)
            db.execute("UPDATE reservations SET state='running',started_at=? WHERE job_id=?", (self._now(), job_id))
            return dict(db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone())

    def settle_job(self, job_id, success):
        if not isinstance(success, bool):
            raise MembershipError("invalid_input", "结算状态不正确")
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise MembershipError("reservation_missing", "任务没有额度记录", 404)
            if row["state"] in ("consumed", "refunded"):
                return dict(row)
            return self._settle_reservation(db, row, success)

    def _settle_reservation(self, db, row, success):
        """Apply a pending reservation once inside the caller's write transaction."""
        now = self._now()
        if not success:
            column = row["kind"] + "_available"
            db.execute(f"UPDATE entitlements SET {column}={column}+?,updated_at=? WHERE id=?",
                       (row["units"], now, row["entitlement_id"]))
        db.execute("UPDATE reservations SET state=?,settled_at=? WHERE job_id=?",
                   ("consumed" if success else "refunded", now, row["job_id"]))
        return dict(db.execute("SELECT * FROM reservations WHERE job_id=?", (row["job_id"],)).fetchone())

    def admin_settle_job(self, actor_id, job_id, success, note):
        """Record an administrator's verified outcome and its quota effect atomically.

        The caller must hold the execution-ledger lock and verify that this job
        is an unresolved error with no active worker, recovery or queue hold.
        Reservation state alone cannot prove that provider execution has ended.
        """
        actor_id = _text(actor_id, "管理员编号", 128)
        job_id = _text(job_id, "任务编号", 128)
        if not isinstance(success, bool):
            raise MembershipError("invalid_input", "结算状态不正确")
        note = _text(note, "核对说明", 500)
        if len(note) < 10:
            raise MembershipError("invalid_input", "核对说明需要 10 至 500 个字符")
        with self._connection(True) as db:
            self._admin(db, actor_id)
            row = db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise MembershipError("reservation_missing", "任务没有额度记录", 404)
            outcome = "consumed" if success else "refunded"
            if row["state"] in ("consumed", "refunded"):
                if row["state"] != outcome:
                    raise MembershipError("settlement_conflict", "任务已按不同结果结算，不能重复改判", 409)
                return dict(row)
            result = self._settle_reservation(db, row, success)
            self._audit(db, actor_id, "job_settle", job_id, {
                "user_id": row["user_id"], "entitlement_id": row["entitlement_id"],
                "kind": row["kind"], "units": row["units"], "backend": row["backend"],
                "previous_state": row["state"], "state": outcome, "success": success, "note": note,
            })
            return result

    def get_reservation(self, job_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM reservations WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row is not None else None

    def list_unsettled_reservations(self, limit=1000, after_job_id=""):
        """Keyset pagination for trusted startup reconciliation with the job ledger."""
        limit = _integer(limit, "数量", 1, 10000)
        after_job_id = _text(after_job_id, "任务游标", 128, False)
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM reservations WHERE state IN('reserved','running') AND job_id>? ORDER BY job_id LIMIT ?",
                (after_job_id, limit))]

    def create_session(self, user_id, ttl=43200, access_credential_id=None, *, oidc_verified=False):
        ttl = _integer(ttl, "登录期限", 60, 604800)
        token, csrf, now = secrets.token_urlsafe(48), secrets.token_urlsafe(32), self._now()
        with self._connection(True) as db:
            user = _public_user(self._user(db, user_id))
            if access_credential_id is not None:
                access_credential_id = _text(access_credential_id, "登录凭证编号", 128)
                if not db.execute("""SELECT 1 FROM login_credentials
                        WHERE id=? AND user_id=? AND revoked_at IS NULL""", (access_credential_id, user_id)).fetchone():
                    raise MembershipError("invalid_access_code", "登录激活码无效或已停用", 401)
            db.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf,created_at,expires_at) VALUES(?,?,?,?,?)",
                       (_hash(token), user_id, csrf, now, now + ttl))
            # This trusted flag is set only by a verified OIDC callback. A login
            # code grants normal account access, never management assurance.
            if oidc_verified and user["is_admin"] and access_credential_id is None:
                db.execute("INSERT INTO admin_session_verifications(token_hash,verified_at,expires_at) VALUES(?,?,?)",
                           (_hash(token), now, min(now + ttl, now + 900)))
            db.execute("""DELETE FROM auth_sessions WHERE user_id=? AND token_hash NOT IN
                (SELECT token_hash FROM auth_sessions WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10)""", (user_id, user_id))
            self._audit(db, user_id, "session_create", user_id)
        return {"token": token, "csrf": csrf, "expires_at": now + ttl, "user": user}

    def get_session(self, token):
        if not isinstance(token, str) or not 40 <= len(token) <= 150:
            return None
        with self._connection() as db:
            row = db.execute("SELECT * FROM auth_sessions WHERE token_hash=? AND expires_at>?", (_hash(token), self._now())).fetchone()
            if row is None:
                return None
            user = _public_user(self._user(db, row["user_id"], False))
            if user["disabled"]:
                return None
            assurance = db.execute("SELECT expires_at FROM admin_session_verifications WHERE token_hash=? AND expires_at>?",
                                   (_hash(token), self._now())).fetchone()
            return {"csrf": row["csrf"], "created_at": row["created_at"], "expires_at": row["expires_at"], "user": user,
                    "admin_verified_until": assurance["expires_at"] if assurance and user["is_admin"] else 0}

    def verify_csrf(self, token, csrf):
        session = self.get_session(token)
        return bool(session and isinstance(csrf, str) and hmac.compare_digest(session["csrf"], csrf))

    def revoke_session(self, token):
        if not isinstance(token, str) or len(token) > 150:
            return
        with self._connection(True) as db:
            row = db.execute("SELECT user_id FROM auth_sessions WHERE token_hash=?", (_hash(token),)).fetchone()
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_hash(token),))
            if row:
                self._audit(db, row["user_id"], "session_revoke", row["user_id"])

    def create_login_state(self, return_to="/", ttl=300):
        ttl = _integer(ttl, "登录请求期限", 30, 600)
        return_to = _login_return_to(return_to)
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        now = self._now()
        with self._connection(True) as db:
            db.execute("DELETE FROM login_states WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO login_states(state_hash,nonce,verifier,return_to,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                       (_hash(state), nonce, verifier, return_to, now, now + ttl))
        return {"state": state, "nonce": nonce, "verifier": verifier, "return_to": return_to, "expires_at": now + ttl}

    def consume_login_state(self, state):
        if not isinstance(state, str) or not 40 <= len(state) <= 100:
            raise MembershipError("invalid_login_state", "登录请求已过期，请重新登录", 400)
        with self._connection(True) as db:
            row = db.execute("SELECT * FROM login_states WHERE state_hash=?", (_hash(state),)).fetchone()
            if row is None or row["expires_at"] <= self._now():
                raise MembershipError("invalid_login_state", "登录请求已过期，请重新登录", 400)
            db.execute("DELETE FROM login_states WHERE state_hash=?", (_hash(state),))
            result = {key: row[key] for key in ("nonce", "verifier", "return_to", "expires_at")}
            # Also reject unsafe states created before this validation shipped.
            result["return_to"] = _login_return_to(result["return_to"])
            return result

    def take_rate_limit(self, subject, action, limit, window_seconds):
        """Persistent fixed window counter; opaque hashes avoid storing raw IPs."""
        subject = _text(subject, "限流对象", 500)
        action = _text(action, "限流操作", 100)
        limit = _integer(limit, "限流数量", 1, 100000)
        window_seconds = _integer(window_seconds, "限流周期", 1, 86400)
        now = self._now()
        expires_at = (now // window_seconds + 1) * window_seconds
        bucket = _hash(action + "\x00" + subject + "\x00" + str(expires_at))
        with self._connection(True) as db:
            db.execute("DELETE FROM rate_buckets WHERE expires_at<=?", (now,))
            db.execute("INSERT INTO rate_buckets(bucket_key,count,expires_at) VALUES(?,1,?) ON CONFLICT(bucket_key) DO UPDATE SET count=count+1", (bucket, expires_at))
            count = db.execute("SELECT count FROM rate_buckets WHERE bucket_key=?", (bucket,)).fetchone()[0]
            return {"allowed": count <= limit, "remaining": max(0, limit - count), "retry_after": max(1, expires_at - now)}

    def list_audit(self, actor_id, limit=100, offset=0):
        limit = _integer(limit, "数量", 1, 100)
        offset = _integer(offset, "偏移", 0, 1000000)
        with self._connection() as db:
            self._admin(db, actor_id)
            return [{**dict(row), "details": json.loads(row["details"])} for row in db.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))]
