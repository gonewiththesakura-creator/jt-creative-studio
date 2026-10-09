"""Casdoor authorization-code + S256 PKCE client with strict ID-token checks.

Only administrator-configured HTTPS origins are contacted. Discovery cannot
redirect token exchange or key retrieval to another origin. JWT cryptographic
verification is delegated to the pinned PyJWT/cryptography dependencies.

Configuration uses an ordinary, non-shared Casdoor application, RS256 signing,
and JWT-Standard (or another JWT format retaining owner and nonce claims).
The server must bind OAuth state to the initiating browser and consume it once.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

import jwt

from membership_store import MembershipError


class OIDCError(MembershipError):
    pass


def _unavailable(code="identity_unavailable"):
    return OIDCError(code, "登录服务暂时不可用，请稍后重试", 503)


def _invalid(code="invalid_identity"):
    return OIDCError(code, "登录验证未通过，请重新登录", 400)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _base64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _bounded_string(value, maximum, minimum=1):
    return isinstance(value, str) and minimum <= len(value) <= maximum and not any(ord(ch) < 32 for ch in value)


class OIDCClient:
    MAX_RESPONSE_BYTES = 256 * 1024
    MAX_ID_TOKEN_BYTES = 64 * 1024
    NETWORK_TIMEOUT = 6
    READ_DEADLINE = 12
    METADATA_TTL = 3600
    JWKS_TTL = 300
    ALGORITHMS = ("RS256",)

    def __init__(self, public_origin, issuer, client_id, client_secret, organization,
                 redirect_uri=None, *, allow_insecure_localhost=False):
        self.allow_insecure_localhost = bool(allow_insecure_localhost)
        self.public_origin = self._origin(public_origin)
        self.issuer = self._origin(issuer)
        if not _bounded_string(client_id, 300) or not _bounded_string(client_secret, 4096):
            raise _unavailable("identity_not_configured")
        if not _bounded_string(organization, 100):
            raise _unavailable("identity_not_configured")
        self.client_id = client_id
        self._client_secret = client_secret
        self.organization = organization
        self.redirect_uri = redirect_uri or self.public_origin + "/api/auth/callback"
        if self.redirect_uri != self.public_origin + "/api/auth/callback":
            raise _unavailable("identity_not_configured")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        self._lock = threading.RLock()
        self._metadata_cache = None
        self._metadata_at = 0.0
        self._jwks_cache = None
        self._jwks_at = 0.0

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("JT_PUBLIC_ORIGIN", ""),
            os.environ.get("JT_OIDC_ISSUER", ""),
            os.environ.get("JT_OIDC_CLIENT_ID", ""),
            os.environ.get("JT_OIDC_CLIENT_SECRET", ""),
            os.environ.get("JT_OIDC_ORGANIZATION", ""),
            os.environ.get("JT_OIDC_REDIRECT_URI") or None,
            allow_insecure_localhost=os.environ.get("JT_OIDC_ALLOW_INSECURE_LOCALHOST") == "1",
        )

    def _url(self, value):
        if not _bounded_string(value, 2048) or "\\" in value or any(ch.isspace() for ch in value):
            raise _unavailable("identity_invalid_endpoint")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise _unavailable("identity_invalid_endpoint") from None
        local_http = (self.allow_insecure_localhost and parsed.scheme == "http"
                      and parsed.hostname in ("localhost", "127.0.0.1", "::1"))
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.query or (parsed.scheme != "https" and not local_http)
                or (port is not None and not 1 <= port <= 65535)):
            raise _unavailable("identity_invalid_endpoint")
        return parsed

    def _origin(self, value):
        parsed = self._url(value)
        if parsed.path not in ("", "/"):
            raise _unavailable("identity_invalid_endpoint")
        return value.rstrip("/")

    def _endpoint(self, value):
        parsed = self._url(value)
        expected = urlsplit(self.issuer)
        if (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)) != (
                expected.scheme, expected.hostname, expected.port or (443 if expected.scheme == "https" else 80)):
            raise _unavailable("identity_invalid_endpoint")
        return value

    def _json_request(self, url, data=None):
        self._endpoint(url)
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "JT-Identity/1.0"}
        payload = None
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            payload = urlencode(data).encode("ascii")
        request = Request(url, data=payload, headers=headers, method="POST" if payload is not None else "GET")
        deadline = time.monotonic() + self.READ_DEADLINE
        try:
            with self._opener.open(request, timeout=self.NETWORK_TIMEOUT) as response:
                if response.status != 200 or response.geturl() != url:
                    raise _unavailable()
                encoding = response.headers.get("Content-Encoding", "identity").lower()
                if encoding not in ("", "identity"):
                    raise _unavailable()
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdecimal() or int(length) > self.MAX_RESPONSE_BYTES):
                    raise _unavailable()
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise _unavailable()
                    chunk = response.read1(min(8192, self.MAX_RESPONSE_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.MAX_RESPONSE_BYTES:
                        raise _unavailable()
                result = json.loads(b"".join(chunks).decode("utf-8"))
                if not isinstance(result, dict):
                    raise _unavailable()
                return result
        except HTTPError as exc:
            # Do not include provider responses, authorization codes or tokens in errors.
            status = exc.code
            exc.close()
            if data is not None and status in (400, 401, 403):
                raise _invalid("invalid_authorization_code") from None
            raise _unavailable() from None
        except (URLError, TimeoutError, socket.timeout, OSError, UnicodeError, ValueError) as exc:
            if isinstance(exc, OIDCError):
                raise
            raise _unavailable() from None

    def _metadata(self):
        with self._lock:
            if self._metadata_cache is not None and time.monotonic() - self._metadata_at < self.METADATA_TTL:
                return self._metadata_cache
            metadata = self._json_request(self.issuer + "/.well-known/openid-configuration")
            if metadata.get("issuer") != self.issuer:
                raise _unavailable("identity_invalid_discovery")
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                self._endpoint(metadata.get(field))
            for field, required in (("response_types_supported", "code"),
                                    ("id_token_signing_alg_values_supported", "RS256"),
                                    ("code_challenge_methods_supported", "S256")):
                if not isinstance(metadata.get(field), list) or required not in metadata[field]:
                    raise _unavailable("identity_unsupported_configuration")
            self._metadata_cache, self._metadata_at = metadata, time.monotonic()
            return metadata

    def authorization_url(self, state, nonce, verifier):
        if (not _bounded_string(state, 200, 32) or not _bounded_string(nonce, 200, 32)
                or not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)):
            raise _invalid("invalid_login_state")
        metadata = self._metadata()
        query = urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": "openid profile email",
            "prompt": "login",
            "state": state, "nonce": nonce,
            "code_challenge": _base64url(hashlib.sha256(verifier.encode("ascii")).digest()),
            "code_challenge_method": "S256",
        })
        return metadata["authorization_endpoint"] + "?" + query

    def _signing_key(self, kid):
        with self._lock:
            now = time.monotonic()
            # A new kid refreshes a warm cache at most once per 30 seconds.
            cached_keys = (self._jwks_cache or {}).get("keys", [])
            found = any(isinstance(key, dict) and key.get("kid") == kid for key in cached_keys)
            if (self._jwks_cache is None or now - self._jwks_at >= self.JWKS_TTL
                    or (not found and now - self._jwks_at >= 30)):
                keys = self._json_request(self._metadata()["jwks_uri"])
                if not isinstance(keys.get("keys"), list) or not 1 <= len(keys["keys"]) <= 100:
                    raise _unavailable("identity_invalid_keys")
                self._jwks_cache, self._jwks_at = keys, time.monotonic()
                cached_keys = keys["keys"]
            matches = [key for key in cached_keys if isinstance(key, dict) and key.get("kid") == kid]
            if len(matches) != 1:
                raise _invalid()
            key = matches[0]
            if (key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256"
                    or key.get("use", "sig") != "sig"
                    or ("key_ops" in key and key["key_ops"] != ["verify"])):
                raise _invalid()
            try:
                parsed = jwt.PyJWK.from_dict(key, algorithm="RS256")
                if parsed.key.key_size < 2048:
                    raise _invalid()
                return parsed
            except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
                raise _invalid() from None

    def exchange(self, code, verifier, nonce):
        if (not _bounded_string(code, 4096) or not _bounded_string(nonce, 200, 32)
                or not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)):
            raise _invalid("invalid_authorization_code")
        metadata = self._metadata()
        response = self._json_request(metadata["token_endpoint"], {
            "grant_type": "authorization_code", "client_id": self.client_id,
            "client_secret": self._client_secret, "code": code,
            "redirect_uri": self.redirect_uri, "code_verifier": verifier,
        })
        if response.get("error"):
            if response.get("error") in ("temporarily_unavailable", "server_error"):
                raise _unavailable()
            raise _invalid("invalid_authorization_code")
        token = response.get("id_token")
        if not _bounded_string(token, self.MAX_ID_TOKEN_BYTES):
            raise _invalid()
        try:
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or not _bounded_string(header.get("kid"), 200)
                    or any(field in header for field in ("jku", "jwk", "x5u", "crit"))):
                raise _invalid()
            key = self._signing_key(header["kid"])
            claims = jwt.decode(token, key, algorithms=list(self.ALGORITHMS),
                                issuer=self.issuer, audience=self.client_id, leeway=0,
                                options={"require": ["iss", "aud", "exp", "iat", "sub", "nonce", "owner"],
                                         "verify_signature": True, "verify_exp": True, "verify_iat": True,
                                         "verify_nbf": True, "verify_iss": True, "verify_aud": True})
            if (claims.get("iss") != self.issuer or claims.get("aud") not in (self.client_id, [self.client_id])
                    or not _bounded_string(claims.get("sub"), 300)
                    or not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce)
                    or claims.get("owner") != self.organization
                    or claims.get("azp", self.client_id) != self.client_id
                    or claims.get("tokenType", "id-token") != "id-token"):
                raise _invalid()
            for field in ("exp", "iat"):
                if isinstance(claims[field], bool) or not isinstance(claims[field], int):
                    raise _invalid()
            if claims["iat"] >= claims["exp"]:
                raise _invalid()
            if any(claims.get(field, False) is not False for field in ("isForbidden", "isDeleted")):
                raise _invalid("account_disabled")
            for field, value in (("at_hash", response.get("access_token")), ("c_hash", code)):
                if field in claims:
                    if not _bounded_string(value, self.MAX_ID_TOKEN_BYTES):
                        raise _invalid()
                    expected = _base64url(hashlib.sha256(value.encode("utf-8")).digest()[:16])
                    if not isinstance(claims[field], str) or not hmac.compare_digest(claims[field], expected):
                        raise _invalid()
            # Never return token payload secrets, provider roles or tokens to the HTTP layer.
            keep = ("iss", "sub", "aud", "exp", "iat", "nonce", "owner", "preferred_username", "name", "displayName", "email", "email_verified")
            return {field: claims[field] for field in keep if field in claims}
        except OIDCError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, UnicodeError):
            raise _invalid() from None
