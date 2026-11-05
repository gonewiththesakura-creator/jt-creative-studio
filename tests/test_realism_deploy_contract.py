import importlib.util
import hashlib
import json
import re
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


def test_native_release_requires_reviewed_evidence_bytes(tmp_path, monkeypatch):
    module = load_module()
    manifest = tmp_path / 'verification.json'
    monkeypatch.setattr(module, 'DREAMAPI_NATIVE_MANIFEST', manifest)
    assert 'absent' in module.validate_native_dreamapi_evidence()[0]
    manifest.write_text('{"verification":"PASS"}', encoding='utf8')
    assert module.validate_native_dreamapi_evidence() == ['native DreamAPI evidence is absent or not reviewed']
    monkeypatch.setattr(module, 'DREAMAPI_NATIVE_EVIDENCE_SHA256', hashlib.sha256(manifest.read_bytes()).hexdigest())
    errors = module.validate_native_dreamapi_evidence()
    assert 'native DreamAPI request contract invalid' in errors
    assert 'native DreamAPI runtime identity invalid' in errors
    assert 'native DreamAPI submission evidence invalid' in errors
    assert 'native DreamAPI artifact path invalid' in errors


def test_native_evidence_passes_for_the_reviewed_runtime(monkeypatch):
    # The reviewed runtime is a fixed historical commit, not this unreviewed
    # frontend rewrite. Preserve positive evidence coverage without bypassing
    # the production gate for the new shell.
    import subprocess
    from types import SimpleNamespace
    module = load_module()
    baseline = '403503028928f80195a5a3c7cfd3795bccc630a0'
    monkeypatch.setattr(module, 'DREAMAPI_NATIVE_MANIFEST', ROOT / 'audit/dreamapi_direct_final_20260918/verification.json')
    monkeypatch.setattr(module, 'DREAMAPI_NATIVE_EVIDENCE_SHA256', '72880ce8a757800862966df4ea334006596643699c57399cdf7db4842c15a760')
    def check_output(args, **kwargs):
        if args == ['git', 'rev-parse', 'HEAD']:
            return baseline + '\n'
        return subprocess.check_output(args, **kwargs)
    def run(args, **kwargs):
        if args[:4] == ['git', 'diff', '--quiet', 'HEAD']:
            return subprocess.CompletedProcess(args, 0)
        return subprocess.run(args, **kwargs)
    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(**{**vars(subprocess), 'check_output':check_output, 'run':run}))
    assert module.validate_native_dreamapi_evidence() == []


# Refreshed 2026-10-22 by the owner-authorized accretion canary (audit/accretion_canary_20261022).
def test_app_shell_has_reviewed_paid_evidence():
    assert load_module().validate_native_dreamapi_evidence() == []


def test_transparent_host_exception_rejects_unreviewed_digest():
    module = load_module()
    assert not module.reviewed_transparent_host_patch('tested', 'current', '0' * 64)


def test_video_queue_exception_rejects_unreviewed_digest(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', lambda *a, **k: '0'*64)
    assert not module.reviewed_video_queue_patch('41d2e7479bed751c457f7535f1994eae00ebae76', 'current')


@pytest.mark.parametrize('changed_payload', ['runtime', 'frontend'])
def test_video_redo_restore_exception_rejects_drift(monkeypatch, changed_payload):
    module = load_module()
    original = module.git_runtime_payload_sha256
    def digest(commit, **kwargs):
        is_runtime = kwargs.get('files') == module.NATIVE_RUNTIME_PAYLOAD_FILES
        if is_runtime == (changed_payload == 'runtime'):
            return '0' * 64
        return original(commit, **kwargs)
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', digest)
    assert not module.reviewed_video_redo_restore_patch(
        'ec0c01c8668a15337199d489bb01f2328302c6db',
        '15b512482aa25fe43d95d51743715b6427088e05')
    assert not module.reviewed_video_redo_restore_patch(
        'unreviewed-canary', '15b512482aa25fe43d95d51743715b6427088e05')


def test_transparent_host_exception_rejects_changed_css(monkeypatch):
    module = load_module()
    import subprocess
    from types import SimpleNamespace
    original = subprocess.check_output
    def altered(args, **kwargs):
        result = original(args, **kwargs)
        if args[:2] == ['git', 'show'] and args[2].startswith(head + ':') and args[2].endswith('.css'):
            result += b'body{display:none}'
        return result
    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(**{**vars(subprocess), 'check_output': altered}))
    record = json.loads(module.DREAMAPI_NATIVE_MANIFEST.read_text(encoding='utf8'))
    head = original(['git', 'rev-parse', 'HEAD'],cwd=ROOT,text=True).strip()
    assert not module.reviewed_transparent_host_patch(record['tested_release_commit'], head,
        '8d08ae62641ac0ee4e7a7612b6c36bce2f9c2871fc0a97ed6799405a9e43b3bb')


