import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "deploy_realism_release.py"
SPEC = importlib.util.spec_from_file_location("uploaded_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf8"))

EXPECTED = {
    "h3_edit_n": "2098330246185926657",
    "h3_edit_t3": "2098330116945457154",
    "h3_edit_remove": "2097937340852727809",
    "qwen_image_edit_zip": "2097924547454918658",
    "wan_action_stabilized": "2097924526817800193",
    "scail2_action_replace": "2097870206308147201",
}
EXPECTED_PROVENANCE = {
    "h3_edit_n": ("2098341535964643329", "431c5283f8bcc3b93755d2c63126d25e3a8d8b6fc2711b529e6408c49e9d76bf", "6c8f2e61c77bd7145c6ccc0a18b6094632bccfa64900ccdf5afd0ba8ded4904f"),
    "h3_edit_t3": ("2098341701604966401", "6534bf97ef07c8d5e3b9571d5819b4a69ca4bb18a934b4095760e729b8f87fd4", "472e4bc3fb879c6b9d9e75ce59c8d92da9c7f6b2af5968461826b814fd0df4a6"),
    "h3_edit_remove": ("2098341695082573826", "d42c537e400d8f4881e57175b44b4fd830ebafeb43492863f7ea9eb0c6eb6805", "876da66c7a6e908145283852d2326b5214dc08710a64cd5bf7032b8ca80a8cbd"),
    "qwen_image_edit_zip": ("2098345504735592450", "4ff0394f19a2de6dd466a99ee1b2b5632695ba33f0621e185ce52d3b34fe1b1b", "5f01ca2bb0c981fcc55c02ac906901270be3a8ed0ce136575347bef8fcaef1d6"),
    "wan_action_stabilized": ("2098345513989357570", "a717d3b361b83729b3f706c9520061131c4be8dd96c315f5cd01e7b3670eb211", "b0475b22baf36f058514b49a335147667640ab45b55d92ca9d754a98e403344a"),
    "scail2_action_replace": ("2098345531529936898", "94d25510ae5d5380e235421d1fa6e8c79ef5d2b1e0a71c4a3b5d045be29bea71", "7fab1a5c29aabdc31e0a23a9ece6e227938906c1f030c54b8f02d009d0352c07"),
}


def test_atomic_release_gates_all_six_uploaded_workflows():
    assert MODULE.UPLOADED_WORKFLOW_TARGETS == EXPECTED
    assert MODULE.UPLOADED_WORKFLOW_PROVENANCE == EXPECTED_PROVENANCE
    assert MODULE.validate_uploaded_workflow_config(CONFIG) == []


def test_uploaded_release_gate_fails_closed_on_identity_or_schema_drift():
    for workflow_id in EXPECTED:
        broken = json.loads(json.dumps(CONFIG))
        item = next(x for x in broken["workflows"] if x["id"] == workflow_id)
        item["rh_workflow_id"] = "2099999999999999999"
        assert MODULE.validate_uploaded_workflow_config(broken)
        item["rh_workflow_id"] = EXPECTED[workflow_id]
        item["rh_schema_complete"] = False
        assert MODULE.validate_uploaded_workflow_config(broken)

        item["rh_schema_complete"] = True
        item["source_api_json_sha256"] = "0" * 64
        assert MODULE.validate_uploaded_workflow_config(broken)


def test_uploaded_workflow_release_gate_pins_complete_control_metadata():
    mutations = (
        ("h3_edit_t3", "rh_media", "source_video", "required", False),
        ("h3_edit_t3", "rh_params", "duration", "type", "text"),
        ("h3_edit_t3", "rh_params", "duration", "default", 9),
        ("h3_edit_t3", "rh_params", "duration", "max", 999),
        ("h3_edit_t3", "rh_params", "long_edge", "step", 1),
        ("scail2_action_replace", "rh_media", "reference_image_2", "fallback_to", None),
    )
    for workflow_id, scope, key, field, value in mutations:
        broken = json.loads(json.dumps(CONFIG))
        item = next(row for row in broken["workflows"] if row["id"] == workflow_id)
        if value is None:
            item[scope][key].pop(field, None)
        else:
            item[scope][key][field] = value
        assert MODULE.validate_uploaded_workflow_config(broken), (workflow_id, scope, key, field)

    broken = json.loads(json.dumps(CONFIG))
    item = next(row for row in broken["workflows"] if row["id"] == "h3_edit_remove")
    item["fixed_features"] = []
    assert any(
        "control metadata drift" in error
        for error in MODULE.validate_uploaded_workflow_config(broken)
    )


