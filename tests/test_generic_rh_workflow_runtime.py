import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
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
              for row in server.rh_build_generic_node_info({"provider_media": media, "params": params}, workflow)}
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
              for row in server.rh_build_generic_node_info({"provider_media": media, "params": params}, workflow)}
    assert mapped[("104", "enabled")] is False


def test_video_media_fallback_overrides_author_sample_assets():
    workflow = {
        "rh_media": {
            "main": {"node": "1", "field": "image", "type": "image", "required": True},
            "angle": {"node": "2", "field": "image", "type": "image", "fallback_to": "main"},
        },
        "rh_params": {},
    }
    rows = server.rh_build_video_node_info(
        {"provider_media": {"main": "api/user.png"}, "params": {}, "prompt": "", "negative_prompt": ""},
        workflow,
    )
    assert rows == [
        {"nodeId": "1", "fieldName": "image", "fieldValue": "api/user.png"},
        {"nodeId": "2", "fieldName": "image", "fieldValue": "api/user.png"},
    ]


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


def test_generic_runner_uses_only_trusted_instance_type(monkeypatch):
    workflow = fixture_workflow()
    workflow["rh_instance_type"] = "plus"
    captured = {}
    def fake_submit(workflow_id, node_info_list, instance_type="default", **kwargs):
        captured["instance_type"] = instance_type
        return "task-plus"
    monkeypatch.setattr(server, "rh_submit", fake_submit)
    monkeypatch.setattr(server, "_rh_wait_task", lambda *args, **kwargs: [{"url": "https://example.invalid/result.png"}])
    server.rh_run_generic({"id": "j", "media": {}, "params": {}, "progress_pct": 0}, workflow)
    assert captured["instance_type"] == "plus"


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


def test_consume_coins_is_task_level_and_never_summed_per_output():
    assert server.normalize_rh_coins({"usage": {"consumeCoins": "64"}}, []) == "64"
    repeated = [{"consumeCoins": "64"}, {"consumeCoins": "64"}, {"consumeCoins": "64"}]
    assert server.normalize_rh_coins({}, repeated) == "64"
    assert server.normalize_rh_coins({}, [{"consumeCoins": "17.5"}]) == "17.5"
    assert server.normalize_rh_coins({}, [{"consumeCoins": "64"}, {"consumeCoins": "65"}]) is None
    assert server.normalize_rh_coins({"usage": {"consumeCoins": None}}, []) is None


@pytest.mark.parametrize("response, expected", [
    ({"status": "", "errorCode": "1004", "errorMessage": "Task not found"}, "RH_TASK_UNAVAILABLE"),
    ({"status": "CANCELLED"}, "RH_TASK_STOPPED"),
    ({"status": "CANCELED"}, "RH_TASK_STOPPED"),
    ({"status": "STOPPED"}, "RH_TASK_STOPPED"),
])
def test_rh_terminal_stop_does_not_keep_polling(monkeypatch, response, expected):
    monkeypatch.setattr(server, "_provider_json_request", lambda *a, **k: response)
    monkeypatch.setattr(server.time, "sleep", lambda *a: pytest.fail("terminal task must not sleep"))
    job = {"id": "stopped", "generation_backend": "cloud"}
    with pytest.raises(server.ProviderTaskFailed, match=expected):
        server._rh_wait_task(job, "known-task", server.time.time() + 60)
    assert job["provider_status"] in {"STOPPED", "UNAVAILABLE"}
    public = server.public_job_error(job | {"error": expected})
    assert ("停止" if expected == "RH_TASK_STOPPED" else "不存在或已过期") in public


def test_rh_query_persists_v2_usage_on_job(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"status": "SUCCESS", "results": [{"url": "https://example.test/a.png"}],
                               "usage": {"consumeCoins": "23"}}).encode()
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *args, **kwargs: Response())
    job = {}
    status, results = server.rh_query("task-coins", job=job)
    assert status == "SUCCESS" and results
    assert job["rh_coins"] == "23"


def test_completed_job_coin_backfill_queries_once(monkeypatch):
    calls = []
    job = {"status": "done", "rh_task_id": "old-task"}
    def query(task_id, job=None):
        calls.append(task_id); job["rh_coins"] = "31"; return "SUCCESS", []
    monkeypatch.setattr(server, "rh_query", query)
    assert server.backfill_rh_coins(job) == "31"
    assert server.backfill_rh_coins(job) == "31"
    assert calls == ["old-task"]