def test_app_shell_rejects_frontend_drift(monkeypatch):
    module = load_module()
    original = module.git_runtime_payload_sha256
    tested = json.loads(module.DREAMAPI_NATIVE_MANIFEST.read_bytes())['tested_release_commit']
    calls = []
    def digest(*args, **kwargs):
        if 'static/app.html' in kwargs.get('files', ()) and args[0] != tested:
            calls.append(True)
            if len(calls) > 1:
                return '0' * 64
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', digest)
    # Drift that is not visual-only stays rejected.
    monkeypatch.setattr(module, 'visual_only_frontend_change', lambda *args, **kwargs: False)
    assert 'native DreamAPI frontend payload drift' in module.validate_native_dreamapi_evidence()


def test_app_shell_drift_is_accepted_only_through_the_visual_only_rule(monkeypatch):
    module = load_module()
    original = module.git_runtime_payload_sha256
    tested = json.loads(module.DREAMAPI_NATIVE_MANIFEST.read_bytes())['tested_release_commit']
    calls, checked = [], []
    def digest(*args, **kwargs):
        if 'static/app.html' in kwargs.get('files', ()) and args[0] != tested:
            calls.append(True)
            if len(calls) > 1:
                return '0' * 64
        return original(*args, **kwargs)
    def visual(tested, current, show=None):
        checked.append((tested, current))
        return True
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', digest)
    monkeypatch.setattr(module, 'visual_only_frontend_change', visual)
    assert module.validate_native_dreamapi_evidence() == []
    assert len(checked) == 1 and checked[0][0] != checked[0][1]


def test_public_app_shell_verifies_all_lazy_assets(monkeypatch):
    module = load_module()
    paths = [p for p in module.RELEASE_RELATIVE_PATHS if p.startswith('static/assets/')
             or p in ('static/app.html', 'static/app-manifest.json')]
    payloads = {ROOT / p: (ROOT / p).read_bytes() for p in paths}
    seen = []
    def fetch(base, route, **kwargs):
        seen.append(route)
        path = 'static/app.html' if route in ('/', '/realism', '/video') else route.lstrip('/')
        return payloads[ROOT / path]
    monkeypatch.setattr(module, 'fetch_bytes_resilient', fetch)
    realism, shell, creator = module.verify_public_app_shell('http://example.test', payloads)
    # 4aa41f6: /realism is the queued image-edit page and submits through the shared scheduler.
    assert b'/api/image-edit-generate' in realism
    assert b'genApiBtn' in creator
    assert set(json.loads(payloads[ROOT / 'static/app-manifest.json'])['assets']) <= set(seen)
    monkeypatch.setattr(module, 'fetch_bytes_resilient', lambda *a, **k: b'wrong')
    with pytest.raises(RuntimeError, match='app shell mismatch'):
        module.verify_public_app_shell('http://example.test', payloads)


