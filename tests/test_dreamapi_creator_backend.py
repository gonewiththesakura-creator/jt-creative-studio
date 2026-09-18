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


def test_dreamapi_input_separates_supported_canvas_from_final_tall_crop():
    text, compacted, _ = server.build_dreamapi_input(
        "adult portrait", "watermark", "1024x1536", "portrait",
        final_size="864x1536",
    )
    assert compacted is False
    assert "Required canvas: exactly 1024x1536" in text
    assert "centered final crop to 864x1536" in text


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


def test_api_5xx_public_error_is_actionable_without_leaking_upstream_detail():
    public = server.public_job_error({
        "id": "api-fail", "generation_backend": "api",
        "error": "DreamAPI HTTP 502: private upstream detail",
    })
    assert "上游暂时失败（HTTP 502）" in public
    assert "可手动重新生成" in public
    assert "private upstream detail" not in public


@pytest.mark.parametrize('detail, expected', [
    ('DreamAPI HTTP 400: Your request was rejected by the safety system. safety_violations=[sexual].', '色情或性内容'),
    ('DreamAPI HTTP 400: content_policy_violation', '内容安全审核'),
    ('DreamAPI HTTP 403: Image generation is not enabled for this group', '分组未开启生图权限'),
    ('DreamAPI HTTP 401: invalid key', '密钥无效或已失效'),
    ('DreamAPI HTTP 403: forbidden', '没有权限'),
    ('DreamAPI HTTP 429: insufficient_quota', '额度不足'),
    ('DreamAPI HTTP 429: rate limit exceeded', '请求过于频繁'),
    ('DreamAPI HTTP 404: model not found', '模型或接口不存在'),
    ('DreamAPI HTTP 400: invalid size', '参数未被接口接受'),
    ('DreamAPI HTTP 502: DreamAPI workstation egress failed', '转发服务连接失败'),
    ('DreamAPI HTTP 429: DreamAPI prior request outcome is still uncertain', '上一次请求的结果尚未确认'),
    ('DreamAPI hard timeout after 600s', '等待超时'),
    ('<urlopen error [WinError 10061] connection refused>', '连接失败'),
    ('DreamAPI returned no completed image', '没有返回可用图片'),
    ('DreamAPI returned malformed response', '返回的数据格式异常'),
    ('DreamAPI returned invalid image data', '返回的图片数据无法读取'),
    ('DreamAPI image data is too large', '图片超过处理上限'),
    ('unknown internal failure', '暂时无法识别具体原因'),
])
def test_api_public_errors_explain_known_causes_without_echoing_secrets(detail, expected):
    message = server.public_job_error({'id':'3feb9a6f8901','generation_backend':'api',
                                      'error':detail+' secret=sk-private-secret request-id=private-id'})
    assert expected in message
    assert '3feb9a6f8901' in message
    assert 'sk-private-secret' not in message and 'private-id' not in message


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


