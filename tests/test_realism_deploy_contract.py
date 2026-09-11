import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SCRIPT = ROOT / "tools" / "deploy_realism_release.py"
SPEC = importlib.util.spec_from_file_location("deploy_realism_release", SCRIPT)


def load_module():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def complete_workflow(internal_id, name, workflow_id):
    return {
        "id": internal_id,
        "name": name,
        "kind": "rh_workflow",
        "backend": "runninghub",
        "rh_workflow_id": workflow_id,
        "rh_schema_complete": True,
        "source_api_json_sha256": "a" * 64,
        "rh_media": {
            "source_image": {
                "node": "101",
                "field": "image",
                "type": "image",
                "required": True,
            }
        },
        "rh_params": {
            "enabled": {
                "node": "102",
                "field": "enabled",
                "type": "boolean",
                "default": False,
            }
        },
    }


def complete_config(module):
    return {
        "workflows": [
            complete_workflow(internal_id, name, str(2100000000000000000 + index))
            for index, (internal_id, name) in enumerate(module.TARGET_WORKFLOWS.items(), 1)
        ]
    }


def test_release_manifest_is_complete_and_excludes_nonproduction_files():
    module = load_module()
    expected = {
        "server.py",
        "config.json",
        "static/index.html",
        "static/promptgen.html",
        "static/original_sketch.html",
        "static/original_graphic.html",
        "static/realcomic.html",
        "static/realism.html",
        "static/video.html",
        "static/previews/manifest.json",
        "static/previews/realism-realcomic.webp",
        "static/previews/realism-krea2.webp",
        "static/previews/realism-2511.webp",
        "static/previews/realism-multisample.webp",
        "static/previews/realism-qwen-zi.webp",
        "static/previews/realism-zi-flowmatch.webp",
        "static/previews/style-cold.webp",
        "static/previews/style-sketch.webp",
        "static/previews/style-original-sketch.webp",
        "static/previews/style-graphic.webp",
        "static/previews/style-original-graphic.webp",
        "static/previews/style-hanmanga.webp",
        "static/previews/style-nff.webp",
        "static/previews/realism-realcomic.thumb.webp",
        "static/previews/realism-krea2.thumb.webp",
        "static/previews/realism-2511.thumb.webp",
        "static/previews/realism-multisample.thumb.webp",
        "static/previews/realism-qwen-zi.thumb.webp",
        "static/previews/realism-zi-flowmatch.thumb.webp",
        "static/previews/style-cold.thumb.webp",
        "static/previews/style-sketch.thumb.webp",
        "static/previews/style-original-sketch.thumb.webp",
        "static/previews/style-graphic.thumb.webp",
        "static/previews/style-original-graphic.thumb.webp",
        "static/previews/style-hanmanga.thumb.webp",
        "static/previews/style-nff.thumb.webp",
        "static/previews/style-retro-manga-luxury.webp",
        "static/previews/style-retro-manga-luxury.thumb.webp",
        "tools/panel_liveness_watchdog.py",
        "deploy/comfy-panel-watchdog.service",
        "deploy/comfy-panel-watchdog.timer",
    }
    assert set(module.RELEASE_RELATIVE_PATHS) == expected
    assert not any(path.startswith(("tests/", "audit/")) for path in module.RELEASE_RELATIVE_PATHS)


def test_release_creates_every_remote_parent_directory():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "remote_parent_paths" in source
    assert "mkdir -p" in source
    assert "pathlib.PurePosixPath(remote).parent" in source


def test_staging_upload_reconnects_and_verifies_each_file():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def stage_file_resilient" in source
    assert "for attempt in range(1, 4)" in source
    assert "client.open_sftp()" in source
    assert "staging mismatch" in source


def test_watchdog_units_are_installed_and_verified():
    source = SCRIPT.read_text(encoding="utf-8")
    service = (ROOT / "deploy" / "comfy-panel-watchdog.service").read_text(encoding="utf-8")
    assert "install_watchdog_units" in source
    assert "systemctl daemon-reload" in source
    assert "enable --now comfy-panel-watchdog.timer" in source
    assert "is-enabled comfy-panel-watchdog.timer" in source
    assert "is-active comfy-panel-watchdog.timer" in source
    assert "capture_watchdog_state" in source
    assert "restore_watchdog_state" in source
    assert "ExecStart=/usr/bin/python3 /usr/local/libexec/comfy-panel-watchdog.py" in service
    assert "/home/admin/comfy-panel/tools/panel_liveness_watchdog.py" not in service
    assert "sudo install -o root -g root -m 0755" in source
    assert "/usr/local/libexec/comfy-panel-watchdog.py" in source