def test_singularity_exception_rejects_scene_asset_drift(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', lambda *args, **kwargs: '0' * 64)
    assert not module.reviewed_singularity_patch('tested', 'current', module.REVIEWED_SINGULARITY_RUNTIME_SHA256)
    assert not module.reviewed_singularity_patch('tested', 'current', '0' * 64)


def test_singularity_release_packages_local_scene_and_licence():
    module = load_module()
    required = {'static/singularity/workbench.js','static/singularity/theme.css',
                'static/singularity/shaders.js','static/singularity/vendor/LICENSE',
                'static/singularity/vendor/build/three.core.js',
                'static/singularity/vendor/build/three.module.js'}
    assert required <= set(module.RELEASE_RELATIVE_PATHS)


def test_native_evidence_rejects_runtime_drift(monkeypatch):
    module = load_module()
    original = module.git_runtime_payload_sha256
    calls = []
    def digest(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs) if len(calls) == 1 else '0' * 64
    monkeypatch.setattr(module, 'git_runtime_payload_sha256', digest)
    assert 'native DreamAPI runtime payload drift' in module.validate_native_dreamapi_evidence()


def test_error_presentation_exception_rejects_other_code_changes():
    module = load_module()
    before = 'def public_job_error(job):\n    return "old"\n\ndef submit():\n    return 1\n'
    after = before.replace('"old"', '"中文"')
    assert module.only_public_error_changed(before, after)
    assert not module.only_public_error_changed(before, after.replace('return 1', 'return 2'))
    assert not module.only_public_error_changed(before, after + '\nimport os\n')
    assert not module.only_public_error_changed(before, after.replace('def public_job_error', '@side_effect\ndef public_job_error'))


def test_admission_exception_cannot_change_generation_or_routes():
    module = load_module()
    before = 'BILLABLE_GLOBAL_HOURLY_LIMIT = 10\ndef billable_quota_status():\n    return True\ndef dreamapi_run_image():\n    return 1\nclass Handler:\n    def _billable_quota_rejection(self):\n        return True\n    def do_POST(self):\n        return 1\n'
    after = before.replace('BILLABLE_GLOBAL_HOURLY_LIMIT = 10\n','').replace('return True','return False')
    assert module.only_error_and_admission_changed(before, after)
    assert not module.only_error_and_admission_changed(before, after.replace('return 1','return 2',1))
    assert not module.only_error_and_admission_changed(before, after.replace('def do_POST(self):\n        return 1','def do_POST(self):\n        return 2'))
    assert not module.only_error_and_admission_changed(before, after.replace('def billable_quota_status', '@execute\ndef billable_quota_status'))


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
        # 547e6cc: H3 edit graph read by server.py at runtime.
        "video_wf/h3_edit_multi_api.json",
        "deploy/comfy-panel-watchdog.timer",
    }
    # server.py and every local module it imports, derived independently of the release tool.
    expected.update(local_import_closure("server.py"))
    style_data = ["static/" + path.name for path in (ROOT / "static").glob("style-configs.*.json")]
    assert len(style_data) == 1
    expected.update(style_data)
    expected.update({'static/app.html','static/app-manifest.json'})
    expected.update(path.lstrip('/') for path in json.loads((ROOT/'static/app-manifest.json').read_text(encoding='utf8'))['assets'])
    expected.update(path.relative_to(ROOT).as_posix()
                    for path in (ROOT / 'static/singularity').rglob('*') if path.is_file())
    assert set(module.RELEASE_RELATIVE_PATHS) == expected
    assert not any(path.startswith(("tests/", "audit/")) for path in module.RELEASE_RELATIVE_PATHS)