def test_uploaded_workflow_release_gate_pins_result_roles_and_order():
    tampered = json.loads(json.dumps(CONFIG))
    by_id = {item["id"]: item for item in tampered["workflows"]}
    by_id["h3_edit_t3"]["rh_result_labels"] = ["原片 / 生成片对比", "编辑后主视频"]
    assert any("result labels" in error for error in MODULE.validate_uploaded_workflow_config(tampered))

    tampered = json.loads(json.dumps(CONFIG))
    by_id = {item["id"]: item for item in tampered["workflows"]}
    by_id["h3_edit_n"]["rh_result_labels"] = ["猜测标签"]
    assert any("result labels" in error for error in MODULE.validate_uploaded_workflow_config(tampered))


def test_public_release_verification_requires_six_names_and_api_creator_markers():
    source = SCRIPT.read_text(encoding="utf8")
    assert "UPLOADED_WORKFLOW_NAMES" in source
    for marker in ("genApiBtn", "gpt-image-2.5-flare", "API结果"):
        assert marker in source


def test_unauthenticated_release_requires_bounded_billable_quota_controls():
    source = (ROOT / "server.py").read_text(encoding="utf8")
    assert MODULE.validate_public_billable_quota(source) == []
    assert MODULE.validate_public_upload_quota(source) == []
    for changed in (
        source.replace("BILLABLE_GLOBAL_HOURLY_LIMIT = 10", "BILLABLE_GLOBAL_HOURLY_LIMIT = 1000"),
        source.replace("BILLABLE_GLOBAL_DAILY_LIMIT = 30", "BILLABLE_GLOBAL_DAILY_LIMIT = 3000"),
        source.replace("BILLABLE_SESSION_HOURLY_LIMIT = 4", "BILLABLE_SESSION_HOURLY_LIMIT = 400"),
        source.replace("register_billable_job(job, session_id)", "register_unbounded_job(job)", 1),
    ):
        assert MODULE.validate_public_billable_quota(changed)
    for changed in (
        source.replace("UPLOAD_SESSION_HOURLY_LIMIT = 20", "UPLOAD_SESSION_HOURLY_LIMIT = 2000"),
        source.replace("UPLOAD_GLOBAL_HOURLY_BYTES = 2 * 1024 * 1024 * 1024", "UPLOAD_GLOBAL_HOURLY_BYTES = 20 * 1024 * 1024 * 1024"),
        source.replace("reserve_upload_attempt(session_id, len(raw))", "allow_unbounded_upload()", 1),
    ):
        assert MODULE.validate_public_upload_quota(changed)


def test_dreamapi_live_e2e_evidence_is_verified_before_release():
    assert MODULE.validate_dreamapi_e2e_manifest() == []
    assert MODULE.validate_dreamapi_sidebar_e2e_manifest() == []
    assert MODULE.DREAMAPI_E2E_MANIFEST.name == "dreamapi_creator_live_e2e.json"


def test_dreamapi_e2e_gate_fails_closed_on_endpoint_models_credentials_or_timestamp_drift(tmp_path, monkeypatch):
    original = json.loads(MODULE.DREAMAPI_E2E_MANIFEST.read_text(encoding="utf8"))
    artifact = MODULE.DREAMAPI_E2E_MANIFEST.parent / original["artifact"]["file"]
    for mutate in (
        lambda row: row["endpoint_contract"].update({"path": "/v1/responses"}),
        lambda row: row["model_discovery"].update({"gpt_image_2_5_flare": False}),
        lambda row: row["credential_handling"].update({"repository_contains_key": True}),
        lambda row: row.update({"verified_at": "not-a-timestamp"}),
    ):
        changed = json.loads(json.dumps(original))
        mutate(changed)
        manifest = tmp_path / "dreamapi_creator_live_e2e.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        (tmp_path / artifact.name).write_bytes(artifact.read_bytes())
        monkeypatch.setattr(MODULE, "DREAMAPI_E2E_MANIFEST", manifest)
        assert MODULE.validate_dreamapi_e2e_manifest()


def test_dreamapi_e2e_png_is_explicitly_trackable():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf8")
    assert "!audit/dreamapi_creator_live_20260912.png" in ignore