def test_watchdog_rollback_restores_exact_unit_contents_and_states(monkeypatch):
    module = load_module()
    import base64
    old_service = b"[Service]\nExecStart=/old/panel-watchdog\n"
    captured = {
        "service_exists": True,
        "service_b64": base64.b64encode(old_service).decode(),
        "timer_exists": False,
        "timer_b64": "",
        "timer_enabled": "enabled",
        "timer_active": "active",
        "executable_exists": True,
        "executable_b64": base64.b64encode(b"#!/usr/bin/python3\n# old\n").decode(),
    }
    calls = []
    def fake_command(client, text, timeout=240):
        calls.append(text)
        return json.dumps(captured) if len(calls) == 1 else ""
    monkeypatch.setattr(module, "command", fake_command)
    state = module.capture_watchdog_state(object())
    module.restore_watchdog_state(object(), state)
    assert state == captured
    assert any(captured["service_b64"] in command for command in calls)
    assert any("rm -f /etc/systemd/system/comfy-panel-watchdog.timer" in command for command in calls)
    assert any("systemctl enable comfy-panel-watchdog.timer" in command for command in calls)
    assert any("systemctl start comfy-panel-watchdog.timer" in command for command in calls)
    assert any(captured["executable_b64"] in command for command in calls)


def test_release_gate_runs_script_contracts_and_pytest_files(tmp_path, monkeypatch):
    module = load_module()
    script_test = tmp_path / "test_script_contract.py"
    pytest_test = tmp_path / "test_runtime.py"
    script_test.write_text("raise SystemExit(0)\n", encoding="utf-8")
    pytest_test.write_text("def test_runtime():\n    assert True\n", encoding="utf-8")
    scripts, pytest_files = module.classify_release_tests(tmp_path)
    assert scripts == [script_test]
    assert pytest_files == [pytest_test]

    calls = []
    class Result:
        returncode = 0
        stdout = ""
    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.run_release_tests(tmp_path)
    assert [module.sys.executable, str(script_test)] in calls
    assert any(call[:4] == [module.sys.executable, "-m", "pytest", "-q"] and str(pytest_test) in call for call in calls)


def test_release_gate_has_one_strict_known_baseline_script_failure(tmp_path, monkeypatch):
    module = load_module()
    baseline = tmp_path / "test_restore_prompt_contract.py"
    baseline.write_text("raise SystemExit(1)\n", encoding="utf-8")

    class Result:
        def __init__(self, code, stdout):
            self.returncode = code
            self.stdout = stdout

    expected = "\n".join(module.KNOWN_BASELINE_SCRIPT_FAILURES[baseline.name]) + "\n"
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result(1, expected))
    module.run_release_tests(tmp_path)

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result(0, ""))
    with pytest.raises(RuntimeError, match="unexpectedly passed"):
        module.run_release_tests(tmp_path)

    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *args, **kwargs: Result(1, "Traceback: SyntaxError\n"),
    )
    with pytest.raises(RuntimeError, match="baseline output changed"):
        module.run_release_tests(tmp_path)

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result(2, expected))
    with pytest.raises(RuntimeError, match="baseline exit code changed"):
        module.run_release_tests(tmp_path)


def test_current_config_passes_without_credentials_or_ssh_needed():
    module = load_module()
    current = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    result = module.validate_release_config(current)
    assert result["ready"] is True
    assert result["missing_targets"] == []
    assert result["invalid_targets"] == []


def test_complete_real_workflows_pass_config_validation():
    module = load_module()
    result = module.validate_release_config(complete_config(module))
    assert result == {"ready": True, "missing_targets": [], "invalid_targets": []}


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("rh_workflow_id", "fixture-never-sent", "provider id"),
        ("rh_workflow_id", "123", "provider id"),
        ("rh_schema_complete", False, "schema"),
        ("source_api_json_sha256", "not-a-hash", "source hash"),
        ("rh_media", {}, "media"),
        ("rh_params", {}, "params"),
    ],
)
def test_incomplete_or_placeholder_workflows_block_release(field, value, reason):
    module = load_module()
    config = complete_config(module)
    config["workflows"][0][field] = value
    result = module.validate_release_config(config)
    assert result["ready"] is False
    assert result["missing_targets"] == []
    assert any(reason in item["reasons"] for item in result["invalid_targets"])