def local_import_closure(entry, root=ROOT):
    """Independent reference for the release tool: every root-level .py reachable from entry."""
    import ast
    found, pending = set(), [entry]
    while pending:
        relative = pending.pop()
        if relative in found:
            continue
        found.add(relative)
        for node in ast.walk(ast.parse((root / relative).read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            pending.extend(name.split(".")[0] + ".py" for name in names
                           if (root / (name.split(".")[0] + ".py")).is_file())
    return found


def test_release_manifest_ships_every_local_module_server_imports():
    # Previously a hand-written list that missed membership_* and result_image_cache, so a formal
    # release would have staged a server.py whose sibling modules were not updated.
    module = load_module()
    local = local_import_closure("server.py")
    assert {"membership_http.py", "membership_auth.py", "membership_store.py",
            "membership_media.py", "result_image_cache.py"} <= local
    assert set(module.SERVER_RUNTIME_MODULE_PATHS) == local
    assert local <= set(module.RELEASE_RELATIVE_PATHS), sorted(local - set(module.RELEASE_RELATIVE_PATHS))


def test_server_runtime_modules_follow_lazy_and_transitive_imports(tmp_path):
    module = load_module()
    (tmp_path / "server.py").write_text(
        "import json, first\nfrom second import thing\ndef late():\n    import lazy\n", encoding="utf-8")
    (tmp_path / "first.py").write_text("import nested.sub\n", encoding="utf-8")
    (tmp_path / "nested.py").write_text("", encoding="utf-8")
    (tmp_path / "second.py").write_text("import first\n", encoding="utf-8")
    (tmp_path / "lazy.py").write_text("", encoding="utf-8")
    (tmp_path / "unused.py").write_text("", encoding="utf-8")
    assert module.server_runtime_module_paths(tmp_path) == (
        "first.py", "lazy.py", "nested.py", "second.py", "server.py")

    (tmp_path / "lazy.py").write_text("from . import sibling\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="relative import"):
        module.server_runtime_module_paths(tmp_path)
    (tmp_path / "lazy.py").write_text("import pkg\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="local package"):
        module.server_runtime_module_paths(tmp_path)


def test_release_creates_every_remote_parent_directory():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "remote_parent_paths" in source
    assert "mkdir -p" in source
    assert "pathlib.PurePosixPath(remote).parent" in source


def test_staging_upload_reuses_one_sftp_and_verifies_each_file():
    source = SCRIPT.read_text(encoding="utf-8")
    stage = source.split("def stage_file_resilient", 1)[1].split("def backup_release", 1)[0]
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert "for attempt in range(1, 4)" in stage
    assert "client.open_sftp()" not in stage
    assert "staging mismatch" in stage
    assert deploy.count("client.open_sftp()") == 1
    assert "stage_file_resilient(client, sftp," in deploy
    assert deploy.index("sftp = client.open_sftp()") < deploy.index(
        "for local, remote in files.items():"
    )


def test_watchdog_units_are_installed_and_verified():
    source = SCRIPT.read_text(encoding="utf-8")
    service = (ROOT / "deploy" / "comfy-panel-watchdog.service").read_text(encoding="utf-8")
    assert "install_watchdog_units" in source
    assert "systemctl daemon-reload" in source
    assert "enable --now comfy-panel-watchdog.timer" in source
    assert "is-enabled comfy-panel-watchdog.timer" in source
    assert "is-active comfy-panel-watchdog.timer" in source
    assert "systemctl unmask --runtime comfy-panel-watchdog.service" in source
    assert "sudo systemctl start comfy-panel-watchdog.service" in source
    assert "watchdog service execution verification failed" in source
    assert "verify_installed_watchdog_contract(client)" in source
    verifier = source.split("def verify_installed_watchdog_contract", 1)[1].split(
        "def install_watchdog_units", 1
    )[0]
    assert "FragmentPath" in verifier and "DropInPaths" in verifier
    assert "watchdog effective ExecStart mismatch" in verifier
    assert "watchdog effective timer schedule mismatch" in verifier
    assert "TimersMonotonic" in verifier and "Persistent" in verifier
    assert "OnBootUSec=2min" in verifier
    assert "OnUnitActiveUSec=1min" in verifier
    assert "OnBootSec=2min" not in verifier
    assert "OnUnitActiveSec=1min" not in verifier
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
        "service_mode": 0o640,
        "timer_exists": False,
        "timer_b64": "",
        "timer_mode": None,
        "service_active": "inactive",
        "service_enabled": "disabled",
        "timer_enabled": "enabled",
        "timer_active": "active",
        "executable_exists": True,
        "executable_b64": base64.b64encode(b"#!/usr/bin/python3\n# old\n").decode(),
        "executable_mode": 0o755,
    }
    calls = []
    def fake_command(client, text, timeout=240):
        calls.append(text)
        return json.dumps(captured) if "print(json.dumps" in text else ""
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


def test_release_pins_the_ssh_host_key_for_public_key_authentication():
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "AutoAddPolicy" not in source
    assert "PinnedSHA256Policy" in source
    assert "hmac.compare_digest" in source
    assert "paramiko.Ed25519Key.from_private_key_file" in source
    assert "pkey=deploy_key" in source
    assert "password=" not in source
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


def app_shell_release_payloads(module):
    paths = [p for p in module.RELEASE_RELATIVE_PATHS if p.startswith('static/assets/')
             or p in ('static/app.html', 'static/app-manifest.json',
                      'static/previews/style-retro-manga-luxury.webp')]
    return {ROOT / p: (ROOT / p).read_bytes() for p in paths}


def serve_payloads(payloads, calls):
    def fetch(base, route, **kwargs):
        calls.append((route, kwargs))
        entry = route.split('?', 1)[0] in ('/', '/realism', '/video')
        return payloads[ROOT / ('static/app.html' if entry else route.lstrip('/'))]
    return fetch


def test_release_checks_the_creator_through_public_app_shell_assets_only():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args", 1)[0]
    assert "verify_public_app_shell_release(public_base, payloads)" in deploy_body
    # The login gate hides these since the membership cutover.
    for hidden in ('"/api/health"', '"/api/workflows"', "/static/previews/", "/static/style-configs"):
        assert hidden not in deploy_body
    assert not hasattr(load_module(), "verify_public_creator_config")


def test_public_app_shell_release_checks_creator_styles_through_hashed_assets(monkeypatch):
    module = load_module()
    payloads = app_shell_release_payloads(module)
    calls = []
    monkeypatch.setattr(module, 'fetch_bytes_resilient', serve_payloads(payloads, calls))
    realism, shell, creator = module.verify_public_app_shell_release('https://origin.test', payloads)
    assert shell == payloads[ROOT / 'static/app.html']
    assert b'/api/image-edit-generate' in realism and b'genApiBtn' in creator
    manifest = json.loads(payloads[ROOT / 'static/app-manifest.json'])
    routes = [route for route, _ in calls]
    assert set(manifest['assets']) <= set(routes)
    assert ('/?style=retro_manga_luxury', True) in {
        (route, kwargs.get('accept_gzip', False)) for route, kwargs in calls}
    # Every public response shares one absolute deadline.
    deadlines = {kwargs.get('deadline') for _, kwargs in calls}
    assert len(deadlines) == 1 and None not in deadlines
    assert not [route for route in routes
                if route.startswith(('/static/previews/', '/static/style-configs.', '/api/'))]


def test_public_app_shell_release_rejects_style_preview_and_route_drift(monkeypatch):
    module = load_module()
    payloads = app_shell_release_payloads(module)
    manifest = json.loads(payloads[ROOT / 'static/app-manifest.json'])
    creator_module = payloads[ROOT / manifest['pages']['/']['module'].lstrip('/')]
    routes = json.loads(re.search(rb'const STYLE_ASSETS=(\{[^;]*\});', creator_module).group(1))
    retro = ROOT / routes['retro_manga_luxury'].lstrip('/')
    preview = ROOT / 'static/previews/style-retro-manga-luxury.webp'

    def check(mutated, message, fetch=None):
        monkeypatch.setattr(module, 'fetch_bytes_resilient', fetch or serve_payloads(mutated, []))
        with pytest.raises(RuntimeError, match=message):
            module.verify_public_app_shell_release('https://origin.test', mutated)

    profile = json.loads(payloads[retro])
    check({**payloads, retro: json.dumps(dict(profile, trigger='other')).encode()},
          'style config mismatch: retro_manga_luxury')
    check({**payloads, preview: b'other'}, 'preview mismatch')
    check({key: value for key, value in payloads.items() if key != preview}, 'preview mismatch')
    served = serve_payloads(payloads, [])
    check(payloads, 'style route mismatch', fetch=lambda base, route, **kwargs:
          b'wrong' if route.startswith('/?') else served(base, route, **kwargs))
    check({key: value for key, value in payloads.items() if key != ROOT / 'static/app.html'},
          'missing the App Shell')


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
            return "inactive\ndisabled\ninactive\nmasked-runtime\n"
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    module.isolate_watchdog(object())
    assert "systemctl disable --runtime --now comfy-panel-watchdog.timer" in calls[0]
    assert "systemctl disable --now comfy-panel-watchdog.timer" in calls[0]
    assert "systemctl disable --runtime --now comfy-panel-watchdog.service" in calls[1]
    assert "systemctl stop comfy-panel-watchdog.service" in calls[1]
    assert "systemctl mask --runtime comfy-panel-watchdog.service" in calls[2]
    assert all("LoadState" in command and "not-found" in command for command in calls[:3])
    assert all("|| true" not in command for command in calls[:3])
    assert len(calls) == 5
    assert calls[3].startswith("sudo python3 -c")
    assert calls[4].startswith("python3 -c")


def test_watchdog_snapshot_rejects_custom_systemd_link_topology_before_mutation():
    source = SCRIPT.read_text(encoding="utf-8")
    capture = source.split("def capture_watchdog_state", 1)[1].split(
        "def validate_watchdog_state", 1
    )[0]
    assert "os.walk(root,followlinks=False)" in capture
    assert "related_links()" in capture
    assert "unsupported watchdog FragmentPath/DropInPaths" in capture
    assert "unsupported watchdog install topology" in capture
    assert "custom watchdog systemd link topology cannot be restored exactly" in capture
    assert "custom watchdog service enablement cannot be restored exactly" in capture


def test_watchdog_isolation_rejects_any_non_isolated_state(monkeypatch):
    module = load_module()
    for replies in (["active", "disabled", "inactive", "masked"],
                    ["inactive", "enabled", "inactive", "masked"],
                    ["inactive", "disabled", "active", "masked"],
                    ["inactive", "disabled", "inactive", "disabled"]):
        payload = "\n".join(replies) + "\n"
        monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                            payload if text.startswith("python3 -c") else "")
        with pytest.raises(RuntimeError, match="watchdog isolation failed"):
            module.isolate_watchdog(object())


def test_watchdog_restore_preserves_runtime_timer_mask(monkeypatch):
    module = load_module()
    state = {
        "service_exists": False, "service_b64": "", "service_mode": None,
        "timer_exists": False, "timer_b64": "", "timer_mode": None,
        "executable_exists": False, "executable_b64": "", "executable_mode": None,
        "service_active": "inactive", "service_enabled": "disabled",
        "timer_active": "inactive", "timer_enabled": "masked-runtime",
    }
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or (json.dumps(state) if "print(json.dumps" in text else ""))
    module.restore_watchdog_state(object(), state)
    assert any("mask --runtime comfy-panel-watchdog.timer" in text for text in calls)


def test_watchdog_state_probe_accepts_expected_nonzero_systemctl_status(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or "inactive\ndisabled\ninactive\nmasked\n")
    assert module.watchdog_isolation_state(object()) == ("inactive", "disabled", "inactive", "masked")
    assert len(calls) == 1
    assert "subprocess.run" in calls[0]


def test_watchdog_isolation_accepts_inactive_static_service_with_disabled_timer(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        "inactive\ndisabled\ninactive\nstatic\n" if text.startswith("python3 -c") else "")
    module.isolate_watchdog(object())


def test_pre_swap_watchdog_isolation_is_premarked_and_restored_by_deploy():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    mark = deploy.index("watchdog_isolated = True")
    isolate = deploy.index("isolate_watchdog(client)", mark)
    handler = deploy.index("except BaseException as preparation_error:", isolate)
    restore = deploy.index("restore_watchdog_state(client, watchdog_state)", handler)
    assert mark < isolate < handler < restore


def test_watchdog_snapshot_restores_service_mask_state(monkeypatch):
    module = load_module()
    import base64
    captured = {
        "service_exists": True, "service_b64": base64.b64encode(b"service").decode(), "service_mode": 0o644,
        "timer_exists": True, "timer_b64": base64.b64encode(b"timer").decode(), "timer_mode": 0o644,
        "executable_exists": True, "executable_b64": base64.b64encode(b"script").decode(), "executable_mode": 0o755,
        "service_active": "inactive", "service_enabled": "masked-runtime",
        "timer_active": "inactive", "timer_enabled": "masked",
    }
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or (json.dumps(captured) if "print(json.dumps" in text else ""))
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


