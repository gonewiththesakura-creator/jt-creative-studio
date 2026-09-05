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


def complete_workflow(name, workflow_id):
    return {
        "id": "target-" + workflow_id[-4:],
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
            complete_workflow(name, str(2100000000000000000 + index))
            for index, name in enumerate(module.TARGET_WORKFLOW_NAMES, 1)
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
    }
    assert set(module.RELEASE_RELATIVE_PATHS) == expected
    assert not any(path.startswith(("tests/", "audit/")) for path in module.RELEASE_RELATIVE_PATHS)


def test_current_config_fails_before_credentials_or_ssh_are_needed():
    module = load_module()
    current = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    result = module.validate_release_config(current)
    assert result["ready"] is False
    assert sorted(result["missing_targets"]) == sorted(module.TARGET_WORKFLOW_NAMES)
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
