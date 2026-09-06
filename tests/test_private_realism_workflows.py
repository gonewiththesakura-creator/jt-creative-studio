import hashlib
import json
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
ATTACHMENTS = Path(r"C:/Users/JT/AppData/Local/hermes/attachments")
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
BY_ID = {item["id"]: item for item in CONFIG["workflows"]}

SOURCES = {
    "realism_krea2": {
        "run_id": "2096139245572726785", "editor_id": None,
        "editor": "Krea2_动漫转真人.json", "api": "Krea2_动漫转真人_api.json",
    },
    "realism_2511": {
        "run_id": "2096138870382723074", "editor_id": None,
        "editor": "动漫转写实真人2511（零偏移_高还原）工作流.json", "api": "动漫转写实真人2511（零偏移_高还原）工作流_api.json",
    },
    "realism_multisample": {
        "run_id": "2096103615374155777", "editor_id": None,
        "editor": "动漫转真人-多采超清天花板.json", "api": "动漫转真人-多采超清天花板_api.json",
    },
    "realism_qwen_zi": {
        "run_id": "2096101840168747010", "editor_id": None,
        "editor": "Qwen+ZI动漫转真人写实感洗图.json", "api": "Qwen+ZI动漫转真人写实感洗图_api.json",
    },
    "realism_4k_text": {
        "run_id": "2095331229284470786", "editor_id": None,
        "editor": "超写实4K文生图.json", "api": "超写实4K文生图_api.json",
    },
    "realism_3in1": {
        "run_id": "2096094953332416513", "editor_id": None,
        "editor": "3in1.json", "api": "3in1_api.json",
    },
    "realism_zi_flowmatch": {
        "run_id": "2096150319347859458", "editor_id": None,
        "editor": "动漫转真人ZI洗图改（Z-image+FlowMatch）.json", "api": "动漫转真人ZI洗图改（Z-image+FlowMatch）_api.json",
    },
}

LOCKED_CLASS_TYPES = {
    "UNETLoader", "CheckpointLoaderSimple", "CLIPLoader", "VAELoader",
    "LoraLoaderModelOnly", "Lora Loader Stack (rgthree)", "easy loraStack",
    "SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "easy sam3ModelLoader",
    "UltralyticsDetectorProvider", "SAMLoader", "llama_cpp_model_loader",
}
LOCKED_OUTPUT_TYPES = {
    "SaveImage", "CompressImages", "easy showAnything", "ShowText|pysssss",
    "ImageAndMaskPreview",
}
LOCKED_OUTPUT_FIELDS = {"filename_prefix", "text", "mask_opacity", "mask_color", "pass_through"}
LOCKED_PAIRS = {("SeedVR2", "model"), ("easy imageColorMatch", "save_prefix")}
LOCKED_FIELD_NAMES = {"model", "device", "device_mode", "offload_device"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def api_literals(api):
    """The exact mechanical policy used for the complete 3in1 contract."""
    rows = set()
    media = set()
    for node_id, node in api.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if class_type in LOCKED_CLASS_TYPES:
            continue
        for field, value in (node.get("inputs") or {}).items():
            linked = isinstance(value, list) and len(value) == 2 and str(value[0]) in api
            if linked:
                continue
            if class_type == "LoadImage" and field == "image":
                media.add((str(node_id), field))
                continue
            if not isinstance(value, (str, int, float, bool)):
                continue
            if class_type in LOCKED_OUTPUT_TYPES and field in LOCKED_OUTPUT_FIELDS:
                continue
            if (class_type, field) in LOCKED_PAIRS:
                continue
            if field in LOCKED_FIELD_NAMES:
                continue
            rows.add((str(node_id), field))
    return media, rows


def test_all_seven_run_ids_are_unique_and_match_fingerprint_audit():
    fingerprint = json.loads((ROOT / "audit" / "private_realism_workflows" / "run_id_fingerprints.json").read_text(encoding="utf-8"))
    configured = {BY_ID[internal_id]["rh_workflow_id"]: internal_id for internal_id in SOURCES}
    assert len(configured) == 7
    assert configured == fingerprint["mapping"]
    assert fingerprint["all_probes_unbilled"] is True
    assert all(next(iter(score.values())) == "5/5" for score in fingerprint["scores"].values())


def test_all_seven_private_workflows_have_exact_ids_and_source_hashes():
    assert set(SOURCES).issubset(BY_ID)
    for internal_id, source in SOURCES.items():
        item = BY_ID[internal_id]
        assert item["backend"] == "runninghub"
        assert item["kind"] == "rh_workflow"
        assert item["rh_workflow_id"] == source["run_id"]
        assert item["source_editor_workflow_id"] == source["editor_id"]
        assert item["rh_schema_complete"] is True
        assert item["source_editor_json_sha256"] == sha(ATTACHMENTS / source["editor"])
        assert item["source_api_json_sha256"] == sha(ATTACHMENTS / source["api"])


def test_multisample_uses_trusted_plus_instance_after_verified_default_vram_oom():
    assert BY_ID["realism_multisample"]["rh_instance_type"] == "plus"
    for internal_id in SOURCES:
        if internal_id != "realism_multisample":
            assert BY_ID[internal_id].get("rh_instance_type", "default") == "default"


def test_3in1_complete_executable_literal_control_contract():
    source = SOURCES["realism_3in1"]
    api = json.loads((ATTACHMENTS / source["api"]).read_text(encoding="utf-8-sig"))
    expected_media, expected_params = api_literals(api)
    item = BY_ID["realism_3in1"]
    actual_media = {(str(row["node"]), row["field"]) for row in item["rh_media"].values()}
    actual_params = {(str(row["node"]), row["field"]) for row in item["rh_params"].values()}
    assert len(expected_media) == 3
    assert len(expected_params) == 105
    assert actual_media == expected_media
    assert actual_params == expected_params


def test_3in1_sensitive_native_prompt_is_preserved_and_clearly_labeled():
    item = BY_ID["realism_3in1"]
    mapping = next(row for row in item["rh_params"].values() if row["node"] == "1399" and row["field"] == "prompt")
    assert mapping["default"]
    assert "成人向" in mapping["label"]
    assert mapping["group"] == "advanced"


def test_3in1_labels_expose_node_and_field_identity_without_provider_id():
    item = BY_ID["realism_3in1"]
    for mapping in list(item["rh_media"].values()) + list(item["rh_params"].values()):
        assert f"节点{mapping['node']}" in mapping["label"]
        assert mapping["field"] in mapping["hint"]
        assert mapping.get("node_type")


def test_all_exported_defaults_normalize_without_semantic_rewriting():
    import importlib.util
    spec = importlib.util.spec_from_file_location("private_realism_server", ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for internal_id in SOURCES:
        item = BY_ID[internal_id]
        media = {key: "api/input.png" for key in item["rh_media"]}
        trusted_media, trusted_params = module.normalize_rh_workflow_inputs(item, media, {})
        assert trusted_media == media
        assert set(trusted_params) == set(item["rh_params"])
        for key, mapping in item["rh_params"].items():
            if isinstance(mapping.get("default"), str) and not mapping["default"].strip():
                assert trusted_params[key] == mapping["default"]


def test_provider_implementation_paths_are_never_browser_controls():
    forbidden_fields = {"unet_name", "clip_name", "vae_name", "lora_name", "ckpt_name", "model_name", "model", "device", "device_mode", "offload_device"}
    for internal_id in SOURCES:
        item = BY_ID[internal_id]
        assert not forbidden_fields.intersection(row["field"] for row in item["rh_params"].values())
        assert all(row.get("type") == "image" for row in item["rh_media"].values())