def test_secondary_watchdog_isolation_is_inside_uncertain_rollback_guard():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    handler = deploy_body.split('print("PUBLIC_MARKERS_OK")', 1)[1].split("finally:", 1)[0]
    assert handler.index("try:") < handler.index("isolate_watchdog(client)")
    assert "rollback_uncertain = True" in handler
    assert 'write_transaction_phase(client, transaction, "rollback-failed")' in handler


def test_watchdog_restore_failure_keeps_release_lock_and_marks_rollback_failed():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    restore_tail = deploy_body.split("restore_watchdog_state(client, watchdog_state)", 1)[1]
    failure_block = restore_tail.split("raise\n            raise", 1)[0]
    assert "except BaseException:" in failure_block
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


def visual_fixture():
    """Two shell commits: business assets fixed, visual assets free to move."""
    def shell(css, scene):
        return (f'<link href="/static/assets/app.{css}.css"><script type="module" src="/static/assets/main.111111111111.js">'
                f'</script><script>window.manifest={{"singularity":"/static/assets/workbench.{scene}.js"}}</script>').encode()

    def manifest(css, scene, extra=()):
        return json.dumps({
            "main": "/static/assets/main.111111111111.js",
            "singularity": f"/static/assets/workbench.{scene}.js",
            "pages": {"/": {"module": "/static/assets/index.222222222222.js",
                            "markup": "/static/assets/index.333333333333.html",
                            "css": f"/static/assets/index.{css}.css", "title": "JT"}},
            "assets": ["/static/assets/main.111111111111.js", "/static/assets/index.222222222222.js",
                       "/static/assets/index.333333333333.html", f"/static/assets/index.{css}.css",
                       f"/static/assets/app.{css}.css", f"/static/assets/workbench.{scene}.js", *extra],
        }).encode()

    files = {
        "tested": {"static/app.html": shell("aaaaaaaaaaaa", "bbbbbbbbbbbb"),
                   "static/app-manifest.json": manifest("aaaaaaaaaaaa", "bbbbbbbbbbbb"),
                   "static/assets/main.111111111111.js": b"main()", "static/assets/index.222222222222.js": b"page()",
                   "static/assets/index.333333333333.html": b"<form></form>",
                   "static/assets/index.aaaaaaaaaaaa.css": b"a{}", "static/assets/app.aaaaaaaaaaaa.css": b"b{}",
                   "static/assets/workbench.bbbbbbbbbbbb.js": b"render()"},
    }
    current = dict(files["tested"])
    current.update({"static/app.html": shell("cccccccccccc", "dddddddddddd"),
                    "static/app-manifest.json": manifest("cccccccccccc", "dddddddddddd"),
                    "static/assets/index.cccccccccccc.css": b"a{color:red}",
                    "static/assets/app.cccccccccccc.css": b"b{text-wrap:balance}",
                    "static/assets/workbench.dddddddddddd.js": b"render();still()"})
    files["current"] = current
    return files, manifest


