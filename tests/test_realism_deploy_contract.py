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
        "systemctl restart comfy-panel",
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


def test_release_rollback_uses_manifest_retry_and_post_restore_verification():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "BACKUP_MANIFEST" in text
    assert 'stat.st_size == 0' not in text
    assert "wait_for_health" in text
    assert "rollback verification mismatch" in text
    assert "rollback health failed" in text


def test_release_requires_clean_git_tests_and_seven_successful_e2e_records():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "E2E_MANIFEST" in text
    assert "validate_e2e_manifest" in text
    assert "require_clean_git" in text
    assert "run_release_tests" in text
    assert "test_restore_prompt_contract.py" in text
    manifest = json.loads((ROOT / "audit" / "private_realism_workflows" / "e2e_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["successful_workflows"]) == 7
    assert all(row["status"] == "SUCCESS" for row in manifest["successful_workflows"])
