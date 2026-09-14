import importlib.util
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

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
    assert MODULE.validate_dreamapi_migration_e2e_manifest() == []
    assert MODULE.DREAMAPI_E2E_MANIFEST.name == "dreamapi_creator_live_e2e.json"
    assert MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.name == "verification.json"


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
    assert "!audit/dreamapi_migration_20260914/*.png" in ignore


def test_dreamapi_runtime_payload_uses_framed_v1_git_bytes():
    assert MODULE.framed_v1_payload_sha256({"a": b"bc"}) == (
        "e7ab503819a08f424da9ba8421b745917f2f82f92b7e6a09ecce37d61289b827"
    )
    assert MODULE.framed_v1_payload_sha256({"a": b"bc"}) != (
        MODULE.framed_v1_payload_sha256({"ab": b"c"})
    )
    assert MODULE.git_runtime_payload_sha256(MODULE.DREAMAPI_TESTED_RELEASE_COMMIT) == (
        MODULE.DREAMAPI_RUNTIME_PAYLOAD_SHA256
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        MODULE.git_runtime_payload_sha256("0" * 40)


def test_dreamapi_runtime_payload_requires_ancestor_and_clean_workspace(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=repository, text=True, capture_output=True, check=True,
        ).stdout.strip()

    git("init", "--initial-branch=main")
    git("config", "user.email", "release-gate@example.invalid")
    git("config", "user.name", "Release Gate")
    for relative in MODULE.DREAMAPI_RUNTIME_PAYLOAD_FILES:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"runtime:{relative}\n", encoding="utf8")
    (repository / "base.txt").write_text("base\n", encoding="utf8")
    git("add", ".")
    git("commit", "-m", "base")
    git("switch", "-c", "tested")
    (repository / "tested.txt").write_text("tested\n", encoding="utf8")
    git("add", "tested.txt")
    git("commit", "-m", "tested")
    tested_commit = git("rev-parse", "HEAD")
    tested_digest = MODULE.git_runtime_payload_sha256(tested_commit, repository)
    git("switch", "main")
    (repository / "head.txt").write_text("head\n", encoding="utf8")
    git("add", "head.txt")
    git("commit", "-m", "head")

    monkeypatch.setattr(MODULE, "DREAMAPI_TESTED_RELEASE_COMMIT", tested_commit)
    monkeypatch.setattr(MODULE, "DREAMAPI_RUNTIME_PAYLOAD_SHA256", tested_digest)
    record = {
        "tested_release_commit": tested_commit,
        "runtime_payload": {
            "format": MODULE.DREAMAPI_RUNTIME_PAYLOAD_FORMAT,
            "files": list(MODULE.DREAMAPI_RUNTIME_PAYLOAD_FILES),
            "sha256": tested_digest,
        },
    }
    errors = MODULE.validate_dreamapi_runtime_payload(record, repository)
    assert "DreamAPI tested release commit is not an ancestor of HEAD" in errors

    (repository / "server.py").write_text("changed in workspace\n", encoding="utf8")
    errors = MODULE.validate_dreamapi_runtime_payload(record, repository)
    assert "DreamAPI runtime payload differs between HEAD and workspace" in errors

    git("switch", "tested")
    (repository / "server.py").write_text("changed after tested release\n", encoding="utf8")
    git("add", "server.py")
    git("commit", "-m", "runtime drift")
    errors = MODULE.validate_dreamapi_runtime_payload(record, repository)
    assert "DreamAPI runtime payload changed after tested release" in errors


