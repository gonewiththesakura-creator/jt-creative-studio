import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SPEC = importlib.util.spec_from_file_location("generic_rh_workflow_runtime", ROOT / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def fixture_workflow():
    return {
        "id": "fixture_3in1",
        "name": "Fixture 3in1",
        "desc": "test only",
        "kind": "rh_workflow",
        "backend": "runninghub",
        "rh_workflow_id": "9007199254740990",
        "rh_media": {
            "source_image": {
                "node": "101",
                "field": "image",
                "type": "image",
                "label": "二次元原图",
                "required": True,
            }
        },
        "rh_params": {
            "instruction": {
                "node": "102",
                "field": "text",
                "type": "text",
                "label": "转换要求",
                "default": "保留构图",
                "required": True,
            },
            "route_a": {
                "node": "103",
                "field": "enabled",
                "type": "boolean",
                "label": "输出写实A",
                "default": True,
            },
            "route_b": {
                "node": "104",
                "field": "enabled",
                "type": "boolean",
                "label": "输出写实B",
                "default": False,
            },
            "result_mode": {
                "node": "105",
                "field": "value",
                "type": "select",
                "label": "结果模式",
                "default": "three",
                "options": ["one", "two", "three"],
            },
            "quality_mode": {
                "node": "109",
                "field": "index",
                "type": "select",
                "label": "质量模式",
                "default": "1",
                "options": [
                    {"name": "快速", "index": "0", "description": "快速预览"},
                    {"name": "高清", "index": "1", "description": "高质量输出"},
                ],
            },
            "optional_note": {
                "node": "110",
                "field": "text",
                "type": "text",
                "label": "可选说明",
                "required": False,
            },
            "steps": {
                "node": "106",
                "field": "steps",
                "type": "int",
                "label": "采样步数",
                "default": 20,
                "min": 1,
                "max": 60,
            },
            "denoise": {
                "node": "107",
                "field": "denoise",
                "type": "float",
                "label": "重绘幅度",
                "default": 0.55,
                "min": 0.0,
                "max": 1.0,
            },
            "seed": {
                "node": "108",
                "field": "seed",
                "type": "int",
                "label": "种子",
                "default": 123,
                "min": 1,
                "max": 9007199254740991,
            },
        },
    }


def test_generic_schema_keeps_all_declared_controls_with_native_types():
    workflow = fixture_workflow()
    media, params = server.normalize_rh_workflow_inputs(
        workflow,
        {"source_image": "api/uploaded.png", "attacker_media": "drop-me"},
        {
            "instruction": "保留脸型与服装",
            "route_a": "false",
            "route_b": True,
            "result_mode": "two",
            "quality_mode": "0",
            "steps": "28",
            "denoise": "0.65",
            "seed": "246813579",
            "attacker_param": "drop-me",
        },
    )
    assert media == {"source_image": "api/uploaded.png"}
    assert params == {
        "instruction": "保留脸型与服装",
        "route_a": False,
        "route_b": True,
        "result_mode": "two",
        "quality_mode": "0",
        "steps": 28,
        "denoise": 0.65,
        "seed": 246813579,
    }
    mapped = {(row["nodeId"], row["fieldName"]): row["fieldValue"]
              for row in server.rh_build_generic_node_info({"media": media, "params": params}, workflow)}
    assert mapped == {
        ("101", "image"): "api/uploaded.png",
        ("102", "text"): "保留脸型与服装",
        ("103", "enabled"): False,
        ("104", "enabled"): True,
        ("105", "value"): "two",
        ("109", "index"): "0",
        ("106", "steps"): 28,
        ("107", "denoise"): 0.65,
        ("108", "seed"): 246813579,
    }


def test_generic_schema_applies_defaults_without_dropping_false():
    workflow = fixture_workflow()
    media, params = server.normalize_rh_workflow_inputs(
        workflow, {"source_image": "api/input.webp"}, {}
    )
    assert params["route_a"] is True
    assert params["route_b"] is False
    assert params["result_mode"] == "three"
    assert params["quality_mode"] == "1"
    assert params["steps"] == 20
    assert params["denoise"] == 0.55
    mapped = {(row["nodeId"], row["fieldName"]): row["fieldValue"]
              for row in server.rh_build_generic_node_info({"media": media, "params": params}, workflow)}
    assert mapped[("104", "enabled")] is False


@pytest.mark.parametrize(
    "media,params,message",
    [
        ({}, {}, "二次元原图"),
        ({"source_image": "api/a.png"}, {"result_mode": "four"}, "结果模式"),
        ({"source_image": "api/a.png"}, {"steps": 61}, "采样步数"),
        ({"source_image": "api/a.png"}, {"denoise": -0.1}, "重绘幅度"),
        ({"source_image": "api/a.png"}, {"route_a": "maybe"}, "输出写实A"),
        ({"source_image": "api/a.png"}, {"instruction": "", "steps": 20}, "转换要求"),
    ],
)
def test_generic_schema_rejects_missing_or_invalid_declared_values(media, params, message):
    with pytest.raises(ValueError, match=message):
        server.normalize_rh_workflow_inputs(fixture_workflow(), media, params)


def test_generic_runner_uses_only_trusted_workflow_id(monkeypatch):
    workflow = fixture_workflow()
    captured = {}

    def fake_submit(workflow_id, node_info_list, **kwargs):
        captured["workflow_id"] = workflow_id
        captured["nodes"] = node_info_list
        return "task-fixture"

    monkeypatch.setattr(server, "rh_submit", fake_submit)
    monkeypatch.setattr(server, "_rh_wait_task", lambda *args, **kwargs: [{"url": "https://example.invalid/result.png"}])
    job = {
        "id": "job-fixture",
        "media": {"source_image": "api/a.png"},
        "params": {"route_a": False, "route_b": True},
        "status": "running",
        "progress_pct": 0,
    }
    server.rh_run_generic(job, workflow)
    assert captured["workflow_id"] == "9007199254740990"
    assert job["rh_task_id"] == "task-fixture"
    assert job["status"] == "running"
    assert job["images"][0]["remote"] is True


def test_integer_controls_do_not_round_through_float():
    workflow = fixture_workflow()
    workflow["rh_params"]["seed"]["max"] = 9223372036854775807
    exact = 9223372036854775807
    _, params = server.normalize_rh_workflow_inputs(
        workflow,
        {"source_image": "api/a.png"},
        {"instruction": "保留构图", "seed": str(exact)},
    )
    assert params["seed"] == exact


def test_optional_blank_controls_are_omitted_but_false_is_preserved():
    workflow = fixture_workflow()
    _, params = server.normalize_rh_workflow_inputs(
        workflow,
        {"source_image": "api/a.png"},
        {"instruction": "保留构图", "optional_note": "", "route_b": False},
    )
    assert "optional_note" not in params
    assert params["route_b"] is False


def test_rh_submit_never_retries_an_ambiguous_transport_failure(monkeypatch):
    attempts = []

    def lost_response(*args, **kwargs):
        attempts.append(1)
        raise TimeoutError("response lost after provider may have accepted request")

    monkeypatch.setattr(server, "_urlopen_bounded", lost_response)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="outcome unknown"):
        server.rh_submit("trusted-id", [])
    assert len(attempts) == 1


