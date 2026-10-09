import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from membership_auth import OIDCClient, OIDCError


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def identity_server(signing_key):
    settings = {"requests": [], "claim_changes": {}, "remove_claims": [], "algorithm": "RS256",
                "headers": {"kid": "key-one"}, "token_status": 200, "metadata_changes": {}, "response_changes": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value, status=200):
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            settings["requests"].append(("GET", self.path))
            if self.path == "/.well-known/openid-configuration":
                result = {"issuer": settings["origin"], "authorization_endpoint": settings["origin"] + "/login/oauth/authorize",
                          "token_endpoint": settings["origin"] + "/api/login/oauth/access_token",
                          "jwks_uri": settings["origin"] + "/.well-known/jwks",
                          "response_types_supported": ["code"], "code_challenge_methods_supported": ["S256"],
                          "id_token_signing_alg_values_supported": ["RS256"], **settings["metadata_changes"]}
                self.send_json(result)
            elif self.path == "/.well-known/jwks":
                public_key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
                public_key.update(kid="key-one", use="sig", alg="RS256")
                public_key.update(settings.get("key_changes", {}))
                self.send_json({"keys": [public_key]})
            else:
                self.send_json({"error": "not_found"}, 404)

        def do_POST(self):
            settings["requests"].append(("POST", self.path))
            settings["submitted"] = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode("ascii"))
            if settings.get("redirect"):
                self.send_response(302)
                self.send_header("Location", "https://unexpected.example/token")
                self.end_headers()
                return
            if settings["token_status"] != 200:
                self.send_json({"error": "sensitive-provider-message", "token": "must-not-leak"}, settings["token_status"])
                return
            now = int(time.time())
            claims = {"iss": settings["origin"], "aud": ["jt-client"], "sub": "stable-user-id", "owner": "jt-users",
                      "exp": now + 300, "iat": now - 1, "nonce": settings["nonce"], "preferred_username": "Alice",
                      "email": "alice@example.com", "email_verified": True, "tokenType": "id-token",
                      "isAdmin": True, "sensitiveInternalValue": "must-not-return", **settings["claim_changes"]}
            for field in settings["remove_claims"]:
                claims.pop(field, None)
            algorithm = settings["algorithm"]
            key = signing_key if algorithm == "RS256" else (None if algorithm == "none" else b"other-secret-value-for-hmac-algorithm-testing")
            token = jwt.encode(claims, key, algorithm=algorithm, headers=settings["headers"])
            if settings.get("tamper"):
                parts = token.split(".")
                claims["sub"] = "attacker"
                parts[1] = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
                token = ".".join(parts)
            self.send_json({"id_token": token, "access_token": "test-access-token", **settings["response_changes"]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    settings["origin"] = f"http://127.0.0.1:{server.server_address[1]}"
    settings["nonce"] = secrets.token_urlsafe(32)
    settings["verifier"] = secrets.token_urlsafe(48)
    client = OIDCClient(settings["origin"], settings["origin"], "jt-client", "test-client-secret", "jt-users", allow_insecure_localhost=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield client, settings
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def exchange(client, settings):
    return client.exchange("test-authorization-code", settings["verifier"], settings["nonce"])


def test_authorization_pkce_and_real_http_signed_exchange(identity_server):
    client, settings = identity_server
    state = secrets.token_urlsafe(32)
    url = client.authorization_url(state, settings["nonce"], settings["verifier"])
    query = parse_qs(urlsplit(url).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(settings["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected] and query["code_challenge_method"] == ["S256"]
    assert query["state"] == [state] and query["nonce"] == [settings["nonce"]]
    assert query['prompt'] == ['login']
    assert "test-client-secret" not in url
    claims = exchange(client, settings)
    assert claims["sub"] == "stable-user-id" and claims["owner"] == "jt-users"
    assert "isAdmin" not in claims and "sensitiveInternalValue" not in claims
    submitted = settings["submitted"]
    assert submitted["code_verifier"] == [settings["verifier"]]
    assert submitted["redirect_uri"] == [client.redirect_uri]
    assert submitted["client_secret"] == ["test-client-secret"]
    exchange(client, settings)
    assert settings["requests"].count(("GET", "/.well-known/jwks")) == 1
    assert settings["requests"].count(("GET", "/.well-known/openid-configuration")) == 1


@pytest.mark.parametrize("changes", [
    {"iss": "https://other.example"}, {"aud": "another-app"}, {"aud": ["jt-client", "another-app"]},
    {"exp": 1}, {"iat": 9999999999}, {"iat": "1800000000"}, {"sub": ""}, {"owner": "other-org"},
    {"nonce": "wrong-nonce"}, {"azp": "other-app"}, {"isForbidden": True}, {"isDeleted": True},
    {"tokenType": "access-token"}, {"at_hash": "wrong"}, {"c_hash": "wrong"},
])
def test_claim_mismatches_and_expiry_are_rejected(identity_server, changes):
    client, settings = identity_server
    settings["claim_changes"] = changes
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 400
    assert "must-not" not in str(caught.value)


@pytest.mark.parametrize("field", ["iss", "aud", "exp", "iat", "sub", "owner", "nonce"])
def test_required_claims_cannot_be_omitted(identity_server, field):
    client, settings = identity_server
    settings["remove_claims"] = [field]
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 400


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_unsigned_or_symmetric_algorithms_cannot_authenticate(identity_server, algorithm):
    client, settings = identity_server
    settings["algorithm"] = algorithm
    with pytest.raises(OIDCError):
        exchange(client, settings)
    assert ("GET", "/.well-known/jwks") not in settings["requests"]


def test_invalid_signature_and_remote_key_headers_are_rejected(identity_server):
    client, settings = identity_server
    settings["tamper"] = True
    with pytest.raises(OIDCError):
        exchange(client, settings)
    settings["tamper"] = False
    settings["headers"]["jku"] = "https://attacker.example/keys"
    with pytest.raises(OIDCError):
        exchange(client, settings)


def test_key_algorithm_and_use_cannot_override_allowlist(identity_server):
    client, settings = identity_server
    settings["key_changes"] = {"alg": "HS256"}
    with pytest.raises(OIDCError):
        exchange(client, settings)


@pytest.mark.parametrize("field,value", [
    ("token_endpoint", "https://unexpected.example/token"),
    ("jwks_uri", "file:///etc/passwd"),
    ("authorization_endpoint", "https://unexpected.example/login"),
    ("issuer", "https://other.example"),
    ("code_challenge_methods_supported", ["plain"]),
    ("id_token_signing_alg_values_supported", ["HS256"]),
    ("response_types_supported", None),
])
def test_discovery_cannot_change_trust_origin_or_weaken_flow(identity_server, field, value):
    client, settings = identity_server
    settings["metadata_changes"][field] = value
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 503
    assert settings["requests"] == [("GET", "/.well-known/openid-configuration")]


@pytest.mark.parametrize("status,expected", [(400, 400), (401, 400), (429, 503), (500, 503), (503, 503)])
def test_provider_errors_are_bounded_generic_and_transient_retryable(identity_server, status, expected):
    client, settings = identity_server
    settings["token_status"] = status
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == expected
    assert "must-not-leak" not in str(caught.value) and "sensitive-provider-message" not in str(caught.value)


def test_response_limit_and_redirects_fail_closed(identity_server):
    client, settings = identity_server
    settings["metadata_changes"]["padding"] = "x" * (client.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 503
    settings["metadata_changes"].clear()
    settings["redirect"] = True
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 503
    assert len(settings["requests"]) == 3


def test_transport_failure_is_503_without_exception_secret(identity_server, monkeypatch):
    client, settings = identity_server
    def unavailable(*args, **kwargs):
        raise TimeoutError("provider secret must-not-leak")
    monkeypatch.setattr(client._opener, "open", unavailable)
    with pytest.raises(OIDCError) as caught:
        exchange(client, settings)
    assert caught.value.status == 503 and "must-not-leak" not in str(caught.value)


def test_environment_requires_tls_and_exact_callback(monkeypatch):
    for name, value in {"JT_PUBLIC_ORIGIN": "https://jt.example", "JT_OIDC_ISSUER": "https://identity.example",
                        "JT_OIDC_CLIENT_ID": "jt-client", "JT_OIDC_CLIENT_SECRET": "server-only-secret",
                        "JT_OIDC_ORGANIZATION": "jt-users"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("JT_OIDC_REDIRECT_URI", raising=False)
    monkeypatch.delenv("JT_OIDC_ALLOW_INSECURE_LOCALHOST", raising=False)
    client = OIDCClient.from_env()
    assert client.redirect_uri == "https://jt.example/api/auth/callback"
    monkeypatch.setenv("JT_OIDC_REDIRECT_URI", "https://attacker.example/callback")
    with pytest.raises(OIDCError):
        OIDCClient.from_env()
    monkeypatch.delenv("JT_OIDC_REDIRECT_URI")
    monkeypatch.setenv("JT_OIDC_ISSUER", "http://127.0.0.1:3000")
    with pytest.raises(OIDCError):
        OIDCClient.from_env()
    monkeypatch.setenv("JT_OIDC_ALLOW_INSECURE_LOCALHOST", "1")
    assert OIDCClient.from_env().issuer == "http://127.0.0.1:3000"
    monkeypatch.setenv("JT_OIDC_ISSUER", "http://192.168.1.3:3000")
    with pytest.raises(OIDCError):
        OIDCClient.from_env()


def test_oidc_hash_claims_validate_when_present(identity_server):
    client, settings = identity_server
    settings["claim_changes"] = {field: base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:16]).rstrip(b"=").decode()
                                 for field, value in (("at_hash", "test-access-token"), ("c_hash", "test-authorization-code"))}
    assert exchange(client, settings)["sub"] == "stable-user-id"