def test_dreamapi_runner_uses_native_images_api_and_saves_exact_png(tmp_path, monkeypatch):
    captured = {}
    encoded = png_b64(width=1024, height=1024)

    def fake_open(request, data, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({
            "id": "img_test_1",
            "created": 123,
            "data": [{"b64_json": encoded}],
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

    assert captured["url"] == "https://dreamapi.club/v1/images/generations"
    assert captured["body"] == {
        "model": "gpt-image-2.5-flare",
        "prompt": captured["body"]["prompt"],
        "size": "1024x1024",
        "quality": "high",
        "n": 1,
        "output_format": "png",
    }
    assert "a careful portrait" in captured["body"]["prompt"]
    assert "text, watermark" in captured["body"]["prompt"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"

    output = Path(tmp_path) / job["images"][0]["file"]
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)
    assert output.read_bytes() == base64.b64decode(encoded)
    assert job["api_response_id"] == "img_test_1"
    assert job["provider_status"] == "API_DONE"
    assert job["api_transport"] == "images"
    assert job["api_geometry_normalized"] is False
    assert job["dreamapi_contract_sha256"] == server.DREAMAPI_CONTRACT_SHA256
    assert job["images"][0]["url"].startswith("/api/image/dreamjob001/")


@pytest.mark.parametrize("ratio,provider_size", [
    ("1:1", "1024x1024"),
    ("2:3", "1024x1536"),
    ("3:2", "1536x1024"),
    ("9:16", "864x1536"),
    ("16:9", "1536x864"),
])
def test_dreamapi_ratio_maps_to_supported_provider_canvas(ratio, provider_size):
    width, height = server.DREAMAPI_RATIO_SIZES[ratio]
    assert server._dreamapi_provider_size({
        "api_ratio": ratio, "width": width, "height": height,
    }) == provider_size


def test_dreamapi_tall_ratio_uses_exact_native_canvas_without_resampling(
        tmp_path, monkeypatch):
    captured = {}
    encoded = png_b64(width=864, height=1536)

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "img_tall",
            "data": [{"b64_json": encoded}],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-tall", "prompt": "a careful portrait",
        "negative_prompt": "", "width": 864, "height": 1536,
        "api_ratio": "9:16", "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["body"]["size"] == "864x1536"
    assert job["api_provider_size"] == "864x1536"
    assert job["api_geometry_normalized"] is False
    assert job["images"][0]["output_size"] == "864x1536"
    output = Path(tmp_path) / "dreamapi.png"
    assert output.read_bytes() == base64.b64decode(encoded)
    with Image.open(output) as image:
        assert image.size == (864, 1536)


@pytest.mark.parametrize("model", [
    "gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
])
def test_dreamapi_all_models_are_selected_directly_without_tools(
        tmp_path, monkeypatch, model):
    captured = {}

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "img_direct",
            "data": [{"b64_json": png_b64(width=1024, height=1024)}],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-image2",
        "prompt": "a careful portrait",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "api_model": model,
        "api_quality": "low",
        "api_fit": "cover",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["body"]["model"] == model
    assert set(captured["body"]) == {
        "model", "prompt", "size", "quality", "n", "output_format",
    }
    assert job["api_transport"] == "images"


def test_dreamapi_mismatched_source_is_normalized_and_recorded(tmp_path, monkeypatch):
    captured = {}

    def fake_open(_request, data, _timeout):
        captured["body"] = json.loads(data.decode("utf-8"))
        return FakeResponse({
            "id": "img_mismatch",
            "data": [{"b64_json": png_b64(width=64, height=96)}],
        })

    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", fake_open)
    job = {
        "id": "dreamjob-sunburst",
        "prompt": "a careful portrait",
        "negative_prompt": "",
        "width": 1024,
        "height": 1024,
        "api_model": "gpt-image-2.5-flare",
        "api_quality": "low",
        "api_fit": "cover",
        "images": [],
    }

    server.dreamapi_run_image(job, tmp_path)

    assert captured["body"]["size"] == "1024x1024"
    assert job["api_geometry_normalized"] is True
    assert job["images"][0]["source_size"] == "64x96"
    assert job["images"][0]["output_size"] == "1024x1024"
    with Image.open(Path(tmp_path) / "dreamapi.png") as image:
        assert image.size == (1024, 1024)


def test_dreamapi_empty_data_reports_sanitized_response_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DREAMAPI_KEY", "test-key", raising=False)
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *_a, **_k: FakeResponse({
        "id": "img_empty", "created": 123, "data": [], "secret": "not-returned",
    }))
    job = {
        "id": "dreamjob-empty", "prompt": "test", "negative_prompt": "",
        "width": 1024, "height": 1024, "api_model": "gpt-image-2.5-flare",
        "api_quality": "low", "api_fit": "cover", "images": [],
    }
    with pytest.raises(RuntimeError) as caught:
        server.dreamapi_run_image(job, tmp_path)
    message = str(caught.value)
    assert "no completed image" in message
    assert "img_empty" in message
    assert "created,data,id,secret" in message
    assert "not-returned" not in message
    assert job["api_response_id"] == "img_empty"
    assert job["api_response_shape"] == "created,data,id,secret"


def test_dreamapi_runner_surfaces_bounded_json_error_detail(tmp_path, monkeypatch):
    body = io.BytesIO(json.dumps({"error": {"message": "upstream image worker unavailable"}}).encode())
    error = urllib.error.HTTPError(
        "https://dreamapi.club/v1/images/generations", 502, "Bad Gateway", {}, body
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
    error = urllib.error.HTTPError(
        "https://dreamapi.club/v1/images/generations", 401, "Unauthorized", {}, body,
    )
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


@pytest.mark.parametrize("payload", [None, [], 123, "bad", {"data": "bad"}, {"data": [None]}])
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
        "data": [{"b64_json": encoded}],
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
        "https://dreamapi.club/v1/images/generations", 502, "Bad Gateway", {}, SlowErrorBody()
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
