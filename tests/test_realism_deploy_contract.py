import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "deploy_realism_release.py"
RETRO_CLOUD_E2E = ROOT / "audit" / "retro_manga_panel_e2e_cloud_w04.json"
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
        "service_active": "inactive",
        "service_enabled": "disabled",
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


def test_release_gate_has_no_known_red_test_exceptions():
    module = load_module()
    assert module.KNOWN_BASELINE_SCRIPT_FAILURES == {}


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
        "new_release_transaction",
        "acquire_release_lock",
        "release_release_lock",
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


def test_release_uses_exclusive_remote_lock_and_unique_transaction_paths():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'RELEASE_LOCK_DIR = REMOTE_ROOT + "/.release.lock"' in source
    assert 'RELEASE_TRANSACTIONS_DIR = REMOTE_ROOT + "/.release-transactions"' in source
    assert "uuid.uuid4().hex" in source
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args", 1)[0]
    assert "transaction = new_release_transaction()" in deploy_body
    assert "acquire_release_lock(client, transaction)" in deploy_body
    assert "release_release_lock(client, transaction)" in deploy_body
    assert "transaction_file(transaction" in deploy_body
    assert deploy_body.index("acquire_release_lock") < deploy_body.index("stage_file_resilient")
    assert deploy_body.rindex("release_release_lock") > deploy_body.index("rollback_release")


def test_backup_manifest_is_atomically_written_and_hash_verified_before_restore():
    source = SCRIPT.read_text(encoding="utf-8")
    backup = source.split("def backup_release(", 1)[1].split("def rollback_release", 1)[0]
    rollback = source.split("def rollback_release(", 1)[1].split("def fetch_json", 1)[0]
    assert "manifest_tmp" in backup and "replace(" in backup
    assert "manifest_sha256" in backup
    assert "hashlib.sha256" in backup
    assert "hmac.compare_digest" in rollback
    assert rollback.index("hmac.compare_digest") < rollback.index("for remote in remote_paths")


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
    assert '"/static/previews/style-retro-manga-luxury.webp"' in helper_body
    assert "timeout=300" in helper_body
    assert "attempts=3" in helper_body
    assert "deadline=deadline" in helper_body
    assert "public creator preview mismatch" in helper_body
    assert "for attempt in range(3)" in helper_body
    assert "accept_gzip=True" in helper_body
    assert "timeout=300" in helper_body
    assert "fetch_bytes_resilient" in helper_body
    assert "PUBLIC_LARGE_VERIFY_TIMEOUT" in helper_body
    assert "time.monotonic()" in helper_body
    assert "public large response verification timeout" in helper_body


def test_resilient_fetch_retries_within_a_single_wall_clock_budget(monkeypatch):
    module = load_module()
    calls = []
    ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks, 2.0))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def flaky(base, path, timeout=60, accept_gzip=False):
        calls.append(timeout)
        if len(calls) < 3:
            raise TimeoutError("transient")
        return b"ok"

    monkeypatch.setattr(module, "fetch_bytes", flaky)
    assert module.fetch_bytes_resilient(
        "http://test", "/large", timeout=20, attempts=3, deadline=30.0
    ) == b"ok"
    assert len(calls) == 3
    assert all(0 < value <= 20 for value in calls)


def test_resilient_fetch_stops_when_wall_clock_budget_is_exhausted(monkeypatch):
    module = load_module()
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks, 31.0))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        module, "fetch_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("transient")),
    )
    with pytest.raises(RuntimeError, match="public large response verification timeout"):
        module.fetch_bytes_resilient(
            "http://test", "/large", timeout=20, attempts=3, deadline=30.0
        )


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
    assert "transaction['manifest']" in text
    assert "transaction['manifest_sha256']" in text
    assert 'stat.st_size == 0' not in text
    assert "wait_for_live" in text
    assert "rollback verification mismatch" in text
    assert "rollback health failed" in text