def test_dreamapi_private_evidence_scan_is_recursive_and_allows_presence_flags():
    allowed = {
        "api_response_id_present": True,
        "repository_contains_key": False,
        "nested": [{"ordinary": "safe"}],
    }
    assert MODULE.find_dreamapi_private_evidence(allowed) == []
    assert MODULE.find_dreamapi_private_evidence({"API-Key": "redacted"})
    assert MODULE.find_dreamapi_private_evidence({"nested": [{"apiResponseId": "redacted"}]})
    assert MODULE.find_dreamapi_private_evidence({"nested": [{"APIResponseId": "redacted"}]})
    assert MODULE.find_dreamapi_private_evidence({"nested": "  Bearer redacted"})
    assert MODULE.find_dreamapi_private_evidence(["sk-redacted"])
    assert MODULE.find_dreamapi_private_evidence([{"value": "resp_redacted"}])


def test_dreamapi_png_helper_requires_meaningful_visible_variance(tmp_path):
    uniform = tmp_path / "uniform.png"
    Image.new("RGB", (4, 4), "white").save(uniform, format="PNG")
    uniform_raw = uniform.read_bytes()
    errors = MODULE.validate_png_artifact(
        uniform, len(uniform_raw), hashlib.sha256(uniform_raw).hexdigest(), (4, 4),
    )
    assert "PNG visible content variance too low" in errors

    one_pixel = tmp_path / "one-pixel.png"
    image = Image.new("RGB", (512, 512), "white")
    image.putpixel((0, 0), (0, 0, 0))
    image.save(one_pixel, format="PNG")
    one_pixel_raw = one_pixel.read_bytes()
    assert "PNG visible content variance too low" in MODULE.validate_png_artifact(
        one_pixel, len(one_pixel_raw), hashlib.sha256(one_pixel_raw).hexdigest(), (512, 512),
    )

    meaningful = tmp_path / "meaningful.png"
    image = Image.new("RGB", (16, 16), "white")
    for x in range(8):
        for y in range(16):
            image.putpixel((x, y), (0, 0, 0))
    image.save(meaningful, format="PNG")
    raw = meaningful.read_bytes()
    assert MODULE.validate_png_artifact(
        meaningful, len(raw), hashlib.sha256(raw).hexdigest(), (16, 16),
    ) == []
    assert "PNG format or dimensions invalid" in MODULE.validate_png_artifact(
        meaningful, len(raw), hashlib.sha256(raw).hexdigest(), (17, 16),
    )

    transparent = tmp_path / "transparent.png"
    hidden = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    hidden.putpixel((0, 0), (255, 0, 0, 0))
    hidden.save(transparent, format="PNG")
    transparent_raw = transparent.read_bytes()
    assert "PNG visible content variance too low" in MODULE.validate_png_artifact(
        transparent, len(transparent_raw), hashlib.sha256(transparent_raw).hexdigest(), (4, 4),
    )

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(raw[:-8])
    corrupt_raw = corrupt.read_bytes()
    assert "PNG decode invalid" in MODULE.validate_png_artifact(
        corrupt, len(corrupt_raw), hashlib.sha256(corrupt_raw).hexdigest(), (16, 16),
    )


def test_dreamapi_png_helper_rejects_before_decode_when_metadata_mismatches(tmp_path, monkeypatch):
    artifact = tmp_path / "untrusted.png"
    artifact.write_bytes(b"not an image")

    def unexpected_open(*args, **kwargs):
        raise AssertionError("Pillow must not inspect bytes with a mismatched digest")

    monkeypatch.setattr(MODULE.Image, "open", unexpected_open)
    assert MODULE.validate_png_artifact(artifact, 999, "0" * 64, (1, 1)) == [
        "artifact bytes invalid"
    ]

    class HeaderOnly:
        format = "PNG"
        size = (1, 1)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def verify(self):
            raise AssertionError("dimension mismatch must return before PNG verification")

    monkeypatch.setattr(MODULE.Image, "open", lambda *args, **kwargs: HeaderOnly())
    raw = artifact.read_bytes()
    assert MODULE.validate_png_artifact(
        artifact, len(raw), hashlib.sha256(raw).hexdigest(), (2, 2),
    ) == ["PNG format or dimensions invalid"]


