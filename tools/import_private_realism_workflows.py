"""Import the seven private RunningHub realism workflows from trusted exports.

The source files remain in the Hermes attachment store. This importer verifies
all source hashes, pairs editor/API graphs by name, derives browser controls
from API literals plus live RunningHub object_info, and atomically updates
config.json. Provider model paths and output paths are deliberately locked.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
ATTACHMENTS = pathlib.Path(r"C:/Users/JT/AppData/Local/hermes/attachments")
OBJECT_INFO = pathlib.Path(r"C:/Users/JT/AppData/Local/Temp/rh_object_info_selected.json")

SOURCES = (
    {
        "id": "realism_krea2", "name": "Krea2_动漫转真人",
        "desc": "Krea2编辑模型将动漫图转换为写实真人，并支持SeedVR2高清放大。",
        "run_id": "2096139245572726785", "editor_id": None,
        "editor": "Krea2_动漫转真人.json", "api": "Krea2_动漫转真人_api.json",
        "editor_sha": "e4cc7f7e2075522f4f7c80402ce8c6d89eb102935a67f97fd547fd7758d66d97",
        "api_sha": "9e86d8d3ad4e1d9b33ac838dc6643158922c5572872de16f6b162b6d412f3375",
    },
    {
        "id": "realism_2511", "name": "动漫转写实真人2511（零偏移·高还原）",
        "desc": "Qwen Image Edit 2511动漫转写实，强调构图、表情、服装与光影一致性。",
        "run_id": "2096138870382723074", "editor_id": None,
        "editor": "动漫转写实真人2511（零偏移_高还原）工作流.json", "api": "动漫转写实真人2511（零偏移_高还原）工作流_api.json",
        "editor_sha": "f6b91601eeb2cdffb91649a4f7a4c36882b90d9e5227b47f66827f67d2f65d90",
        "api_sha": "d9a1ff2f1bcb01ccfb11afef1f8e71b354ec98ece251977745300b487633b7b5",
    },
    {
        "id": "realism_multisample", "name": "动漫转真人·多采超清天花板",
        "desc": "Boogu多采样动漫转真人，含提示词反推、Z-Image美化与SeedVR超清放大。",
        "run_id": "2096103615374155777", "editor_id": None,
        "editor": "动漫转真人-多采超清天花板.json", "api": "动漫转真人-多采超清天花板_api.json",
        "editor_sha": "26b3957c2a1764ea9fe3b269eee7bf0d8d5fbd71155d9e3b1a11ac49fa4d8d59",
        "api_sha": "f96328890b403e6d03ab6bc7c8cc071912b2200555459762d9ff4208e96f1cad",
    },
    {
        "id": "realism_qwen_zi", "name": "Qwen+ZI动漫转真人写实感洗图",
        "desc": "Qwen Image Edit转真人后使用Z-Image增强质感，并支持高清放大。",
        "run_id": "2096101840168747010", "editor_id": None,
        "editor": "Qwen+ZI动漫转真人写实感洗图.json", "api": "Qwen+ZI动漫转真人写实感洗图_api.json",
        "editor_sha": "d231eae675cc1a8e99138213258a9bd4bbfa9020f1183fab6d09a7c45656e51c",
        "api_sha": "a933b4f22a867474f0f18c55e952946269b94ef95864a55a26793d6dc541210a",
    },
    {
        "id": "realism_4k_text", "name": "超写实4K文生图",
        "desc": "超写实文生图，支持Krea2/Z-Image链路、分辨率预设和SeedVR2放大。",
        "run_id": "2095331229284470786", "editor_id": None,
        "editor": "超写实4K文生图.json", "api": "超写实4K文生图_api.json",
        "editor_sha": "13d2c2469e9a8db8f7ec79c594c09d489e2694307fd10ab94ef8fd1104ba33d0",
        "api_sha": "ccbba3d7e067a5b82ed22436cb6033b4238e1fdbb6b14e79f4b4e1c064a6615a",
    },
    {
        "id": "realism_3in1", "name": "动漫转真人·多分支超清3in1",
        "desc": "完整多分支图：Flux2 Klein转真人、Z-Image质感、面部修复、局部处理与SeedVR2放大。",
        "run_id": "2096094953332416513", "editor_id": None,
        "editor": "3in1.json", "api": "3in1_api.json",
        "editor_sha": "43c5681ea9ac4d9f3cceeaf5e5583ee4acf3dba67459797c9af357c11c32549c",
        "api_sha": "d0dc8eabb62b939a9bf64c33f16d2a6bf5db6ee665649cf8718ac4efda6d2e10",
    },
    {
        "id": "realism_zi_flowmatch", "name": "动漫转真人ZI洗图改（Z-Image+FlowMatch）",
        "desc": "动漫转真人、提示词反推与Z-Image FlowMatch质感增强组合。",
        "run_id": "2096150319347859458", "editor_id": None,
        "editor": "动漫转真人ZI洗图改（Z-image+FlowMatch）.json", "api": "动漫转真人ZI洗图改（Z-image+FlowMatch）_api.json",
        "editor_sha": "257b5776bea4f6b12d762a3428f7cee649008d5447dfb5094969905d7d8417a3",
        "api_sha": "81efaa4789cc6b53e4bf8b3445b7deeb73051ad0b7cb4cbb5cf7357d6d495db3",
    },
)

LOCKED_CLASSES = {
    "UNETLoader", "CheckpointLoaderSimple", "CLIPLoader", "VAELoader",
    "LoraLoaderModelOnly", "Lora Loader Stack (rgthree)", "easy loraStack",
    "SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "easy sam3ModelLoader",
    "UltralyticsDetectorProvider", "SAMLoader", "llama_cpp_model_loader",
}
OUTPUT_CLASSES = {"SaveImage", "CompressImages", "easy showAnything", "ShowText|pysssss", "ImageAndMaskPreview"}
OUTPUT_FIELDS = {"filename_prefix", "text", "mask_opacity", "mask_color", "pass_through"}
LOCKED_PAIRS = {("SeedVR2", "model"), ("easy imageColorMatch", "save_prefix")}
LOCKED_FIELD_NAMES = {"model", "device", "device_mode", "offload_device"}
LABELS = {
    "image": "输入图片", "prompt": "提示词", "text": "文本", "seed": "随机种子",
    "noise_seed": "噪声种子", "steps": "采样步数", "cfg": "CFG强度",
    "sampler_name": "采样器", "scheduler": "调度器", "denoise": "重绘强度",
    "scale_to_length": "目标边长", "new_resolution": "放大分辨率",
    "batch_size": "批量大小", "threshold": "阈值", "keep_model_loaded": "保持模型加载",
    "use_custom_size": "使用自定义尺寸", "custom_width": "自定义宽度",
    "custom_height": "自定义高度", "preset_size": "分辨率预设",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source(source):
    editor_path, api_path = ATTACHMENTS / source["editor"], ATTACHMENTS / source["api"]
    if digest(editor_path) != source["editor_sha"] or digest(api_path) != source["api_sha"]:
        raise RuntimeError(f"source hash mismatch: {source['id']}")
    return (json.loads(editor_path.read_text(encoding="utf-8-sig")),
            json.loads(api_path.read_text(encoding="utf-8-sig")))


def node_titles(editor):
    return {str(node.get("id")): str(node.get("title") or node.get("type") or "")
            for node in editor.get("nodes", []) if isinstance(node, dict)}


def input_spec(object_info, class_type, field):
    node = object_info.get(class_type) or {}
    inputs = (node.get("input") or {})
    for required in ("required", "optional"):
        spec = (inputs.get(required) or {}).get(field)
        if spec is not None:
            return required == "required", spec
    return False, None


def control_type(value, spec):
    head = spec[0] if isinstance(spec, list) and spec else None
    meta = spec[1] if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) else {}
    options = head if isinstance(head, list) else meta.get("options")
    if options:
        return "select", options, meta
    kind = str(head or "").upper()
    if kind == "BOOLEAN" or isinstance(value, bool): return "boolean", None, meta
    if kind == "INT" or isinstance(value, int): return "int", None, meta
    if kind == "FLOAT" or isinstance(value, float): return "float", None, meta
    return ("textarea" if meta.get("multiline") or isinstance(value, str) and len(value) > 120 else "text"), None, meta


def group_for(class_type, field, value):
    if class_type == "LoadImage" or field in {"prompt", "text"}: return "common"
    if field in {"use_custom_size", "custom_width", "custom_height", "preset_size", "new_resolution"}: return "common"
    return "advanced"


def build_workflow(source, object_info):
    editor, api = load_source(source)
    titles = node_titles(editor)
    media, params = {}, {}
    for node_id, node in api.items():
        if not isinstance(node, dict): continue
        class_type = str(node.get("class_type") or "")
        if class_type in LOCKED_CLASSES: continue
        title = str((node.get("_meta") or {}).get("title") or titles.get(str(node_id)) or class_type)
        for field, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in api: continue
            if class_type == "LoadImage" and field == "image":
                key = f"n{node_id}_{field}"
                label = f"节点{node_id} · {title or LABELS['image']}"
                media[key] = {"node": str(node_id), "field": field, "type": "image",
                              "label": label, "required": True, "group": "common",
                              "node_type": class_type,
                              "hint": f"{class_type} · fieldName: {field}"}
                continue
            if not isinstance(value, (str, int, float, bool)): continue
            if class_type in OUTPUT_CLASSES and field in OUTPUT_FIELDS: continue
            if (class_type, field) in LOCKED_PAIRS: continue
            if field in LOCKED_FIELD_NAMES: continue
            required, spec = input_spec(object_info, class_type, field)
            kind, options, meta = control_type(value, spec)
            key = f"n{node_id}_{field}"
            base_label = LABELS.get(field) or f"{title} · {field}"
            group = group_for(class_type, field, value)
            if source["id"] == "realism_3in1" and str(node_id) == "1399" and field == "prompt":
                base_label = "成人向原生提示词"
                group = "advanced"
            label = f"节点{node_id} · {base_label}"
            row = {"node": str(node_id), "field": field, "type": kind, "label": label,
                   "default": value, "required": bool(required), "group": group,
                   "node_type": class_type}
            if isinstance(value, str) and not value.strip():
                row["allow_blank"] = True
            if options is not None: row["options"] = options
            for name in ("min", "max", "step"):
                if name in meta: row[name] = meta[name]
            existing_hint = str(meta.get("tooltip") or "").strip()
            identity_hint = f"{class_type} · fieldName: {field}"
            row["hint"] = f"{identity_hint} · {existing_hint}" if existing_hint else identity_hint
            params[key] = row
    result = {
        "id": source["id"], "name": source["name"], "desc": source["desc"],
        "kind": "rh_workflow", "backend": "runninghub", "rh_workflow_id": source["run_id"],
        "source_editor_workflow_id": source["editor_id"], "source_editor_json_sha256": source["editor_sha"],
        "source_api_json_sha256": source["api_sha"], "rh_schema_complete": True,
        "rh_media": media, "rh_params": params, "params_defaults": {},
        "speed": "RunningHub云端，耗时按工作流和当前队列而定",
        "ref": "按页面字段上传图片；文生图工作流无需图片",
    }
    if source["id"] == "realism_multisample":
        result["rh_instance_type"] = "plus"
    return result


def main():
    object_info = json.loads(OBJECT_INFO.read_text(encoding="utf-8"))
    config_path = BASE / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    generated = [build_workflow(source, object_info) for source in SOURCES]
    ids = {source["id"] for source in SOURCES}
    config["workflows"] = [item for item in config["workflows"] if item.get("id") not in ids] + generated
    tmp = config_path.with_suffix(".json.new")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(config_path)
    print(json.dumps({item["id"]: {"media": len(item["rh_media"]), "params": len(item["rh_params"])} for item in generated}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