def test_unauthenticated_server_requires_separate_explicit_acceptance():
    module = load_module()
    source = "class Handler:\n    def _auth(self):\n        return True\n"
    assert module.auth_is_disabled(source) is True
    decision = module.preflight_decision(
        complete_config(module),
        source,
        execute=True,
        allow_unauthenticated_public=False,
    )
    assert decision["ready"] is False
    assert "unauthenticated public access not accepted" in decision["blockers"]


def test_dry_run_never_allows_remote_mutation_even_when_config_is_complete():
    module = load_module()
    authenticated = "class Handler:\n    def _auth(self):\n        return self.headers.get('X') == 'Y'\n"
    decision = module.preflight_decision(
        complete_config(module),
        authenticated,
        execute=False,
        allow_unauthenticated_public=False,
    )
    assert decision["config_ready"] is True
    assert decision["ready"] is False
    assert "--execute not supplied" in decision["blockers"]


def test_release_targets_match_all_six_active_private_workflows():
    module = load_module()
    expected = {
        "realism_krea2", "realism_2511", "realism_multisample", "realism_qwen_zi",
        "realism_4k_text", "realism_zi_flowmatch",
    }
    assert set(module.TARGET_WORKFLOW_IDS) == expected
    current = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    result = module.validate_release_config(current)
    assert result["ready"] is True
    assert result["missing_targets"] == []
    assert result["invalid_targets"] == []


def test_atomic_release_contract_contains_stage_backup_verify_and_rollback():
    text = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
    required = [
        ".realism-release.new",
        "backup_release",
        "rollback_release",
        "staging mismatch",
        "live mismatch",
        "posix_rename",
        "systemctl stop comfy-panel",
        "systemctl start comfy-panel",
        "/api/health",
        "/realism",
        "/api/workflows",
        "PUBLIC_MARKERS_OK",
    ]
    assert all(token in text for token in required)
    assert all(marker in text for marker in ["fixture_3in1", "fixture-never-sent", "realism_fixture"])
    module = load_module()
    assert not any(path.startswith(("tests/", "audit/")) for path in module.RELEASE_RELATIVE_PATHS)
    assert "RUNNINGHUB_API_KEY=" not in text


def test_release_pins_the_ssh_host_key_before_password_authentication():
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "AutoAddPolicy" not in source
    assert "PinnedSHA256Policy" in source
    assert "hmac.compare_digest" in source
    assert module.SSH_HOST_KEY_SHA256.startswith("SHA256:")
    assert len(module.SSH_HOST_KEY_SHA256) == 50


def test_release_stops_the_service_for_the_complete_file_set_switch():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args", 1)[0]
    stop_at = deploy_body.index('command(client, "sudo systemctl stop comfy-panel"')
    switch_at = deploy_body.index("for remote in remote_paths:", stop_at)
    verify_at = deploy_body.index("live mismatch", switch_at)
    start_at = deploy_body.index('command(client, "sudo systemctl start comfy-panel"', verify_at)
    assert stop_at < switch_at < verify_at < start_at

    rollback_body = source.split("def rollback_release(", 1)[1].split("def fetch_json", 1)[0]
    rollback_stop = rollback_body.index('command(client, "sudo systemctl stop comfy-panel"')
    restore_at = rollback_body.index("for remote in remote_paths:")
    rollback_start = rollback_body.index(
        'command(client, "sudo systemctl start comfy-panel"', restore_at
    )
    assert rollback_stop < restore_at < rollback_start


def test_release_reads_back_the_new_creator_style_and_exact_preview_bytes():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args", 1)[0]
    for marker in ["retro_manga_luxury", "jt_style321_v1", "style-retro-manga-luxury.webp"]:
        assert marker in deploy_body
    assert "verify_public_large_responses(public_base)" in deploy_body
    helper_body = source.split("def verify_public_large_responses(", 1)[1].split("def wait_for_health", 1)[0]
    assert 'fetch_bytes(base, "/static/previews/style-retro-manga-luxury.webp")' in helper_body
    assert "public creator preview mismatch" in helper_body
    assert "for attempt in range(3)" in helper_body