def visual_show(files):
    def show(commit, path):
        if path not in files[commit]:
            raise OSError(path)
        return files[commit][path]
    return show


SCENE = b"render();still()"
REVIEWED_SCENE = frozenset({hashlib.sha256(SCENE).hexdigest()})
BACKSLASH = bytes([92])


def test_visual_only_frontend_change_accepts_styles_and_a_reviewed_scene():
    module = load_module()
    files, _ = visual_fixture()
    show = visual_show(files)
    assert module.visual_only_frontend_change("tested", "current", show=show, reviewed_scripts=REVIEWED_SCENE)
    current = files["current"]
    current["static/assets/app.cccccccccccc.css"] = (
        b'b{background:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\'%3E%3C/svg%3E")}')
    assert module.visual_only_frontend_change("tested", "current", show=show, reviewed_scripts=REVIEWED_SCENE)
    files["tested"]["static/assets/app.aaaaaaaaaaaa.css"] = b"b{background:url(/static/assets/preview.111111111111.webp)}"
    current["static/assets/app.cccccccccccc.css"] = b"b{color:red;background:URL( '/static/assets/preview.111111111111.webp' )}"
    assert module.visual_only_frontend_change("tested", "current", show=show, reviewed_scripts=REVIEWED_SCENE)


@pytest.mark.parametrize("change", [
    "page-module", "main", "markup", "shell-text", "new-logic-asset", "missing-file",
    "unreviewed-scene", "edited-after-review", "same-path-overwrite",
    "style-api", "style-import", "style-external-spaced", "style-escape", "style-image-set", "style-src",
    "style-new-relative", "unreadable-tested-style",
    "style-comment-in-string", "style-url-in-string", "style-target-case", "style-image-function",
    "style-charset-shift",
])
def test_visual_only_frontend_change_rejects_business_drift_and_unproven_visuals(change):
    module = load_module()
    files, manifest = visual_fixture()
    current, reviewed = files["current"], REVIEWED_SCENE
    app_css, page_css = "static/assets/app.cccccccccccc.css", "static/assets/index.cccccccccccc.css"
    if change == "page-module":
        current["static/assets/index.222222222222.js"] = b"page();submit()"
    elif change == "main":
        current["static/assets/main.111111111111.js"] = b"main();other()"
    elif change == "markup":
        current["static/assets/index.333333333333.html"] = b"<form id=x></form>"
    elif change == "shell-text":
        current["static/app.html"] = current["static/app.html"].replace(b"<link", b"<link data-x")
    elif change == "new-logic-asset":
        current["static/app-manifest.json"] = manifest("cccccccccccc", "dddddddddddd",
                                                       ["/static/assets/helper.444444444444.js"])
        current["static/assets/helper.444444444444.js"] = b"helper()"
    elif change == "missing-file":
        del current["static/assets/index.222222222222.js"]
    elif change == "unreviewed-scene":
        reviewed = frozenset()
    elif change == "edited-after-review":
        current["static/assets/workbench.dddddddddddd.js"] = SCENE + b";document.forms[0].reset()"
    elif change == "same-path-overwrite":
        # The scene keeps its old hashed name but its bytes change.
        current["static/app-manifest.json"] = manifest("cccccccccccc", "bbbbbbbbbbbb")
        current["static/app.html"] = current["static/app.html"].replace(b"dddddddddddd", b"bbbbbbbbbbbb")
        current["static/assets/workbench.bbbbbbbbbbbb.js"] = b"render();tampered()"
    elif change == "style-api":
        current[app_css] = b"b{background:url(/api/jobs)}"
    elif change == "style-import":
        current[page_css] = b"@IMPORT 'theme.css';a{}"
    elif change == "style-external-spaced":
        current[app_css] = b"b{background:URL( https://example.test/x.png )}"
    elif change == "style-escape":
        current[app_css] = b"b{background:u" + BACKSLASH + b"72l(https://example.test/x.png)}"
    elif change == "style-image-set":
        current[app_css] = b"b{background:image-set('https://example.test/1.png' 1x)}"
    elif change == "style-src":
        current[app_css] = b"b{background:src('https://example.test/1.png')}"
    elif change == "style-new-relative":
        current[app_css] = b"b{background:url(/static/other.png)}"
    elif change == "unreadable-tested-style":
        files["tested"]["static/assets/app.aaaaaaaaaaaa.css"] = b"b{content:'" + BACKSLASH + b"201C'}"
    # Second Codex review (T261023-142143-2ae3): strings and comments are lexer states.
    elif change == "style-comment-in-string":
        current[app_css] = b'body{--a:"/*";background-image:url(https://example.test/new.png);--b:"*/"}'
    elif change == "style-url-in-string":
        current[app_css] = b"body{--a:'url(\"data:';background-image:url(https://example.test/new.png);--b:'\")'}"
    elif change == "style-target-case":
        files["tested"]["static/assets/app.aaaaaaaaaaaa.css"] = b"b{background:url(/static/a.png?v=a)}"
        current[app_css] = b"b{background:url(/static/a.png?v=A)}"
    elif change == "style-image-function":
        current[app_css] = b"b{background:image('https://example.test/a.png')}"
    # Third Codex review (T261023-142838-b6bf): ISO-2022-JP turns "@im ESC ( B port" into @import.
    elif change == "style-charset-shift":
        current[app_css] = b'@charset "iso-2022-jp";@im' + bytes([27]) + b'(Bport "/api/jobs";'  # ESC ( B returns to ASCII
    assert not module.visual_only_frontend_change("tested", "current", show=visual_show(files),
                                                  reviewed_scripts=reviewed)