def test_uploaded_workflow_live_schema_evidence_is_fail_closed():
    assert MODULE.validate_uploaded_workflow_live_schema_manifest(CONFIG) == []
    record = json.loads(MODULE.UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST.read_text(encoding="utf8"))
    assert record["verification"] == "PASS"
    assert len(record["records"]) == 6
    assert sum(len(row["allowed_structural_differences"]) for row in record["records"]) == 3
    assert all(row["verified"] and row["all_mappings_present"] for row in record["records"])
    assert all(not row["unexpected_structural_differences"] for row in record["records"])


def test_all_six_uploaded_workflows_have_layered_live_e2e_evidence():
    assert MODULE.validate_uploaded_workflow_e2e_manifest(CONFIG) == []
    record = json.loads(MODULE.UPLOADED_WORKFLOW_E2E_MANIFEST.read_text(encoding="utf8"))
    assert set(record["workflows"]) == set(EXPECTED)
    assert all(row["submit_attempts"] == 1 and row["status"] == "done"
               for row in record["workflows"].values())
    serialized = json.dumps(record, ensure_ascii=False)
    for forbidden in ("upl_", "http://", "https://", "C:\\\\", "provider_media"):
        assert forbidden not in serialized
    assert record["workflows"]["h3_edit_remove"]["strict_visual"] == "WARNING"
    assert record["workflows"]["scail2_action_replace"]["strict_visual"] == "WARNING"


def test_uploaded_workflow_e2e_tampering_blocks_release(tmp_path, monkeypatch):
    original = json.loads(MODULE.UPLOADED_WORKFLOW_E2E_MANIFEST.read_text(encoding="utf8"))
    mutations = (
        lambda row: row["workflows"]["h3_edit_n"].update({"run_workflow_id": "2099999999999999999"}),
        lambda row: row["workflows"]["qwen_image_edit_zip"].update({"submit_attempts": 2}),
        lambda row: row["workflows"]["wan_action_stabilized"].update({"rh_coins": "0"}),
        lambda row: row["workflows"]["h3_edit_t3"]["artifacts"][0].update({"sha256": "0" * 64}),
        lambda row: row["workflows"]["h3_edit_remove"].pop("visual_warning"),
        lambda row: row["workflows"]["qwen_image_edit_zip"].update({
            "security_wrapper_scope": "opaque_upload_capability_verified",
        }),
    )
    for index, mutate in enumerate(mutations):
        changed = json.loads(json.dumps(original))
        mutate(changed)
        manifest = tmp_path / f"uploaded-e2e-{index}.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        monkeypatch.setattr(MODULE, "UPLOADED_WORKFLOW_E2E_MANIFEST", manifest)
        assert MODULE.validate_uploaded_workflow_e2e_manifest(CONFIG), index


def test_uploaded_workflow_live_schema_tampering_blocks_release(tmp_path, monkeypatch):
    source = json.loads(MODULE.UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST.read_text(encoding="utf8"))
    for mutate in (
        lambda row: row["records"][0].update({"live_canonical_sha256": "0" * 64}),
        lambda row: row["records"][0].update({"all_mappings_present": False}),
        lambda row: row["records"][0]["unexpected_structural_differences"].append({"node": "1"}),
        lambda row: row.update({"endpoint": "https://example.invalid"}),
    ):
        changed = json.loads(json.dumps(source))
        mutate(changed)
        manifest = tmp_path / "live-schema.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        monkeypatch.setattr(MODULE, "UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST", manifest)
        assert MODULE.validate_uploaded_workflow_live_schema_manifest()


def test_uploaded_live_schema_gate_rejects_internal_contradictions(tmp_path, monkeypatch):
    source = json.loads(MODULE.UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST.read_text(encoding="utf8"))
    mutations = (
        lambda row: row.update({"method": "paid submit"}),
        lambda row: row["records"][0].update({"http_status": 500}),
        lambda row: row["records"][0].update({"provider_code": 99}),
        lambda row: row["records"][0].update({"structural_difference_count": 99}),
        lambda row: row["records"][0].update({"structural_differences": []}),
        lambda row: row["records"][0].update({"scalar_difference_count": 1}),
        lambda row: row["records"][1].update({"canonical_equal": False}),
        lambda row: row["records"][1].update({"structural_equal": False}),
    )
    for index, mutate in enumerate(mutations):
        changed = json.loads(json.dumps(source))
        mutate(changed)
        manifest = tmp_path / f"live-schema-{index}.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        monkeypatch.setattr(MODULE, "UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST", manifest)
        assert MODULE.validate_uploaded_workflow_live_schema_manifest(CONFIG), index
