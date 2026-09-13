import importlib.util
import io
import json
from pathlib import Path
import types
import urllib.error

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_payload():
    return {
        "model": "gpt-5.6-sol",
        "input": "A blue sphere on a clean studio background.",
        "stream": False,
        "tools": [{
            "type": "image_generation",
            "action": "generate",
            "model": "gpt-image-2",
            "size": "864x1536",
            "quality": "low",
        }],
    }


def test_watchdog_accepts_only_the_panels_bounded_image_request_contract():
    watchdog = load_module("watchdog_dreamapi_contract", ROOT / "comfy_watchdog.py")
    assert watchdog.validate_dreamapi_payload(valid_payload()) == valid_payload()

    mutations = [
        {**valid_payload(), "model": "other"},
        {**valid_payload(), "stream": True},
        {**valid_payload(), "input": "x" * 2001},
        {**valid_payload(), "unexpected": True},
        {**valid_payload(), "tools": []},
        {**valid_payload(), "tools": [{**valid_payload()["tools"][0], "size": "2048x2048"}]},
        {**valid_payload(), "tools": [{**valid_payload()["tools"][0], "quality": "max"}]},
    ]
    for payload in mutations:
        with pytest.raises(ValueError):
            watchdog.validate_dreamapi_payload(payload)


def test_watchdog_forwards_authorization_only_to_fixed_https_dreamapi(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_forward", ROOT / "comfy_watchdog.py")
    captured = {}

    class Response:
        status = 200
        headers = types.SimpleNamespace(get_content_type=lambda: "application/json")

        def read(self, size):
            if captured.get("read"):
                return b""
            captured["read"] = True
            return b'{"output":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(watchdog, "_dreamapi_urlopen", fake_urlopen)
    status, body, content_type = watchdog.dreamapi_proxy_request(
        valid_payload(), "Bearer local-test-token",
    )
    assert (status, body, content_type) == (200, b'{"output":[]}', "application/json")
    assert captured == {
        "url": "https://dreamapi.club/responses",
        "authorization": "Bearer local-test-token",
        "timeout": 600,
        "payload": valid_payload(),
        "read": True,
    }


def test_watchdog_does_not_follow_redirects_with_the_authorization_header():
    watchdog = load_module("watchdog_dreamapi_redirects", ROOT / "comfy_watchdog.py")
    handler = next(
        item for item in watchdog._dreamapi_opener.handlers
        if isinstance(item, watchdog._NoRedirectHandler)
    )
    assert handler.redirect_request(None, None, 307, "redirect", {}, "https://elsewhere.invalid") is None


def test_server_egress_endpoint_is_optional_and_loopback_only(monkeypatch):
    server = load_module("server_dreamapi_egress", ROOT / "server.py")
    monkeypatch.setattr(server, "DREAMAPI_BASE_URL", "https://dreamapi.club")
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "")
    assert server._dreamapi_request_endpoint() == "https://dreamapi.club/responses"

    monkeypatch.setattr(
        server, "DREAMAPI_EGRESS_URL", "http://127.0.0.1:8198/dreamapi/responses",
    )
    assert server._dreamapi_request_endpoint() == "http://127.0.0.1:8198/dreamapi/responses"

    for unsafe in (
        "https://127.0.0.1:8198/dreamapi/responses",
        "http://8.210.125.65:8198/dreamapi/responses",
        "http://user:pass@127.0.0.1:8198/dreamapi/responses",
        "http://127.0.0.1:8198/dreamapi/responses?next=elsewhere",
    ):
        monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", unsafe)
        with pytest.raises(RuntimeError, match="loopback"):
            server._dreamapi_request_endpoint()