def test_dreamapi_release_identity_evidence_is_exact_and_fail_closed(tmp_path, monkeypatch):
    original = json.loads(MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.read_text(encoding="utf8"))
    assert original["release_identity_evidence"] == MODULE.DREAMAPI_RELEASE_IDENTITY_EVIDENCE
    mutations = (
        lambda row: row.update({"method": "job metadata"}),
        lambda row: row.update({"attestation_scope": "provider-signed"}),
        lambda row: row.update({"transaction_id": "wrong-transaction"}),
        lambda row: row.update({"phase": "prepared"}),
        lambda row: row.update({"phase_mtime": "2026-09-14T20:16:44+08:00"}),
        lambda row: row.update({"completed_mtime": "2026-09-14T20:16:43+08:00"}),
        lambda row: row["server_service"].update({"invocation_id": "0" * 32}),
        lambda row: row["server_service"].update({"active_since": "2026-09-14T20:16:20+08:00"}),
        lambda row: row["server_service"].update({"restart_count": 1}),
        lambda row: row["remote_sha256"].update({"server.py": "0" * 64}),
        lambda row: row["remote_sha256"].update({"unexpected.py": "0" * 64}),
        lambda row: row["workstation_watchdog"].update({"process_id": 1}),
        lambda row: row["workstation_watchdog"].update({"active_since": "2026-09-14T18:17:06+08:00"}),
        lambda row: row["workstation_watchdog"].update({"file_sha256": "0" * 64}),
        lambda row: row["workstation_watchdog"].update({"launcher_sha256": "0" * 64}),
        lambda row: row["workstation_watchdog"].update({"dreamapi_contract_sha256": "0" * 64}),
        lambda row: row["workstation_watchdog"].update({"dreamapi_uncertainty_fence": True}),
        lambda row: row.update({"first_job_created_at": "2026-09-14T20:19:52.301+08:00"}),
        lambda row: row.update({"last_job_created_at": "2026-09-14T20:19:52.301+08:00"}),
    )
    monkeypatch.setattr(MODULE, "validate_png_artifact", lambda *args, **kwargs: [])
    for index, mutate in enumerate(mutations):
        changed = json.loads(json.dumps(original))
        mutate(changed["release_identity_evidence"])
        manifest = tmp_path / f"release-identity-{index}.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        monkeypatch.setattr(MODULE, "DREAMAPI_MIGRATION_E2E_MANIFEST", manifest)
        errors = MODULE.validate_dreamapi_migration_e2e_manifest()
        assert "DreamAPI release identity evidence invalid" in errors, index
    assert "DreamAPI release identity job timeline invalid" in errors


