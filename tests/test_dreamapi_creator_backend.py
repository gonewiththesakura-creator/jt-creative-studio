import base64
import io
import json
import time
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

import server


def png_b64(width=64, height=96, color=(31, 79, 127)):
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def test_dreamapi_prompt_compaction_preserves_priority_and_bounds_total_input():
    core = "important-core-style, " + ", ".join(f"style-{i}" for i in range(90))
    content = ", ".join(f"content-{i}" for i in range(160))
    negative = ", ".join(["watermark", "text", "bad hands"] * 30)
    positive, negative_out, compacted = server.compact_dreamapi_prompts(
        core + ", " + content, negative, max_total=1400)
    assert compacted is True
    assert positive.startswith("important-core-style")
    assert "watermark" in negative_out and "bad hands" in negative_out
    assert len(positive) + len(negative_out) <= 1400
    assert positive.count("important-core-style") == 1


def test_short_dreamapi_prompt_is_not_rewritten():
    assert server.compact_dreamapi_prompts("adult portrait", "watermark") == (
        "adult portrait", "watermark", False)


def test_dreamapi_prompt_compaction_keeps_unbroken_long_text_nonempty():
    positive = "复古漫画质感" * 400
    negative = "避免文字水印" * 200
    positive_out, negative_out, compacted = server.compact_dreamapi_prompts(
        positive, negative, max_total=1600)
    assert compacted is True
    assert positive_out
    assert negative_out
    assert positive_out.startswith("复古漫画质感")
    assert negative_out.startswith("避免文字水印")
    assert len(positive_out) + len(negative_out) <= 1600


def test_dreamapi_complete_upstream_input_stays_within_budget():
    text, compacted, positive_chars = server.build_dreamapi_input(
        "连续中文画风描述" * 500,
        "避免文字水印" * 300,
        "768x1024",
        "portrait",
    )
    assert compacted is True
    assert positive_chars > 0
    assert len(text) <= 1600
    assert "Required canvas: exactly 768x1024" in text
    assert "Avoid:" in text


def test_dreamapi_rejects_prompt_that_normalizes_to_no_subject():
    for prompt in (",,\n, ,\n", "，，，、。！？……—"):
        with pytest.raises(ValueError, match="subject"):
            server.build_dreamapi_input(prompt, "watermark", "768x1024", "portrait")


def test_api_failure_sets_terminal_provider_status():
    job={"workflow":"anima02","generation_backend":"api","id":"api-fail","status":"running"}
    original=server.dreamapi_run_image
    try:
        server.dreamapi_run_image=lambda *_: (_ for _ in ()).throw(RuntimeError("upstream failed"))
        server.run_job(job)
    finally:
        server.dreamapi_run_image=original
    assert job["status"]=="error"
    assert job["provider_status"]=="API_ERROR"


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
        self.consumed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self.consumed:
            return b""
        self.consumed = True
        return self.payload