def test_non_runninghub_jobs_do_not_backfill_coins(monkeypatch):
    monkeypatch.setattr(server, "rh_query", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not query")))
    assert server.backfill_rh_coins({"status": "done"}) is None


def test_failed_provider_job_can_backfill_charged_coins(monkeypatch):
    job = {"status": "error", "rh_task_id": "failed-task"}
    def query(task_id, job=None):
        job["rh_coins"] = "9"
        raise RuntimeError("provider task failed")
    monkeypatch.setattr(server, "rh_query", query)
    assert server.backfill_rh_coins(job) == "9"


def test_history_scope_filters_before_limit():
    jobs = [
        {"id": "new-realism", "workflow": "realism_3in1", "created": 50},
        {"id": "video", "workflow": "h3_t2v_i2v", "created": 40},
        {"id": "sketch", "workflow": "anima02", "style_id": "sketch", "created": 30},
        {"id": "graphic", "workflow": "anima02", "style_id": "graphic", "created": 20},
        {"id": "style221", "workflow": "anima02", "style_id": "style221", "created": 19},
        {"id": "style222", "workflow": "anima02", "style_id": "style222", "created": 18},
    ]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "video")] == ["video"]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "creator")] == ["sketch", "graphic", "style221", "style222"]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "creator", "sketch")] == ["sketch"]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "creator", "style221")] == ["style221"]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "creator", "style222")] == ["style222"]
    assert [x["id"] for x in server.scoped_history_jobs(jobs, "realism")] == ["new-realism"]


def test_failed_task_error_includes_actionable_node_detail(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"code": 805, "data": {"failedReason": {
                "node_id": "87", "node_name": "SeedVR2VideoUpscaler",
                "exception_type": "torch.OutOfMemoryError",
                "exception_message": "insufficient VRAM; use plus instance",
            }}}).encode()
    monkeypatch.setattr(server, "_urlopen_bounded", lambda *args, **kwargs: Response())
    detail = server.rh_failed_task_detail("task-805")
    assert "节点87" in detail
    assert "SeedVR2VideoUpscaler" in detail
    assert "OutOfMemoryError" in detail
    assert "plus instance" in detail


def test_restart_resumes_existing_cloud_task_without_resubmission(monkeypatch):
    job = {"id": "restart-job", "workflow": "fixture", "status": "recovering",
           "generation_backend": "cloud", "rh_task_id": "existing-task", "images": [], "progress_pct": 5}
    monkeypatch.setattr(server, "_rh_wait_task", lambda *args, **kwargs: [{"url": "https://example.test/recovered.png"}])
    monkeypatch.setattr(server, "save_jobs", lambda: None)
    monkeypatch.setattr(server, "rh_submit", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not resubmit")))
    server.resume_cloud_job(job)
    assert job["status"] == "done"
    assert job["provider_status"] == "DONE"
    assert job["images"][0]["url"].endswith("recovered.png")


def test_provider_task_id_is_persisted_immediately(monkeypatch):
    saved = []
    monkeypatch.setattr(server, "save_jobs", lambda: saved.append(True))
    job = {"id": "persist-now"}
    server.persist_provider_task(job, "provider-task")
    assert job["rh_task_id"] == "provider-task"
    assert saved == [True]
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert source.count("persist_provider_task(job, task_id)") >= 5


def test_multistage_jobs_are_not_misreported_as_recovered_complete(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"seq": {"id": "seq", "status": "running",
        "generation_backend": "cloud", "rh_task_id": "last-stage",
        "sequence_mode": "sketch3", "rh_task_ids": ["stage-1", "last-stage"]}}), encoding="utf-8")
    monkeypatch.setattr(server, "JOBS_FILE", jobs_file)
    monkeypatch.setattr(server, "save_jobs", lambda: None)
    server.load_jobs()
    assert server._jobs["seq"]["status"] == "error"
    assert "多阶段" in server._jobs["seq"]["error"]


def test_comfy_output_names_cannot_escape_job_directory():
    import tempfile
    root = Path(tempfile.mkdtemp())
    for name in ("../escape.png", "C:/escape.png", "/tmp/escape.png", "sub/escape.png"):
        with pytest.raises(ValueError):
            server.safe_output_filename(name)
    assert server.safe_output_filename("result_00001_.png") == "result_00001_.png"


def test_http_server_has_bounded_request_concurrency():
    assert 16 <= server.BoundedHTTPServer.max_workers <= 64
    assert server.BoundedHTTPServer.request_queue_size >= 64
    assert server.CLIENT_SOCKET_TIMEOUT <= 10
    assert server.MAX_REQUESTS_PER_CONNECTION == 1
    assert hasattr(server.BoundedHTTPServer, "process_request_thread")