def test_dreamapi_migration_e2e_gate_fails_closed_on_contract_job_or_artifact_drift(tmp_path, monkeypatch):
    original = json.loads(MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.read_text(encoding="utf8"))
    source_dir = MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.parent
    mutations = (
        lambda row: row.update({"evidence_scope": "per-model production request-contract matrix"}),
        lambda row: row.update({"unified_release_e2e": False}),
        lambda row: row.update({"tested_release_commit": "0" * 40}),
        lambda row: row["runtime_payload"].update({"format": "raw-concatenation"}),
        lambda row: row["runtime_payload"].update({"files": list(reversed(row["runtime_payload"]["files"]))}),
        lambda row: row["runtime_payload"].update({"sha256": "0" * 64}),
        lambda row: row["request_contract"].update({"text_model": "gpt-5.6-sol"}),
        lambda row: row["request_contract"].update({"client_pixel_dimensions_present": True}),
        lambda row: row["request_contract"].update({"provider_size_mapped_from_ratio": False}),
        lambda row: row["request_contract"]["action_by_model"].update({"gpt-image-2": "generate"}),
        lambda row: row["request_contract"]["instruction_profile_by_model"].update({"gpt-image-2": "strict"}),
        lambda row: row["production_jobs"]["gpt-image-2.5-sunburst"].update({"status": "error"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"api_model": "gpt-image-2.5-flare"}),
        lambda row: row["production_jobs"]["gpt-image-2.5-flare"].update({"api_dispatch_profile": "strict"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"api_action_mode": "generate"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"dreamapi_contract_sha256": "0" * 64}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"contract_commit": "f7c1798"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"client_request_id": "wrong-request"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"created_at": "2026-09-14T20:19:18+08:00"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"history_occurrences": 2}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"requested_ratio": "1024x1024"}),
        lambda row: row["production_jobs"]["gpt-image-2.5-flare"]["artifact"].update({"sha256": "0" * 64}),
        lambda row: row["contrastive_failures"]["sunburst_with_standard_instruction"].update({"instruction_profile": "strict"}),
        lambda row: row["contrastive_failures"].update({"interpretation": "proves deterministic causality"}),
        lambda row: row.update({"authorization": "redacted"}),
        lambda row: row["production_jobs"]["gpt-image-2"].update({"metadata": {"secret": "redacted"}}),
        lambda row: row["production_jobs"]["gpt-image-2"]["visual_review"].update({"note": "Bearer redacted"}),
    )
    for index, mutate in enumerate(mutations):
        case = tmp_path / str(index)
        case.mkdir()
        changed = json.loads(json.dumps(original))
        mutate(changed)
        manifest = case / "verification.json"
        manifest.write_text(json.dumps(changed), encoding="utf8")
        for job in original["production_jobs"].values():
            name = job["artifact"]["file"]
            (case / name).write_bytes((source_dir / name).read_bytes())
        monkeypatch.setattr(MODULE, "DREAMAPI_MIGRATION_E2E_MANIFEST", manifest)
        assert MODULE.validate_dreamapi_migration_e2e_manifest(), index

    corrupt = tmp_path / "corrupt-artifact"
    corrupt.mkdir()
    manifest = corrupt / "verification.json"
    manifest.write_text(json.dumps(original), encoding="utf8")
    for job in original["production_jobs"].values():
        name = job["artifact"]["file"]
        raw = (source_dir / name).read_bytes()
        (corrupt / name).write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    monkeypatch.setattr(MODULE, "DREAMAPI_MIGRATION_E2E_MANIFEST", manifest)
    assert any(
        "artifact bytes invalid" in error
        for error in MODULE.validate_dreamapi_migration_e2e_manifest()
    )


def test_dreamapi_migration_e2e_rejects_duplicate_job_and_client_ids(tmp_path, monkeypatch):
    original = json.loads(MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.read_text(encoding="utf8"))
    source_dir = MODULE.DREAMAPI_MIGRATION_E2E_MANIFEST.parent
    cases = []
    duplicate_job = json.loads(json.dumps(original))
    duplicate_job["production_jobs"]["gpt-image-2"]["job_id"] = (
        duplicate_job["contrastive_failures"]["image_2_with_strict_instruction"]["job_id"]
    )
    cases.append((duplicate_job, "DreamAPI migration job IDs are not unique"))
    duplicate_client = json.loads(json.dumps(original))
    duplicate_client["production_jobs"]["gpt-image-2"]["client_request_id"] = (
        duplicate_client["production_jobs"]["gpt-image-2.5-flare"]["client_request_id"]
    )
    cases.append((duplicate_client, "DreamAPI migration client request IDs are not unique"))

    for index, (record, expected_error) in enumerate(cases):
        case = tmp_path / str(index)
        case.mkdir()
        manifest = case / "verification.json"
        manifest.write_text(json.dumps(record), encoding="utf8")
        for job in original["production_jobs"].values():
            name = job["artifact"]["file"]
            (case / name).write_bytes((source_dir / name).read_bytes())
        monkeypatch.setattr(MODULE, "DREAMAPI_MIGRATION_E2E_MANIFEST", manifest)
        assert expected_error in MODULE.validate_dreamapi_migration_e2e_manifest()


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