def test_rollback_keeps_panel_stopped_when_a_file_restore_fails(monkeypatch):
    module = load_module()
    remote_paths = [module.REMOTE_ROOT + "/a", module.REMOTE_ROOT + "/b"]
    manifest = {
        remote_paths[0]: {"exists": True, "sha256": "a" * 64, "mode": 0o640},
        remote_paths[1]: {"exists": True, "sha256": "b" * 64, "mode": 0o600},
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_digest = module.hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()
    calls = []

    def fake_command(client, text, timeout=240):
        calls.append(text)
        if "/tx/manifest.sha256" in text:
            return manifest_digest + "\n"
        if "/tx/manifest.json" in text:
            return manifest_raw
        if text.startswith("cp --") and remote_paths[1] in text:
            raise RuntimeError("restore b failed")
        if "hashlib.sha256" in text and (remote_paths[0] in text or "/tx/backup/a" in text):
            return "a" * 64 + "\n"
        if "hashlib.sha256" in text and (remote_paths[1] in text or "/tx/backup/b" in text):
            return "b" * 64 + "\n"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: {"ok": True})
    transaction = {
        "manifest": "/tx/manifest.json", "manifest_sha256": "/tx/manifest.sha256",
        "backup_root": "/tx/backup",
    }
    with pytest.raises(RuntimeError, match="restore b failed"):
        module.rollback_release(object(), object(), remote_paths, transaction, public_base="http://test")
    assert any("systemctl stop comfy-panel" in text for text in calls)
    assert not any("systemctl start comfy-panel" in text for text in calls)


def test_rollback_keeps_panel_stopped_when_backup_manifest_is_unreadable(monkeypatch):
    module = load_module()
    calls = []

    def fake_command(client, text, timeout=240):
        calls.append(text)
        if "/tx/manifest.json" in text:
            return "not-json"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: {"ok": True})
    transaction = {"manifest": "/tx/manifest.json", "manifest_sha256": "/tx/manifest.sha256"}
    with pytest.raises(RuntimeError, match="backup manifest"):
        module.rollback_release(object(), object(), ["/remote/a"], transaction, public_base="http://test")
    assert any("systemctl stop comfy-panel" in text for text in calls)
    assert not any("systemctl start comfy-panel" in text for text in calls)


def test_rollback_keeps_panel_stopped_when_liveness_check_raises(monkeypatch):
    module = load_module()
    remote = module.REMOTE_ROOT + "/a"
    manifest = {remote: {"exists": True, "sha256": "a" * 64, "mode": 0o640}}
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_digest = module.hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()
    calls = []

    def fake_command(client, text, timeout=240):
        calls.append(text)
        if "/tx/manifest.sha256" in text:
            return manifest_digest + "\n"
        if "/tx/manifest.json" in text:
            return manifest_raw
        if "hashlib.sha256" in text:
            return "a" * 64 + "\n"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("liveness timeout: connection refused")))
    transaction = {
        "manifest": "/tx/manifest.json", "manifest_sha256": "/tx/manifest.sha256",
        "backup_root": "/tx/backup",
    }
    with pytest.raises(RuntimeError, match="rollback health"):
        module.rollback_release(object(), object(), [remote], transaction,
                                public_base="http://test")
    start_index = max(i for i, text in enumerate(calls)
                      if "systemctl start comfy-panel" in text)
    assert any(i > start_index and "systemctl stop comfy-panel" in text
               for i, text in enumerate(calls))


def test_deploy_stops_and_masks_watchdog_service_and_timer_before_swap():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    isolation_at = deploy_body.index("isolate_watchdog(client)")
    stop_at = deploy_body.index('command(client, "sudo systemctl stop comfy-panel"')
    swap_at = deploy_body.index("for remote in remote_paths:", stop_at)
    assert isolation_at < stop_at < swap_at


def test_watchdog_isolation_fails_closed_and_verifies_systemd_state(monkeypatch):
    module = load_module()
    calls = []
    def fake_command(client, text, timeout=240):
        calls.append(text)
        if text.startswith("python3 -c"):
            return "inactive\ninactive\nmasked-runtime\n"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    module.isolate_watchdog(object())
    assert calls[:3] == [
        "sudo systemctl disable --now comfy-panel-watchdog.timer",
        "sudo systemctl stop comfy-panel-watchdog.service",
        "sudo systemctl mask --runtime comfy-panel-watchdog.service",
    ]
    assert all("|| true" not in command for command in calls[:3])
    assert len(calls) == 4 and calls[3].startswith("python3 -c")