def test_release_liveness_does_not_depend_on_local_comfy_tunnel():
    module = load_module()
    assert hasattr(module, "wait_for_live")
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args", 1)[0]
    rollback_body = source.split("def rollback_release(", 1)[1].split("def fetch_json", 1)[0]
    assert "wait_for_live(public_base" in deploy_body
    assert "wait_for_live(public_base" in rollback_body
    assert 'not health.get("local_comfy_ok")' not in deploy_body


def test_rollback_liveness_accepts_the_previous_release_without_api_live(monkeypatch):
    module = load_module()
    calls = []
    def fake_fetch(base, path):
        calls.append(path)
        if path == "/api/live":
            raise module.urllib.request.HTTPError(base + path, 404, "missing", {}, None)
        if path == "/api/workflows":
            return [{"id": "anima02"}]
        raise AssertionError(path)
    monkeypatch.setattr(module, "fetch_json", fake_fetch)
    assert module.wait_for_live("http://old", timeout=0.1, allow_legacy=True) == {
        "ok": True, "service": "comfy-panel-legacy"
    }
    assert calls == ["/api/live", "/api/workflows"]


def test_release_rollback_uses_manifest_retry_and_post_restore_verification():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "BACKUP_MANIFEST" in text
    assert 'stat.st_size == 0' not in text
    assert "wait_for_health" in text
    assert "rollback verification mismatch" in text
    assert "rollback health failed" in text


def test_rollback_attempts_to_start_panel_even_when_a_file_restore_fails(monkeypatch):
    module = load_module()
    remote_paths = ["/remote/a", "/remote/b"]
    manifest = {
        "/remote/a": {"exists": True, "sha256": "a" * 64},
        "/remote/b": {"exists": True, "sha256": "b" * 64},
    }
    calls = []

    def fake_command(client, text, timeout=240):
        calls.append(text)
        if "BACKUP_MANIFEST" in text or ".pre-realism-release-manifest.json" in text:
            return json.dumps(manifest)
        if text.startswith("cp --") and "/remote/b" in text:
            raise RuntimeError("restore b failed")
        if "hashlib.sha256" in text and "/remote/a" in text:
            return "a" * 64 + "\n"
        if "hashlib.sha256" in text and "/remote/b" in text:
            return "b" * 64 + "\n"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: {"ok": True})
    with pytest.raises(RuntimeError, match="restore b failed"):
        module.rollback_release(object(), object(), remote_paths, public_base="http://test")
    assert any("systemctl start comfy-panel" in text for text in calls)


def test_rollback_attempts_to_start_panel_when_backup_manifest_is_unreadable(monkeypatch):
    module = load_module()
    calls = []

    def fake_command(client, text, timeout=240):
        calls.append(text)
        if ".pre-realism-release-manifest.json" in text:
            return "not-json"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: {"ok": True})
    with pytest.raises(RuntimeError, match="backup manifest"):
        module.rollback_release(object(), object(), ["/remote/a"], public_base="http://test")
    assert any("systemctl start comfy-panel" in text for text in calls)


def test_release_requires_clean_git_tests_and_historical_e2e_records():
    module = load_module()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "E2E_MANIFEST" in text
    assert "validate_e2e_manifest" in text
    assert "require_clean_git" in text
    assert "run_release_tests" in text
    assert module.KNOWN_BASELINE_SCRIPT_FAILURES == {
        "test_restore_prompt_contract.py": (
            "restore endpoint False", "bounded upload False", "PNG signature validation False",
            "PNG text parser False", "prompt metadata extractor False", "history filename lookup False",
            "parameter extraction False", "restore source confidence False", "no vision guessing False",
            "upload control False", "restore button False", "restore status False",
            "restore raw prompt False", "restore parameters False", "restore mapped selections False",
            "restore uses raw upload False", "unmatched terms retained False",
        )
    }
    manifest = json.loads((ROOT / "audit" / "private_realism_workflows" / "e2e_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["successful_workflows"]) == 7
    assert all(row["status"] == "SUCCESS" for row in manifest["successful_workflows"])