def test_load_jobs_marks_provider_task_for_recovery(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"cloud": {"id": "cloud", "status": "running",
        "generation_backend": "cloud", "rh_task_id": "existing-task"},
        "unknown": {"id": "unknown", "status": "running", "generation_backend": "cloud"}}), encoding="utf-8")
    monkeypatch.setattr(server, "JOBS_FILE", jobs_file)
    monkeypatch.setattr(server, "save_jobs", lambda: None)
    server.load_jobs()
    assert server._jobs["cloud"]["status"] == "recovering"
    assert server._jobs["cloud"]["rh_task_id"] == "existing-task"
    assert server._jobs["unknown"]["status"] == "error"


def test_load_jobs_migrates_unicode_remote_result_urls_without_resubmitting(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({
        "done": {
            "id": "done", "status": "done", "generation_backend": "cloud",
            "rh_task_id": "existing-task",
            "images": [{
                "url": "https://cdn.example.test/output/压缩文件.zip?name=结果",
                "preview_url": "https://cdn.example.test/output/压缩文件.zip?name=结果",
                "file": "压缩文件.zip", "remote": True,
            }],
        }
    }, ensure_ascii=False), encoding="utf8")
    monkeypatch.setattr(server, "JOBS_FILE", jobs_file)
    saved = []
    monkeypatch.setattr(server, "save_jobs", lambda: saved.append(True))
    server.load_jobs()
    job = server._jobs["done"]
    assert job["status"] == "done" and job["rh_task_id"] == "existing-task"
    assert job["images"][0]["url"].isascii()
    assert "%E5%8E%8B%E7%BC%A9%E6%96%87%E4%BB%B6" in job["images"][0]["url"]
    assert job["images"][0]["file"] == "压缩文件.zip"
    assert saved == [True]


def test_json_limit_preserves_existing_sixty_megabyte_video_upload_contract():
    encoded_sixty_mib = 4 * ((60 * 1024 * 1024 + 2) // 3)
    assert server.json_body_limit("/api/upload") > encoded_sixty_mib
    assert server.json_body_limit("/api/workflow-upload") == server.MAX_JSON_BYTES
    assert server.json_body_limit("/api/workflow-generate") == server.MAX_JSON_BYTES
    assert server.json_body_limit("/api/upload") == server.MAX_UPLOAD_JSON_BYTES


def test_favorites_are_deduplicated_and_bounded():
    assert server.MAX_FAVORITES == 200
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "existing_favorite" in source
    assert "prune_favorites" in source


def test_concurrent_favorite_requests_download_and_persist_once(tmp_path, monkeypatch):
    import http.client
    import http.server
    import threading

    server.DATA_DIR = tmp_path
    server.JOBS_DIR = tmp_path / "jobs"; server.JOBS_DIR.mkdir()
    server.FAVORITES_DIR = tmp_path / "favorites"; server.FAVORITES_DIR.mkdir()
    server.JOBS_FILE = tmp_path / "jobs.json"
    server.FAVORITES_FILE = tmp_path / "favorites.json"
    server._favorites = {}
    session_id = "favorite-concurrency-session-1234567890"
    cookie = "jt_session=" + server._encode_session_cookie(session_id)
    server._jobs = {"same-job": {"id": "same-job", "status": "done", "prompt": "<img id=pwn onerror=alert(1)>",
        "request_session_hash": server._session_hash(session_id),
        "images": [{"url": "https://example.test/result.png", "remote": True}]}}
    downloads = []
    def fake_download(url, dest, timeout=120):
        downloads.append(url)
        Path(dest).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    monkeypatch.setattr(server, "download_file_resilient", fake_download)
    monkeypatch.setattr(server, "image_content_type", lambda *_: "image/png")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    barrier = threading.Barrier(3); results = []
    def post():
        barrier.wait()
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
        body = json.dumps({"job_id": "same-job", "image_index": 0}).encode()
        conn.request("POST", "/api/favorites", body, {"Content-Type": "application/json", "Cookie": cookie})
        response = conn.getresponse(); results.append((response.status, json.loads(response.read())))
        conn.close()
    workers = [threading.Thread(target=post) for _ in range(2)]
    for worker in workers: worker.start()
    barrier.wait()
    for worker in workers: worker.join(timeout=10)
    httpd.shutdown(); httpd.server_close(); thread.join(timeout=3)
    assert [status for status, _ in results] == [200, 200]
    assert len({payload["id"] for _, payload in results}) == 1
    assert len(downloads) == 1
    assert len(server._favorites) == 1
    assert len(list(server.FAVORITES_DIR.glob("*"))) == 1


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