def test_watchdog_isolation_rejects_any_non_isolated_state(monkeypatch):
    module = load_module()
    for replies in (["active", "inactive", "masked"],
                    ["inactive", "active", "masked"],
                    ["inactive", "inactive", "disabled"]):
        payload = "\n".join(replies) + "\n"
        monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                            payload if text.startswith("python3 -c") else "")
        with pytest.raises(RuntimeError, match="watchdog isolation failed"):
            module.isolate_watchdog(object())


def test_watchdog_restore_preserves_runtime_timer_mask(monkeypatch):
    module = load_module()
    state = {
        "service_exists": False, "service_b64": "",
        "timer_exists": False, "timer_b64": "",
        "executable_exists": False, "executable_b64": "",
        "service_active": "inactive", "service_enabled": "disabled",
        "timer_active": "inactive", "timer_enabled": "masked-runtime",
    }
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or "")
    module.restore_watchdog_state(object(), state)
    assert any("mask --runtime comfy-panel-watchdog.timer" in text for text in calls)


def test_watchdog_state_probe_accepts_expected_nonzero_systemctl_status(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or "inactive\ninactive\nmasked\n")
    assert module.watchdog_isolation_state(object()) == ("inactive", "inactive", "masked")
    assert len(calls) == 1
    assert "subprocess.run" in calls[0]


def test_watchdog_snapshot_restores_service_mask_state(monkeypatch):
    module = load_module()
    import base64
    captured = {
        "service_exists": True, "service_b64": base64.b64encode(b"service").decode(),
        "timer_exists": True, "timer_b64": base64.b64encode(b"timer").decode(),
        "executable_exists": True, "executable_b64": base64.b64encode(b"script").decode(),
        "service_active": "inactive", "service_enabled": "masked-runtime",
        "timer_active": "inactive", "timer_enabled": "masked",
    }
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or (json.dumps(captured) if len(calls) == 1 else ""))
    state = module.capture_watchdog_state(object())
    module.restore_watchdog_state(object(), state)
    assert state["service_enabled"] == "masked-runtime"
    assert any("mask --runtime comfy-panel-watchdog.service" in text for text in calls)
    assert any("mask comfy-panel-watchdog.timer" in text for text in calls)


def test_deploy_keeps_lock_after_uncertain_rollback():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert "rollback_uncertain" in deploy_body
    assert 'if lock_acquired and not rollback_uncertain:' in deploy_body


def test_watchdog_restore_failure_keeps_release_lock_and_marks_rollback_failed():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    restore_tail = deploy_body.split("restore_watchdog_state(client, watchdog_state)", 1)[1]
    failure_block = restore_tail.split("raise\n            raise", 1)[0]
    assert "except Exception:" in failure_block
    assert "rollback_uncertain = True" in failure_block
    assert 'write_transaction_phase(client, transaction, "rollback-failed")' in failure_block


def test_release_transaction_permissions_metadata_and_cleanup_are_hardened():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "chmod 0700" in source
    assert "chmod 0600" in source
    assert '"mode"' in source
    assert "chmod" in source.split("def rollback_release", 1)[1].split("def fetch_json", 1)[0]
    assert "cleanup_release_transaction" in source
    assert "transaction retention" in source
    acquire = source.split("def acquire_release_lock", 1)[1].split("def release_release_lock", 1)[0]
    assert "trap" in acquire and "RELEASE_LOCK_DIR" in acquire


def test_watchdog_snapshot_and_restore_include_oneshot_service_state():
    source = SCRIPT.read_text(encoding="utf-8")
    capture = source.split("def capture_watchdog_state", 1)[1].split("def restore_watchdog_state", 1)[0]
    restore = source.split("def restore_watchdog_state", 1)[1].split("def remove_watchdog_units", 1)[0]
    assert "service_active" in capture
    assert "service_active" in restore
    assert "comfy-panel-watchdog.service" in restore


def test_release_transaction_persists_durable_phase_markers(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240: calls.append(text) or "")
    transaction = {"root": "/tx/current"}
    for phase in ("prepared", "swapping", "committed", "rollback-failed"):
        module.write_transaction_phase(object(), transaction, phase)
    joined = "\n".join(calls)
    for phase in ("prepared", "swapping", "committed", "rollback-failed"):
        assert phase in joined
    assert "os.fsync" in joined
    assert "os.replace" in joined
    assert "0o600" in joined