def test_css_fetch_targets_reads_nested_data_uris_and_fails_closed():
    module = load_module()
    css = (b"/* url(http://commented.test) */a{background:url(\"data:image/svg+xml,%3Csvg%3E%3Cuse "
           b"href='url(%23g)'/%3E%3C/svg%3E\")}b{mask:url( /static/x.webp )}")
    assert module.css_fetch_targets(css) == [
        "data:image/svg+xml,%3Csvg%3E%3Cuse href='url(%23g)'/%3E%3C/svg%3E", "/static/x.webp"]
    # Strings and comments are lexer states: neither hides nor invents a url().
    assert module.css_fetch_targets(
        b'body{--a:"/*";background-image:url(https://example.test/new.png);--b:"*/"}') == [
        "https://example.test/new.png"]
    assert module.css_fetch_targets(
        b"body{--a:'url(\"data:';background-image:URL(https://example.test/new.png);--b:'\")'}") == [
        "https://example.test/new.png"]
    assert module.css_fetch_targets(b"a{background:url(/static/A.png?v=B)}b{x:myurl(y)}") == ["/static/A.png?v=B"]
    for unreadable in (b"a{background:url('x.png)}", b"a{background:url(x.png}", b"a{background:url(\"x\" y)}",
                       b"@import url(a.css);", b"@IMPORT 'a.css';", b"a{background:-webkit-image-set(url(a.png) 1x)}",
                       b"a{background:image('a.png')}", b"a{background:-webkit-cross-fade(url(a.png),url(b.png),50%)}",
                       b"a{content:'unterminated}", b"/* never closed",
                       b'@charset "utf-8";a{}', b"a{}" + bytes([27]) + b"(B", b"a{}" + bytes([0]),
                       bytes([0xFF, 0xFE]) + "a{}".encode("utf-16-le"),
                       b"a{content:'" + BACKSLASH + b"75rl'}"):
        assert module.css_fetch_targets(unreadable) is None, unreadable