def test_rh_submit_never_retries_a_response_that_already_has_task_id(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "status": "FAILED",
                "taskId": "possibly-billed-task",
                "errorCode": "TIMEOUT",
                "errorMessage": "provider timeout",
            }).encode()

    def answered(*args, **kwargs):
        attempts.append(1)
        return Response()

    monkeypatch.setattr(server, "_urlopen_bounded", answered)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="possibly-billed-task"):
        server.rh_submit("trusted-id", [])
    assert len(attempts) == 1


def test_rh_submit_does_not_retry_provider_timeout_without_task_id(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "status": "FAILED",
                "errorCode": "TIMEOUT",
                "errorMessage": "provider timeout",
            }).encode()

    def answered(*args, **kwargs):
        attempts.append(1)
        return Response()

    monkeypatch.setattr(server, "_urlopen_bounded", answered)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="TIMEOUT"):
        server.rh_submit("trusted-id", [])
    assert len(attempts) == 1


def test_remote_results_accept_only_http_urls():
    rows = server._rh_results_to_images(
        [
            {"url": "javascript:alert(1)"},
            {"fileUrl": "file:///etc/passwd"},
            {"url": "data:image/png;base64,AAAA"},
            {"url": "https://cdn.example.test/x.png\" onerror=\"alert(1)"},
            {"url": "https://user:pass@cdn.example.test/x.png"},
            {"url": "https://cdn.example.test/result.png"},
            {"fileUrl": "http://cdn.example.test/result.webp"},
        ],
        "task-safe",
    )
    assert [row["url"] for row in rows] == [
        "https://cdn.example.test/result.png",
        "http://cdn.example.test/result.webp",
    ]


def test_json_limit_preserves_existing_sixty_megabyte_video_upload_contract():
    encoded_sixty_mib = 4 * ((60 * 1024 * 1024 + 2) // 3)
    assert server.json_body_limit("/api/upload") > encoded_sixty_mib
    assert server.json_body_limit("/api/workflow-upload") == server.MAX_JSON_BYTES
    assert server.json_body_limit("/api/workflow-generate") == server.MAX_JSON_BYTES
    assert server.json_body_limit("/api/upload") == server.MAX_UPLOAD_JSON_BYTES


def test_public_schema_preserves_large_integers_as_decimal_strings():
    workflow = fixture_workflow()
    exact = 9223372036854775807
    workflow["rh_params"]["seed"].update({"default": exact, "max": exact})
    public = server.public_workflow(workflow)
    assert public["rh_params"]["seed"]["default"] == str(exact)
    assert public["rh_params"]["seed"]["max"] == str(exact)


def test_favorite_snapshot_preserves_large_integers_as_decimal_strings():
    workflow = fixture_workflow()
    exact = 9223372036854775807
    snapshot = server.normalize_realism_snapshot(
        workflow,
        {"source_image": "api/input.png"},
        {"seed": exact, "route_a": False},
        {"media_names": {"source_image": "input.png"}},
    )
    assert snapshot["params"]["seed"] == str(exact)
    assert snapshot["params"]["route_a"] is False