def test_prepared_phase_fsyncs_stage_backup_and_manifest_first():
    source = SCRIPT.read_text(encoding="utf-8")
    stage = source.split("def stage_file_resilient", 1)[1].split("def backup_release", 1)[0]
    backup = source.split("def backup_release", 1)[1].split("def rollback_release", 1)[0]
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert "fsync_remote_file" in stage
    assert "fsync_remote_file" in backup
    assert "os.fsync" in backup
    assert deploy.index("release_manifest = backup_release") < deploy.index(
        'write_transaction_phase(client, transaction, "prepared")')


def test_deploy_records_each_transaction_phase():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert 'write_transaction_phase(client, transaction, "prepared")' in deploy_body
    assert 'write_transaction_phase(client, transaction, "swapping")' in deploy_body
    assert 'write_transaction_phase(client, transaction, "committed")' in deploy_body
    assert 'write_transaction_phase(client, transaction, "rollback-failed")' in deploy_body


def test_release_requires_clean_git_tests_and_historical_e2e_records():
    module = load_module()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "E2E_MANIFEST" in text
    assert "validate_e2e_manifest" in text
    assert "require_clean_git" in text
    assert "run_release_tests" in text
    assert module.KNOWN_BASELINE_SCRIPT_FAILURES == {}
    manifest = json.loads((ROOT / "audit" / "private_realism_workflows" / "e2e_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["successful_workflows"]) == 7
    assert all(row["status"] == "SUCCESS" for row in manifest["successful_workflows"])


def test_retro_creator_has_a_verified_cloud_e2e_release_gate():
    module = load_module()
    assert module.RETRO_CLOUD_E2E_MANIFEST == RETRO_CLOUD_E2E
    assert module.validate_retro_cloud_e2e_manifest() == []
    record = json.loads(RETRO_CLOUD_E2E.read_text(encoding="utf-8"))
    actual = record["authoritative_remote_job_record"]
    assert record["verification"] == "PASS"
    assert record["rh_task_id"] == "2098333420378148866"
    assert record["rh_coins"] == "6"
    assert actual["client_request_id"] == "retro-cloud-w04-32421-final"
    assert actual["status"] == "done" and actual["provider_status"] == "DONE"
    assert actual["workflow"] == "anima02"
    assert actual["style_id"] == "retro_manga_luxury"
    assert actual["trigger"] == "jt_style321_v1"
    assert actual["loras"] == {
        "LORA1": "09_style321_v1_step200.safetensors",
        "LORA2": "09_style321_v1_step200.safetensors",
    }
    assert actual["lora_strengths"] == {"LORA1": 0.4, "LORA2": 0.0}
    assert (actual["width"], actual["height"], actual["batch"], actual["hd"], actual["seed"]) == (768, 1024, 1, 0, 32421)
    assert record["artifact"]["sha256"] == "a11974ba1341a36c76499b815a8f84611303493594805d03e9fc26d87156b2da"
    assert record["visual_review"]["functional_style_evidence"] == "PASS"
    assert record["visual_review"]["strict_promotional_visual"] == "FAIL"


def test_retro_cloud_e2e_tampering_blocks_release(tmp_path, monkeypatch):
    module = load_module()
    record = json.loads(RETRO_CLOUD_E2E.read_text(encoding="utf-8"))
    record["authoritative_remote_job_record"]["lora_strengths"]["LORA1"] = 0.6
    tampered = tmp_path / "retro.json"
    tampered.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(module, "RETRO_CLOUD_E2E_MANIFEST", tampered)
    errors = module.validate_retro_cloud_e2e_manifest()
    assert "retro cloud E2E LoRA mapping invalid" in errors
    decision = module.preflight_decision(
        complete_config(module),
        "class Handler:\n    def _auth(self):\n        return True\n",
        execute=True,
        allow_unauthenticated_public=True,
    )
    assert decision["ready"] is False
    assert "invalid retro creator cloud E2E" in decision["blockers"]