def test_dreamapi_runner_uses_luna_dispatcher_and_saves_exact_png(tmp_path, monkeypatch):
    captured = {}

    def fake_open(request, data, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({
            "id": "resp_test_1",
            "output": [{
                "type": "image_generation_call",
                "result": png_b64(),
                "model": "gpt-image-2.5-flare",
                "quality": "high",
                "size": "64x96",
            }],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob001",
        "prompt": "a careful portrait",
        "negative_prompt": "text, watermark",
        "width": 1024,
        "height": 1024,
        "api_model": "gpt-image-2.5-flare",
        "api_quality": "high",
        "api_fit": "contain",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["url"] == "https://dreamapi.club/responses"
    assert captured["body"]["model"] == "gpt-5.6-luna"
    assert captured["body"]["instructions"] == (
        "You are an image generation dispatcher. Call the provided "
        "image_generation tool exactly once. Do not return or rewrite a prompt. "
        "Return no text."
    )
    assert "tool_choice" not in captured["body"]
    assert captured["body"]["stream"] is False
    assert captured["body"]["tools"] == [{
        "type": "image_generation",
        "action": "generate",
        "model": "gpt-image-2.5-flare",
        "size": "1024x1024",
        "quality": "high",
    }]
    assert "a careful portrait" in captured["body"]["input"]
    assert "text, watermark" in captured["body"]["input"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"

    output = Path(tmp_path) / job["images"][0]["file"]
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)
    assert job["api_response_id"] == "resp_test_1"
    assert job["provider_status"] == "API_DONE"
    assert job["api_dispatch_profile"] == "standard"
    assert job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert job["api_action_mode"] == "generate"
    assert job["images"][0]["url"].startswith("/api/image/dreamjob001/")


def test_dreamapi_image_2_omits_action_for_legacy_bridge_compatibility(tmp_path, monkeypatch):
    captured = {}

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "resp_image_2",
            "output": [{
                "type": "image_generation_call",
                "result": png_b64(),
                "model": "gpt-image-2",
                "quality": "low",
                "size": "1024x1024",
            }],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-image2",
        "prompt": "a careful portrait",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "api_model": "gpt-image-2",
        "api_quality": "low",
        "api_fit": "cover",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["body"]["tools"] == [{
        "type": "image_generation",
        "model": "gpt-image-2",
        "size": "1024x1024",
        "quality": "low",
    }]
    assert captured["body"]["instructions"] == (
        "You are an image generation dispatcher. Call the provided "
        "image_generation tool exactly once. Do not return or rewrite a prompt. "
        "Return no text."
    )


def test_dreamapi_sunburst_uses_its_verified_strict_dispatch_instruction(tmp_path, monkeypatch):
    captured = {}

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "resp_sunburst",
            "output": [{
                "type": "image_generation_call",
                "result": png_b64(),
                "model": "gpt-image-2.5-sunburst",
                "quality": "low",
                "size": "1024x1024",
            }],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-sunburst",
        "prompt": "a careful portrait",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "api_model": "gpt-image-2.5-sunburst",
        "api_quality": "low",
        "api_fit": "cover",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["body"]["instructions"] == (
        "You are an image generation dispatcher. You must call the provided "
        "image_generation tool exactly once. Do not return or rewrite a prompt. "
        "Return no text."
    )
    assert captured["body"]["tools"][0]["model"] == "gpt-image-2.5-sunburst"
    assert captured["body"]["tools"][0]["action"] == "generate"
    assert job["api_dispatch_profile"] == "strict"
    assert job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert job["api_action_mode"] == "generate"


def test_dreamapi_image2_records_omitted_action_contract(tmp_path, monkeypatch):
    captured = {}

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "resp_image2",
            "output": [{
                "type": "image_generation_call",
                "result": png_b64(),
                "model": "gpt-image-2",
                "quality": "low",
                "size": "1024x1024",
            }],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-image2",
        "prompt": "a careful portrait",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "api_model": "gpt-image-2",
        "api_quality": "low",
        "api_fit": "cover",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert "action" not in captured["body"]["tools"][0]
    assert job["api_dispatch_profile"] == "standard"
    assert job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert job["api_action_mode"] == "omitted"


def test_dreamapi_runner_surfaces_bounded_json_error_detail(tmp_path, monkeypatch):
    body = io.BytesIO(json.dumps({"error": {"message": "upstream image worker unavailable"}}).encode())
    error = urllib.error.HTTPError(
        "https://dreamapi.club/responses", 502, "Bad Gateway", {}, body
    )
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    job = {
        "id": "dreamjob-error", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    try:
        server.dreamapi_run_image(job, tmp_path)
    except RuntimeError as caught:
        message = str(caught)
    else:
        raise AssertionError("HTTP 502 must fail")
    assert message == "DreamAPI HTTP 502: upstream image worker unavailable"
    assert "test-key" not in message


@pytest.mark.parametrize("width,height", [(0, 1024), (-1024, -1024), (-768, 1024), (768, 0)])
def test_dreamapi_size_rejects_non_positive_dimensions(width, height):
    with pytest.raises(ValueError, match="positive"):
        server._dreamapi_size(width, height)


def test_dreamapi_http_error_redacts_current_key_and_bearer_tokens(tmp_path, monkeypatch):
    secret = "fixture-secret-never-serialize"
    body = io.BytesIO(json.dumps({
        "error": {"message": f"invalid API key {secret}; Authorization: Bearer other-secret-token-123456"}
    }).encode())
    error = urllib.error.HTTPError("https://dreamapi.club/responses", 401, "Unauthorized", {}, body)
    monkeypatch.setattr(server, "DREAMAPI_KEY", secret, raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: (_ for _ in ()).throw(error))
    job = {
        "id": "dreamjob-redact", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    with pytest.raises(RuntimeError) as caught:
        server.dreamapi_run_image(job, tmp_path)
    message = str(caught.value)
    assert secret not in message
    assert "other-secret-token-123456" not in message
    assert "[REDACTED]" in message


@pytest.mark.parametrize("payload", [None, [], 123, "bad", {"output": "bad"}, {"output": [None]}])
def test_dreamapi_rejects_malformed_response_with_stable_error(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: FakeResponse(payload))
    job = {
        "id": "dreamjob-malformed", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    with pytest.raises(RuntimeError, match="malformed response"):
        server.dreamapi_run_image(job, tmp_path)


def test_dreamapi_rejects_source_image_over_pixel_budget_before_full_decode(tmp_path, monkeypatch):
    encoded = png_b64(width=9000, height=4000)
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: FakeResponse({
        "id": "resp_too_large",
        "output": [{"type": "image_generation_call", "result": encoded}],
    }))
    job = {
        "id": "dreamjob-pixels", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    with pytest.raises(RuntimeError, match="source image dimensions are too large"):
        server.dreamapi_run_image(job, tmp_path)


def test_dreamapi_total_request_and_body_read_share_one_hard_deadline(tmp_path, monkeypatch):
    class SlowResponse:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _size=-1):
            time.sleep(0.5)
            return b""

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "DREAMAPI_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: SlowResponse())
    job = {
        "id": "dreamjob-deadline", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="hard timeout"):
        server.dreamapi_run_image(job, tmp_path)
    assert time.perf_counter() - started < 0.3


def test_dreamapi_http_error_body_read_is_inside_the_same_hard_deadline(tmp_path, monkeypatch):
    class SlowErrorBody:
        def read(self, _size=-1):
            time.sleep(0.5)
            return b""

    error = urllib.error.HTTPError(
        "https://dreamapi.club/responses", 502, "Bad Gateway", {}, SlowErrorBody()
    )
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "DREAMAPI_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: (_ for _ in ()).throw(error))
    job = {
        "id": "dreamjob-error-deadline", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="hard timeout"):
        server.dreamapi_run_image(job, tmp_path)
    assert time.perf_counter() - started < 0.3


@pytest.mark.parametrize("payload", [b"not-json", b"\xff\xfe\xfd"])
def test_dreamapi_success_with_invalid_json_or_utf8_has_stable_error(tmp_path, monkeypatch, payload):
    class RawResponse:
        def __init__(self): self.done = False
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _size=-1):
            if self.done: return b""
            self.done = True
            return payload
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: RawResponse())
    job = {
        "id": "dreamjob-bad-json", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    with pytest.raises(RuntimeError, match="DreamAPI returned malformed response"):
        server.dreamapi_run_image(job, tmp_path)