def test_the_current_scene_script_is_a_reviewed_one():
    """Changing the scene needs a reviewed pin; hashed asset names are sha256 prefixes."""
    module = load_module()
    manifest = json.loads((ROOT / "static/app-manifest.json").read_text(encoding="utf-8"))
    scene = next(path for path in manifest["assets"] if "/workbench." in path)
    assert scene.split(".")[-2] in {digest[:12] for digest in module.REVIEWED_VISUAL_SCRIPTS_SHA256}


def test_visual_only_rule_never_classifies_business_assets_as_visual():
    module = load_module()
    manifest = json.loads((ROOT / "static/app-manifest.json").read_text(encoding="utf-8"))
    visual = {path.rsplit("/", 1)[1].split(".")[0] for path in manifest["assets"]
              if module.VISUAL_FRONTEND_ASSET.fullmatch(path)}
    business = {"main", "router", "api", "account", "account-storage", "page-scope", "membership-admin",
                "retired-upload-storage", "index", "realism", "video", "login-scene", "accretion-layout"}
    business_paths = [path for path in manifest["assets"]
                      if path.rsplit("/", 1)[1].split(".")[0] in business and not path.endswith(".css")]
    assert business_paths and not [path for path in business_paths if module.VISUAL_FRONTEND_ASSET.fullmatch(path)]
    assert not [path for path in manifest["assets"] if "/style-" in path and module.VISUAL_FRONTEND_ASSET.fullmatch(path)]
    assert {"workbench", "shaders", "appearance", "preview"} <= visual


def test_av1_upload_exception_rejects_other_commits_and_payloads():
    module = load_module()
    assert not module.reviewed_av1_upload_patch('tested', 'HEAD', module.REVIEWED_AV1_UPLOAD_RUNTIME_SHA256)
    assert not module.reviewed_av1_upload_patch(module.REVIEWED_AV1_UPLOAD_TESTED_COMMIT, 'HEAD', '0' * 64)
