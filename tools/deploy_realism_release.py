"""Fail-closed atomic release for the realism workbench.

Default invocation is a local preflight only. Remote mutation requires both:
  --execute
  --allow-unauthenticated-public  (only while server._auth intentionally allows all)

The preflight refuses release until all four private RunningHub copies have
trusted provider ids and mechanically completed schemas sourced from exported
API JSON.
"""
from __future__ import annotations

import argparse
import ast
import base64
import datetime
import gzip
import hashlib
import hmac
import json
import pathlib
import re
import shlex
import subprocess
import sys
import time
import urllib.request
import uuid

BASE = pathlib.Path(__file__).resolve().parents[1]
E2E_MANIFEST = BASE / "audit" / "private_realism_workflows" / "e2e_manifest.json"
SCAIL_E2E_MANIFEST = BASE / "audit" / "scail2_video_e2e.json"
RETRO_CLOUD_E2E_MANIFEST = BASE / "audit" / "retro_manga_panel_e2e_cloud_w04.json"
DREAMAPI_E2E_MANIFEST = BASE / "audit" / "dreamapi_creator_live_e2e.json"
UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST = BASE / "audit" / "uploaded_workflows_live_schema_20260912.json"
UPLOADED_WORKFLOW_E2E_MANIFEST = BASE / "audit" / "uploaded_workflows_live_e2e_20260912.json"
REMOTE_ROOT = "/home/admin/comfy-panel"
PUBLIC_BASE = "http://8.210.125.65:8189"
RELEASE_LOCK_DIR = REMOTE_ROOT + "/.release.lock"
RELEASE_TRANSACTIONS_DIR = REMOTE_ROOT + "/.release-transactions"
WATCHDOG_SERVICE_UNIT = "/etc/systemd/system/comfy-panel-watchdog.service"
WATCHDOG_TIMER_UNIT = "/etc/systemd/system/comfy-panel-watchdog.timer"
WATCHDOG_EXECUTABLE = "/usr/local/libexec/comfy-panel-watchdog.py"
SSH_HOST_KEY_SHA256 = "SHA256:TBBAqO1joLOjtttAHJaGdmYYolwwvpkDJaFXGqKEgWA"
PUBLIC_LARGE_VERIFY_TIMEOUT = 15 * 60
KNOWN_BASELINE_SCRIPT_FAILURES = {}

TARGET_WORKFLOWS = {
    "realism_krea2": "Krea2_动漫转真人",
    "realism_2511": "动漫转写实真人2511（零偏移·高还原）",
    "realism_multisample": "动漫转真人·多采超清天花板",
    "realism_qwen_zi": "Qwen+ZI动漫转真人写实感洗图",
    "realism_4k_text": "超写实4K文生图",
    "realism_zi_flowmatch": "动漫转真人ZI洗图改（Z-Image+FlowMatch）",
}
TARGET_WORKFLOW_IDS = tuple(TARGET_WORKFLOWS)
TARGET_WORKFLOW_NAMES = tuple(TARGET_WORKFLOWS.values())
SCAIL_VIDEO_TARGETS = {
    "scail2_plus": "2096841102812053505",
    "scail2_multi": "2096840691372924929",
}
SCAIL_VIDEO_FIELDS = {
    "scail2_plus": ({"reference_image", "driving_video"}, {"prompt", "width", "height", "frame_rate", "frame_load_cap", "skip_first_frames", "seed", "vae_tiling", "long_video_low_memory"}),
    "scail2_multi": ({"reference_image", "driving_video"}, {"prompt", "mask_prompt", "long_edge", "frame_rate", "frame_load_cap", "skip_first_frames", "people", "seed", "mode", "preserve_reference_background", "vae_tiling"}),
}
UPLOADED_WORKFLOW_TARGETS = {
    "h3_edit_n": "2098330246185926657",
    "h3_edit_t3": "2098330116945457154",
    "h3_edit_remove": "2097937340852727809",
    "qwen_image_edit_zip": "2097924547454918658",
    "wan_action_stabilized": "2097924526817800193",
    "scail2_action_replace": "2097870206308147201",
}
UPLOADED_WORKFLOW_NAMES = {
    "h3_edit_n": "MiniMax H3 · 双参考视频编辑",
    "h3_edit_t3": "MiniMax H3 · 通用视频编辑 T3",
    "h3_edit_remove": "MiniMax H3 · 移除人物/物品/元素",
    "qwen_image_edit_zip": "全能修改图生图",
    "wan_action_stabilized": "动作迁移 · 抖动优化",
    "scail2_action_replace": "SCAIL2 · 动作迁移/角色替换",
}
UPLOADED_WORKFLOW_PROVENANCE = {
    "h3_edit_n": ("2098341535964643329", "431c5283f8bcc3b93755d2c63126d25e3a8d8b6fc2711b529e6408c49e9d76bf", "6c8f2e61c77bd7145c6ccc0a18b6094632bccfa64900ccdf5afd0ba8ded4904f"),
    "h3_edit_t3": ("2098341701604966401", "6534bf97ef07c8d5e3b9571d5819b4a69ca4bb18a934b4095760e729b8f87fd4", "472e4bc3fb879c6b9d9e75ce59c8d92da9c7f6b2af5968461826b814fd0df4a6"),
    "h3_edit_remove": ("2098341695082573826", "d42c537e400d8f4881e57175b44b4fd830ebafeb43492863f7ea9eb0c6eb6805", "876da66c7a6e908145283852d2326b5214dc08710a64cd5bf7032b8ca80a8cbd"),
    "qwen_image_edit_zip": ("2098345504735592450", "4ff0394f19a2de6dd466a99ee1b2b5632695ba33f0621e185ce52d3b34fe1b1b", "5f01ca2bb0c981fcc55c02ac906901270be3a8ed0ce136575347bef8fcaef1d6"),
    "wan_action_stabilized": ("2098345513989357570", "a717d3b361b83729b3f706c9520061131c4be8dd96c315f5cd01e7b3670eb211", "b0475b22baf36f058514b49a335147667640ab45b55d92ca9d754a98e403344a"),
    "scail2_action_replace": ("2098345531529936898", "94d25510ae5d5380e235421d1fa6e8c79ef5d2b1e0a71c4a3b5d045be29bea71", "7fab1a5c29aabdc31e0a23a9ece6e227938906c1f030c54b8f02d009d0352c07"),
}
UPLOADED_WORKFLOW_FIELDS = {
    "h3_edit_n": ({"reference_image", "source_video"}, {"prompt", "duration", "short_edge", "seed"}, "video"),
    "h3_edit_t3": ({"source_video"}, {"prompt", "duration", "long_edge", "seed"}, "video"),
    "h3_edit_remove": ({"source_video"}, {"prompt", "duration", "long_edge", "seed"}, "video"),
    "qwen_image_edit_zip": ({"source_image"}, {"prompt", "batch", "seed"}, "rh_workflow"),
    "wan_action_stabilized": ({"reference_image", "driving_video"}, {"prompt", "duration", "width", "height", "jitter", "seed"}, "video"),
    "scail2_action_replace": ({"reference_image", "reference_image_2", "reference_image_3", "reference_image_4", "driving_video"}, {"prompt", "replace_target", "replacement_mode", "duration", "long_edge", "people", "seed"}, "video"),
}

UPLOADED_WORKFLOW_RESULT_LABELS = {
    "h3_edit_n": None,
    "h3_edit_t3": ["编辑后主视频", "原片 / 生成片对比"],
    "h3_edit_remove": ["移除后主视频", "原片 / 生成片对比"],
    "qwen_image_edit_zip": None,
    "wan_action_stabilized": None,
    "scail2_action_replace": ["动作迁移主视频", "输入 / 参考 / 结果对比"],
}

UPLOADED_WORKFLOW_CONTROL_SCHEMA_SHA256 = {
    "h3_edit_n": "7334c0d1e2d0de0de97e8255ddb6d8419085c92ea16ee67e94d4aaa9137628e3",
    "h3_edit_t3": "005fd5c8e7cf5638a74cb4d8ed38a78e00438522cbe6a14e25a8a3129a8be8f0",
    "h3_edit_remove": "32733e5d4fd9d7ec435bb6b393f5729e804988d8cfffade7040853b49ccb932d",
    "qwen_image_edit_zip": "5adf6399af4a2e6e652600420c69c2914ab8f950802d883b570c77ed3f435151",
    "wan_action_stabilized": "01b790493b32a6759b2506c6a79e3f7ada0831ea30c1518eb6f17d358951b40d",
    "scail2_action_replace": "2d8e78b3e7ad8f53085edc62d2e3f2012de31174224bf72fbbcf240112527bbe",
}

UPLOADED_WORKFLOW_LIVE_SCHEMA = {
    "h3_edit_n": (33, "7c6c55419b15ebe36208748bbc6ef328448278de1e3830a5fabdd58f7249db71"),
    "h3_edit_t3": (34, "74179658ef12711f2a93dbf8b0cb357a19340132b67ed279020d92c320c606cb"),
    "h3_edit_remove": (34, "95808692e31e26225f220f5dfee7a32ef801c5e211118499b2bd14a825654049"),
    "qwen_image_edit_zip": (18, "49c268aba011930630a3b44c0832be77190eea42c5e3e1afc96df9683080f96f"),
    "wan_action_stabilized": (40, "52952dbde16d7885e06d233e39180a66b2e3fe79dcb6a6d91b692fb66126bf85"),
    "scail2_action_replace": (61, "7ed58e2745fb22e5222ece2036a5ccc0c7ac517d85aef610d4bf4144930597f9"),
}
UPLOADED_WORKFLOW_ALLOWED_LIVE_DIFFERENCES = {
    "h3_edit_n": {("228", "video-preview", "field_missing_in_attachment")},
    "h3_edit_t3": set(),
    "h3_edit_remove": set(),
    "qwen_image_edit_zip": set(),
    "wan_action_stabilized": set(),
    "scail2_action_replace": {
        ("492", "Update inputs", "field_missing_in_live"),
        ("494", "Update inputs", "field_missing_in_live"),
    },
}

RELEASE_RELATIVE_PATHS = (
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
)


def _target_by_id(config):
    workflows = config.get("workflows") if isinstance(config, dict) else None
    if not isinstance(workflows, list):
        return {}
    return {
        str(item.get("id") or ""): item
        for item in workflows
        if isinstance(item, dict)
    }


def _invalid_reasons(item):
    reasons = []
    provider_id = str(item.get("rh_workflow_id") or "")
    if not re.fullmatch(r"\d{16,24}", provider_id):
        reasons.append("provider id")
    if item.get("kind") != "rh_workflow" or item.get("backend") != "runninghub":
        reasons.append("workflow type")
    if item.get("rh_schema_complete") is not True:
        reasons.append("schema")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(item.get("source_api_json_sha256") or "")):
        reasons.append("source hash")
    if item.get("id") != "realism_4k_text" and (not isinstance(item.get("rh_media"), dict) or not item.get("rh_media")):
        reasons.append("media")
    if not isinstance(item.get("rh_params"), dict) or not item.get("rh_params"):
        reasons.append("params")
    return reasons


def validate_release_config(config):
    """Mechanically gate the four target workflows before any remote access."""
    by_id = _target_by_id(config)
    missing = [workflow_id for workflow_id in TARGET_WORKFLOW_IDS if workflow_id not in by_id]
    invalid = []
    for workflow_id, expected_name in TARGET_WORKFLOWS.items():
        if workflow_id not in by_id:
            continue
        item = by_id[workflow_id]
        reasons = _invalid_reasons(item)
        if item.get("name") != expected_name:
            reasons.append("name")
        if reasons:
            invalid.append({"id": workflow_id, "name": expected_name, "reasons": reasons})
    return {
        "ready": not missing and not invalid,
        "missing_targets": missing,
        "invalid_targets": invalid,
    }


def validate_scail_video_config(config):
    by_id = _target_by_id(config)
    errors = []
    forbidden_keys = {"multi_image", "pose_detection", "skeleton_action", "background_image", "black_background", "model", "lora", "steps", "cfg", "scheduler", "device", "blocks_to_swap"}
    forbidden_fields = {"model", "model_name", "lora", "lora_0", "steps", "cfg", "scheduler", "render_device", "blocks_to_swap", "device", "load_device"}
    for internal_id, workflow_id in SCAIL_VIDEO_TARGETS.items():
        item = by_id.get(internal_id)
        if not item:
            errors.append(f"missing SCAIL workflow: {internal_id}")
            continue
        expected_media, expected_params = SCAIL_VIDEO_FIELDS[internal_id]
        media = item.get("rh_media") or {}; params = item.get("rh_params") or {}
        if item.get("kind") != "video" or item.get("backend") != "runninghub" or item.get("rh_workflow_id") != workflow_id or item.get("rh_schema_complete") is not True:
            errors.append(f"invalid SCAIL identity: {internal_id}")
        if set(media) != expected_media or set(params) != expected_params or not all(row.get("required") for row in media.values()):
            errors.append(f"invalid SCAIL public schema: {internal_id}")
        direct_fields = {row.get("field") for row in params.values() if row.get("field")}
        if forbidden_keys.intersection(media) or forbidden_keys.intersection(params) or forbidden_fields.intersection(direct_fields):
            errors.append(f"unsafe SCAIL controls: {internal_id}")
        for key in ("source_editor_json_sha256", "source_api_json_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get(key) or "")):
                errors.append(f"missing SCAIL source hash: {internal_id}")
    return errors


def validate_uploaded_workflow_config(config):
    by_id = _target_by_id(config)
    errors = []
    forbidden = {"model", "model_name", "unet", "vae", "clip", "lora", "lora_0", "steps", "cfg", "sampler", "scheduler", "denoise", "device", "load_device", "blocks_to_swap"}
    for internal_id, provider_id in UPLOADED_WORKFLOW_TARGETS.items():
        item = by_id.get(internal_id)
        if not item:
            errors.append(f"missing uploaded workflow: {internal_id}")
            continue
        media_keys, param_keys, kind = UPLOADED_WORKFLOW_FIELDS[internal_id]
        media = item.get("rh_media") or {}
        params = item.get("rh_params") or {}
        if (item.get("backend") != "runninghub" or item.get("kind") != kind
                or item.get("rh_workflow_id") != provider_id
                or item.get("name") != UPLOADED_WORKFLOW_NAMES[internal_id]
                or item.get("rh_schema_complete") is not True):
            errors.append(f"invalid uploaded workflow identity: {internal_id}")
        if set(media) != media_keys or set(params) != param_keys:
            errors.append(f"invalid uploaded workflow public schema: {internal_id}")
        expected_labels = UPLOADED_WORKFLOW_RESULT_LABELS[internal_id]
        actual_labels = item.get("rh_result_labels")
        if actual_labels != expected_labels:
            errors.append(f"uploaded workflow result labels drift: {internal_id}")
        control_projection = {
            "rh_media": media,
            "rh_params": params,
            "params_defaults": item.get("params_defaults") or {},
            "fixed_features": item.get("fixed_features") or [],
        }
        control_digest = hashlib.sha256(json.dumps(
            control_projection, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if control_digest != UPLOADED_WORKFLOW_CONTROL_SCHEMA_SHA256[internal_id]:
            errors.append(f"uploaded workflow control metadata drift: {internal_id}")
        direct = {str(row.get("field") or "").lower() for row in [*media.values(), *params.values()]}
        if forbidden.intersection({key.lower() for key in [*media, *params]}) or forbidden.intersection(direct):
            errors.append(f"unsafe uploaded workflow controls: {internal_id}")
        expected_editor_id, expected_editor_hash, expected_api_hash = UPLOADED_WORKFLOW_PROVENANCE[internal_id]
        if (str(item.get("source_editor_workflow_id") or "") != expected_editor_id
                or item.get("source_editor_json_sha256") != expected_editor_hash
                or item.get("source_api_json_sha256") != expected_api_hash):
            errors.append(f"uploaded workflow provenance drift: {internal_id}")
    return errors


def validate_scail_e2e_manifest():
    try:
        manifest = json.loads(SCAIL_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"SCAIL E2E manifest unreadable: {error}"]
    records = manifest.get("workflows") or {}
    errors = []
    for internal_id, workflow_id in SCAIL_VIDEO_TARGETS.items():
        record = records.get(internal_id) or {}
        if record.get("workflow_id") != workflow_id or record.get("status") != "SUCCESS" or not re.fullmatch(r"\d{16,24}", str(record.get("task_id") or "")) or int(record.get("result_count") or 0) < 1:
            errors.append(f"missing successful SCAIL E2E: {internal_id}")
    return errors


def validate_e2e_manifest(config):
    manifest = json.loads(E2E_MANIFEST.read_text(encoding="utf-8"))
    records = {row.get("id"): row for row in manifest.get("successful_workflows", [])}
    workflows = {item.get("id"): item for item in config.get("workflows", [])}
    errors = []
    for internal_id in TARGET_WORKFLOW_IDS:
        record = records.get(internal_id)
        workflow = workflows.get(internal_id)
        if not record or record.get("status") != "SUCCESS":
            errors.append(f"missing successful E2E: {internal_id}")
        elif not workflow or record.get("workflow_id") != workflow.get("rh_workflow_id"):
            errors.append(f"stale workflow id in E2E manifest: {internal_id}")
    return errors


def validate_uploaded_workflow_live_schema_manifest(config=None):
    try:
        record = json.loads(UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"uploaded workflow live schema manifest unreadable: {error}"]
    errors = []
    if (record.get("verification") != "PASS"
            or record.get("method") != "RunningHub getJsonApiFormat via current production service account; read-only, no task submit"
            or record.get("endpoint") != "https://www.runninghub.ai/api/openapi/getJsonApiFormat"
            or record.get("billing") != "none (schema reads only)"):
        errors.append("uploaded workflow live schema identity invalid")
    try:
        verified_at = datetime.datetime.fromisoformat(str(record.get("verified_at") or ""))
        if verified_at.tzinfo is None:
            raise ValueError("timezone missing")
    except Exception:
        errors.append("uploaded workflow live schema timestamp invalid")
    rows = record.get("records")
    if not isinstance(rows, list) or len(rows) != len(UPLOADED_WORKFLOW_TARGETS):
        return errors + ["uploaded workflow live schema record set invalid"]
    by_id = {str(row.get("internal_id") or ""): row for row in rows if isinstance(row, dict)}
    if set(by_id) != set(UPLOADED_WORKFLOW_TARGETS):
        errors.append("uploaded workflow live schema ids invalid")
    config_by_id = _target_by_id(config) if config is not None else {}
    for internal_id, run_id in UPLOADED_WORKFLOW_TARGETS.items():
        row = by_id.get(internal_id)
        if not row:
            continue
        node_count, live_hash = UPLOADED_WORKFLOW_LIVE_SCHEMA[internal_id]
        actual_allowed = {
            (str(item.get("node") or ""), str(item.get("field") or ""), str(item.get("difference") or ""))
            for item in (row.get("allowed_structural_differences") or []) if isinstance(item, dict)
        }
        raw_structural = row.get("structural_differences")
        raw_scalar = row.get("scalar_difference_locations")
        if not isinstance(raw_structural, list) or not isinstance(raw_scalar, list):
            errors.append(f"uploaded workflow live difference lists invalid: {internal_id}")
            continue
        raw_structural_keys = {
            (str(item.get("node") or ""), str(item.get("field") or ""), str(item.get("difference") or ""))
            for item in raw_structural if isinstance(item, dict)
        }
        expected_allowed = UPLOADED_WORKFLOW_ALLOWED_LIVE_DIFFERENCES[internal_id]
        expected_equal = not expected_allowed
        if (row.get("run_workflow_id") != run_id or row.get("node_count") != node_count
                or row.get("http_status") != 200 or row.get("provider_code") != 0
                or row.get("live_canonical_sha256") != live_hash
                or row.get("verified") is not True or row.get("all_mappings_present") is not True
                or row.get("structural_difference_count") != len(raw_structural)
                or row.get("scalar_difference_count") != len(raw_scalar)
                or row.get("scalar_difference_count") != 0
                or raw_structural_keys != expected_allowed
                or row.get("canonical_equal") is not expected_equal
                or row.get("structural_equal") is not expected_equal
                or row.get("unexpected_structural_differences") != []
                or row.get("missing_expected_structural_differences") != []
                or actual_allowed != expected_allowed):
            errors.append(f"uploaded workflow live schema invalid: {internal_id}")
            continue
        if config is not None:
            workflow = config_by_id.get(internal_id) or {}
            expected_mappings = {
                (scope, key, str(mapping.get("node") or ""), str(mapping.get("field") or ""))
                for scope in ("rh_media", "rh_params")
                for key, mapping in (workflow.get(scope) or {}).items()
            }
            manifest_mappings = {
                (str(item.get("scope") or ""), str(item.get("key") or ""),
                 str(item.get("node") or ""), str(item.get("field") or ""))
                for item in (row.get("mappings") or [])
                if isinstance(item, dict) and item.get("live_present") is True
            }
            if manifest_mappings != expected_mappings:
                errors.append(f"uploaded workflow live mappings invalid: {internal_id}")
    return errors


def validate_uploaded_workflow_e2e_manifest(config=None):
    try:
        record = json.loads(UPLOADED_WORKFLOW_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"uploaded workflow E2E manifest unreadable: {error}"]
    errors = []
    rows = record.get("workflows") or {}
    if (record.get("verification") != "PASS_WITH_DISCLOSED_VISUAL_WARNINGS"
            or set(rows) != set(UPLOADED_WORKFLOW_TARGETS)):
        return ["uploaded workflow E2E manifest identity invalid"]
    expected = {
        "qwen_image_edit_zip": ("dc292a0496d7", "2098482621837561858", "32",
                                  [("ZIP", "527afde489a99ed5f40ce5ea08f21981228bec4e385700c6bbbf2e35cb1f8ce1")]),
        "h3_edit_t3": ("9afefec7b35c", "2098487571991543810", "57", [
            ("ISO-BMFF", "dedd780d9e41a47333f4a162e1813f5522482e525ef13d2e8ba0ef1ccdbdf9a9"),
            ("ISO-BMFF", "26ee89d599eb3a8d609383826e3de681d8922bf6e75e3eb6b373a4c0b9df19fa")]),
        "h3_edit_remove": ("53a605803781", "2098487578251001857", "55", [
            ("ISO-BMFF", "c9468119e5a1dfce813fd5ec68c5aa87707f19d9c5f9ffdb703f193c6379187a"),
            ("ISO-BMFF", "0e3700208e11fd0b08622901f51e1350fc793f5ecf2b6c2ef008b6f6af5d541d")]),
        "h3_edit_n": ("f6429e986717", "2098525802599895042", "36",
                       [("ISO-BMFF", "09ceb6c22a7131946377ec57bfd477520766f9bc09d93063ae5dfafb68d7a58b")]),
        "wan_action_stabilized": ("6079ca16cb0c", "2098587433266663425", "51",
                                  [("ZIP", "2dcc1c1031b454624c971e53edc83d771833b214999fc9cd3498472e7f4f74b7")]),
        "scail2_action_replace": ("529d7df24fdb", "2098585909081964545", "82", [
            ("ISO-BMFF", "7f0d8b529004b5d4e0f33dcab7ee82e5e92432efc5be46520aca824631cf836e"),
            ("ISO-BMFF", "6dff841440376f208d1792cab3b7a1f55f362a526907c6b2d0f0729ae0faa85c")]),
    }
    warnings = {"h3_edit_remove", "scail2_action_replace"}
    hardened = {"h3_edit_n", "wan_action_stabilized", "scail2_action_replace"}
    for internal_id, run_id in UPLOADED_WORKFLOW_TARGETS.items():
        row = rows.get(internal_id) or {}
        artifacts = row.get("artifacts") or []
        job_id, provider_task_id, coins, expected_artifacts = expected[internal_id]
        if (row.get("run_workflow_id") != run_id or row.get("submit_attempts") != 1
                or row.get("status") != "done" or row.get("provider_status") != "DONE"
                or row.get("rh_coins") != coins or row.get("job_id") != job_id
                or row.get("provider_task_id") != provider_task_id
                or row.get("result_count") != len(artifacts) or not artifacts
                or [(item.get("container"), item.get("sha256")) for item in artifacts] != expected_artifacts
                or row.get("functional") != "PASS" or row.get("mechanical") != "PASS"):
            errors.append(f"uploaded workflow E2E job invalid: {internal_id}")
        for artifact in artifacts:
            if (artifact.get("container") not in {"ZIP", "ISO-BMFF"}
                    or not isinstance(artifact.get("bytes"), int) or artifact.get("bytes") <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256") or ""))):
                errors.append(f"uploaded workflow E2E artifact invalid: {internal_id}")
        if internal_id in warnings and (row.get("strict_visual") != "WARNING"
                                        or not row.get("visual_warning")):
            errors.append(f"uploaded workflow visual warning missing: {internal_id}")
        if internal_id in hardened:
            if (row.get("security_wrapper_scope") != "opaque_upload_capability_verified"
                    or row.get("history_occurrences") != 1
                    or row.get("upload_token_exposed") is not False):
                errors.append(f"uploaded workflow hardened wrapper evidence invalid: {internal_id}")
        elif row.get("security_wrapper_scope") != "pre_upload_capability_hardening":
            errors.append(f"uploaded workflow early wrapper scope invalid: {internal_id}")
    serialized = json.dumps(record, ensure_ascii=False)
    if any(token in serialized for token in ("upl_", "http://", "https://", "provider_media", "C:\\\\")):
        errors.append("uploaded workflow E2E manifest contains private transport data")
    return errors


def validate_dreamapi_e2e_manifest():
    try:
        record = json.loads(DREAMAPI_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"DreamAPI E2E manifest unreadable: {error}"]
    successful = record.get("successful_e2e") or {}
    artifact = record.get("artifact") or {}
    visual = record.get("visual_review") or {}
    errors = []
    endpoint = record.get("endpoint_contract") or {}
    discovery = record.get("model_discovery") or {}
    credentials = record.get("credential_handling") or {}
    if record.get("verification") != "PASS" or record.get("provider") != "DreamAPI":
        errors.append("DreamAPI E2E did not pass")
    if endpoint != {
        "base_url": "https://dreamapi.club", "path": "/responses",
        "text_model": "gpt-5.6-sol", "tool_type": "image_generation", "tool_action": "generate",
    }:
        errors.append("DreamAPI E2E endpoint contract invalid")
    required_models = ("gpt_5_6_sol", "gpt_image_2", "gpt_image_2_5_flare", "gpt_image_2_5_sunburst")
    if discovery.get("http_status") != 200 or any(discovery.get(key) is not True for key in required_models):
        errors.append("DreamAPI E2E model discovery invalid")
    if (credentials.get("browser_received_key") is not False
            or credentials.get("repository_contains_key") is not False
            or credentials.get("remote_environment_file_mode") != "root:root 600"):
        errors.append("DreamAPI E2E credential handling invalid")
    try:
        verified_at = datetime.datetime.fromisoformat(str(record.get("verified_at") or ""))
        if verified_at.tzinfo is None:
            raise ValueError("timezone missing")
    except Exception:
        errors.append("DreamAPI E2E verification timestamp invalid")
    if (successful.get("status") != "done" or successful.get("provider_status") != "API_DONE"
            or successful.get("generation_backend") != "api" or successful.get("submit_attempts") != 1
            or successful.get("history_occurrences") != 1 or successful.get("seed_supported") is not False
            or successful.get("api_model") != "gpt-image-2.5-flare"
            or successful.get("api_quality") != "low" or successful.get("api_fit") != "cover"
            or successful.get("api_response_id_present") is not True
            or "api_response_id" in successful):
        errors.append("DreamAPI E2E job contract invalid")
    if (artifact.get("format") != "PNG" or artifact.get("width") != 768
            or artifact.get("height") != 1024 or artifact.get("bytes") != 507981
            or artifact.get("sha256") != "4ba551a2a08cfb5101bb807cd52637f96ca002f7139bb30a5460a89dd110615a"):
        errors.append("DreamAPI E2E artifact metadata invalid")
    artifact_path = DREAMAPI_E2E_MANIFEST.parent / str(artifact.get("file") or "")
    try:
        artifact_bytes = artifact_path.read_bytes()
    except Exception:
        errors.append("DreamAPI E2E artifact missing")
    else:
        if (len(artifact_bytes) != artifact.get("bytes")
                or hashlib.sha256(artifact_bytes).hexdigest() != artifact.get("sha256")
                or not artifact_bytes.startswith(b"\x89PNG\r\n\x1a\n")):
            errors.append("DreamAPI E2E artifact bytes invalid")
    if (visual.get("status") != "PASS" or visual.get("not_blank_or_corrupt") is not True
            or visual.get("complete_subject") is not True
            or visual.get("visible_text_logo_watermark") is not False
            or visual.get("obvious_crop_problem") is not False):
        errors.append("DreamAPI E2E visual review invalid")
    first = record.get("first_diagnostic_attempt") or {}
    if first.get("status") != "error" or first.get("submit_attempts") != 1 or first.get("automatic_retry") is not False:
        errors.append("DreamAPI first diagnostic failure record invalid")
    return errors


def validate_retro_cloud_e2e_manifest():
    try:
        record = json.loads(RETRO_CLOUD_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"retro cloud E2E manifest unreadable: {error}"]
    actual = record.get("authoritative_remote_job_record") or {}
    artifact = record.get("artifact") or {}
    visual = record.get("visual_review") or {}
    errors = []
    if record.get("verification") != "PASS":
        errors.append("retro cloud E2E did not pass")
    if record.get("rh_coins") != "6" or actual.get("rh_coins") != "6":
        errors.append("retro cloud E2E billed coins invalid")
    if not re.fullmatch(r"\d{16,24}", str(record.get("rh_task_id") or "")):
        errors.append("retro cloud E2E task id invalid")
    if actual.get("rh_task_id") != record.get("rh_task_id"):
        errors.append("retro cloud E2E task id mismatch")
    if actual.get("status") != "done" or actual.get("provider_status") != "DONE":
        errors.append("retro cloud E2E provider status invalid")
    if actual.get("client_request_id") != "retro-cloud-w04-32421-final":
        errors.append("retro cloud E2E request id invalid")
    if actual.get("workflow") != "anima02" or actual.get("style_id") != "retro_manga_luxury":
        errors.append("retro cloud E2E route invalid")
    if actual.get("trigger") != "jt_style321_v1":
        errors.append("retro cloud E2E trigger invalid")
    expected_loras = {"LORA1": "09_style321_v1_step200.safetensors", "LORA2": "09_style321_v1_step200.safetensors"}
    if actual.get("loras") != expected_loras or actual.get("lora_strengths") != {"LORA1": 0.4, "LORA2": 0.0}:
        errors.append("retro cloud E2E LoRA mapping invalid")
    if tuple(actual.get(key) for key in ("width", "height", "batch", "hd", "seed")) != (768, 1024, 1, 0, 32421):
        errors.append("retro cloud E2E generation parameters invalid")
    if (not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256") or ""))
            or artifact.get("format") != "PNG"
            or (artifact.get("width"), artifact.get("height")) != (768, 1024)
            or artifact.get("bytes") != 1042674
            or artifact.get("sha256") != "a11974ba1341a36c76499b815a8f84611303493594805d03e9fc26d87156b2da"):
        errors.append("retro cloud E2E artifact invalid")
    results = record.get("results") or []
    if (record.get("result_count") != 1 or len(results) != 1
            or results[0].get("bytes") != artifact.get("bytes")
            or results[0].get("sha256") != artifact.get("sha256")
            or results[0].get("png_signature") is not True
            or record.get("artifact_sha256") != artifact.get("sha256")):
        errors.append("retro cloud E2E result evidence mismatch")
    if visual.get("functional_style_evidence") != "PASS" or visual.get("strict_promotional_visual") != "FAIL":
        errors.append("retro cloud E2E visual classification invalid")
    return errors


def require_clean_git():
    result = subprocess.run(["git", "status", "--porcelain"], cwd=BASE, text=True,
                            capture_output=True, check=True)
    if result.stdout.strip():
        raise RuntimeError("git working tree is not clean; commit the reviewed release first")


def classify_release_tests(test_dir=None):
    test_dir = pathlib.Path(test_dir or (BASE / "tests"))
    scripts = []
    pytest_files = []
    for path in sorted(test_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_pytest_tests = any(
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"))
            or (isinstance(node, ast.ClassDef) and node.name.startswith("Test"))
            for node in tree.body
        )
        (pytest_files if has_pytest_tests else scripts).append(path)
    return scripts, pytest_files


def run_release_tests(test_dir=None):
    scripts, pytest_files = classify_release_tests(test_dir)
    failures = []
    for path in scripts:
        result = subprocess.run(
            [sys.executable, str(path)], cwd=BASE, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
        )
        expected_failure = path.name in KNOWN_BASELINE_SCRIPT_FAILURES
        if expected_failure and result.returncode == 0:
            failures.append({
                "file": path.name,
                "output": "known baseline unexpectedly passed; remove its strict release exception",
            })
        elif expected_failure and result.returncode != 1:
            failures.append({
                "file": path.name,
                "output": f"known baseline exit code changed: {result.returncode}",
            })
        elif expected_failure and result.stdout.splitlines() != list(KNOWN_BASELINE_SCRIPT_FAILURES[path.name]):
            failures.append({
                "file": path.name,
                "output": "known baseline output changed: " + result.stdout[-1200:],
            })
        elif result.returncode and not expected_failure:
            failures.append({"file": path.name, "output": result.stdout[-1200:]})
    if pytest_files:
        command_line = [sys.executable, "-m", "pytest", "-q", *map(str, pytest_files)]
        result = subprocess.run(
            command_line, cwd=BASE, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200,
        )
        if result.returncode:
            failures.append({"file": "pytest", "output": result.stdout[-4000:]})
    if failures:
        raise RuntimeError("release tests failed: " + json.dumps(failures, ensure_ascii=False))


def auth_is_disabled(server_source):
    """Detect the deliberate `return True` _auth implementation via AST."""
    try:
        tree = ast.parse(server_source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_auth":
            returns = [child for child in ast.walk(node) if isinstance(child, ast.Return)]
            return bool(returns) and all(
                isinstance(ret.value, ast.Constant) and ret.value.value is True
                for ret in returns
            )
    return False


def validate_public_upload_quota(server_source):
    required = {
        "UPLOAD_SESSION_HOURLY_LIMIT": 20,
        "UPLOAD_GLOBAL_HOURLY_LIMIT": 100,
        "UPLOAD_SESSION_HOURLY_BYTES": 500 * 1024 * 1024,
        "UPLOAD_GLOBAL_HOURLY_BYTES": 2 * 1024 * 1024 * 1024,
    }
    errors = []
    try:
        tree = ast.parse(server_source)
    except SyntaxError as error:
        return [f"server syntax invalid for upload quota: {error}"]
    def integer_constant(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left, right = integer_constant(node.left), integer_constant(node.right)
            if left is not None and right is not None:
                return left * right
        return None

    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = integer_constant(node.value)
            if value is not None:
                assignments[node.targets[0].id] = value
    for name, value in required.items():
        if assignments.get(name) != value:
            errors.append(f"public upload quota invalid: {name}")
    definitions = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "reserve_upload_attempt"
    )
    calls = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "reserve_upload_attempt"
    )
    if definitions != 1 or calls != 3:
        errors.append("not all public upload routes are quota guarded")
    if ("_upload_usage_lock = threading.Lock()" not in server_source
            or "load_upload_usage()" not in server_source
            or "Retry-After" not in server_source):
        errors.append("public upload quota persistence or response missing")
    return errors


def validate_public_billable_quota(server_source):
    required = {
        "BILLABLE_GLOBAL_HOURLY_LIMIT": 10,
        "BILLABLE_GLOBAL_DAILY_LIMIT": 30,
        "BILLABLE_SESSION_HOURLY_LIMIT": 4,
    }
    try:
        tree = ast.parse(server_source)
    except SyntaxError as error:
        return [f"server source cannot be parsed: {error}"]
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in required and isinstance(node.value, ast.Constant):
                    values[target.id] = node.value.value
    errors = []
    for name, expected in required.items():
        if values.get(name) != expected:
            errors.append(f"public billable quota drift: {name}")
    function_defs = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "register_billable_job"
    )
    guarded_calls = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "register_billable_job"
    )
    if function_defs != 1 or guarded_calls != 4:
        errors.append("not all public billable routes are quota guarded")
    for marker in ("_billable_quota_lock", "Retry-After", "billable_quota_recorded"):
        if marker not in server_source:
            errors.append(f"missing public billable quota control: {marker}")
    return errors


def preflight_decision(config, server_source, execute=False, allow_unauthenticated_public=False):
    config_result = validate_release_config(config)
    scail_errors = validate_scail_video_config(config) + validate_scail_e2e_manifest()
    uploaded_errors = validate_uploaded_workflow_config(config)
    uploaded_live_schema_errors = validate_uploaded_workflow_live_schema_manifest(config)
    uploaded_e2e_errors = validate_uploaded_workflow_e2e_manifest(config)
    dreamapi_e2e_errors = validate_dreamapi_e2e_manifest()
    retro_cloud_errors = validate_retro_cloud_e2e_manifest()
    unauthenticated = auth_is_disabled(server_source)
    public_quota_errors = validate_public_billable_quota(server_source) if unauthenticated else []
    public_upload_quota_errors = validate_public_upload_quota(server_source) if unauthenticated else []
    blockers = []
    if config_result["missing_targets"]:
        blockers.append("missing target workflows")
    if config_result["invalid_targets"]:
        blockers.append("invalid or incomplete target schemas")
    if scail_errors:
        blockers.append("invalid SCAIL video schemas")
    if uploaded_errors:
        blockers.append("invalid uploaded workflow schemas")
    if uploaded_live_schema_errors:
        blockers.append("invalid uploaded workflow live schemas")
    if uploaded_e2e_errors:
        blockers.append("invalid uploaded workflow E2E")
    if dreamapi_e2e_errors:
        blockers.append("invalid DreamAPI creator E2E")
    if retro_cloud_errors:
        blockers.append("invalid retro creator cloud E2E")
    if public_quota_errors:
        blockers.append("invalid public billable quota controls")
    if public_upload_quota_errors:
        blockers.append("invalid public upload quota controls")
    if not execute:
        blockers.append("--execute not supplied")
    if unauthenticated and not allow_unauthenticated_public:
        blockers.append("unauthenticated public access not accepted")
    return {
        "ready": not blockers,
        "config_ready": config_result["ready"],
        "auth_disabled": unauthenticated,
        "execute": bool(execute),
        "allow_unauthenticated_public": bool(allow_unauthenticated_public),
        "missing_targets": config_result["missing_targets"],
        "invalid_targets": config_result["invalid_targets"],
        "scail_video_errors": scail_errors,
        "uploaded_workflow_errors": uploaded_errors,
        "uploaded_workflow_live_schema_errors": uploaded_live_schema_errors,
        "uploaded_workflow_e2e_errors": uploaded_e2e_errors,
        "dreamapi_e2e_errors": dreamapi_e2e_errors,
        "retro_cloud_e2e_errors": retro_cloud_errors,
        "public_billable_quota_errors": public_quota_errors,
        "public_upload_quota_errors": public_upload_quota_errors,
        "blockers": blockers,
    }


def release_files():
    files = {BASE / rel: f"{REMOTE_ROOT}/{rel}" for rel in RELEASE_RELATIVE_PATHS}
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("missing release files: " + ", ".join(missing))
    for path in files:
        lower = path.read_bytes().lower()
        if b"fixture_3in1" in lower or b"fixture-never-sent" in lower or b"realism_fixture" in lower:
            raise RuntimeError(f"test fixture marker in production release file: {path}")
    return files


def command(client, text, timeout=240):
    _, stdout, stderr = client.exec_command(text, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    if code:
        raise RuntimeError(f"remote command failed ({code}): {err or out}")
    return out


def new_release_transaction():
    transaction_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex
    root = RELEASE_TRANSACTIONS_DIR + "/" + transaction_id
    return {
        "id": transaction_id, "root": root,
        "stage_root": root + "/stage", "backup_root": root + "/backup",
        "manifest": root + "/manifest.json",
        "manifest_sha256": root + "/manifest.sha256",
    }


def transaction_file(transaction, remote, area):
    relative = pathlib.PurePosixPath(remote).relative_to(pathlib.PurePosixPath(REMOTE_ROOT))
    return str(pathlib.PurePosixPath(transaction[f"{area}_root"]) / relative)


def acquire_release_lock(client, transaction):
    owner = str(transaction["id"])
    script = (
        "set -eu; umask 077; "
        f"mkdir -p -- {shlex.quote(RELEASE_TRANSACTIONS_DIR)}; "
        f"chmod 0700 -- {shlex.quote(RELEASE_TRANSACTIONS_DIR)}; "
        f"if ! mkdir -- {shlex.quote(RELEASE_LOCK_DIR)} 2>/dev/null; then "
        "echo 'release already locked' >&2; exit 73; fi; "
        f"cleanup_release_lock() {{ rm -rf -- {shlex.quote(RELEASE_LOCK_DIR)}; }}; "
        "trap cleanup_release_lock EXIT; "
        f"chmod 0700 -- {shlex.quote(RELEASE_LOCK_DIR)}; "
        f"printf '%s\\n' {shlex.quote(owner)} > {shlex.quote(RELEASE_LOCK_DIR + '/owner')}; "
        f"mkdir -p -- {shlex.quote(transaction['stage_root'])} {shlex.quote(transaction['backup_root'])}; "
        f"chmod 0700 -- {shlex.quote(transaction['root'])} {shlex.quote(transaction['stage_root'])} "
        f"{shlex.quote(transaction['backup_root'])}; trap - EXIT"
    )
    command(client, script)


def release_release_lock(client, transaction):
    owner = str(transaction["id"])
    script = (
        "set -eu; "
        f"test \"$(cat {shlex.quote(RELEASE_LOCK_DIR + '/owner')})\" = {shlex.quote(owner)}; "
        f"rm -rf -- {shlex.quote(RELEASE_LOCK_DIR)}"
    )
    command(client, script)


def cleanup_release_transaction(client, transaction, keep=3):
    """Bound completed transaction retention while preserving recent evidence."""
    marker = transaction["root"] + "/completed"
    script = (
        "set -eu; umask 077; "
        f"touch -- {shlex.quote(marker)}; chmod 0600 -- {shlex.quote(marker)}; "
        "python3 -c " + shlex.quote(
            "import pathlib,shutil;"
            f"root=pathlib.Path({RELEASE_TRANSACTIONS_DIR!r});"
            "rows=sorted((p for p in root.iterdir() if p.is_dir() and (p/'completed').is_file()),"
            "key=lambda p:p.name,reverse=True);"
            f"[shutil.rmtree(p) for p in rows[{int(keep)}:]]"
        )
    )
    command(client, script)


def write_transaction_phase(client, transaction, phase):
    """Durably checkpoint the release phase for crash recovery diagnostics."""
    allowed = {"prepared", "swapping", "committed", "rolling-back",
               "rolled-back", "rollback-failed"}
    if phase not in allowed:
        raise ValueError("invalid release transaction phase")
    path = transaction["root"] + "/phase"
    temporary = path + ".tmp-" + uuid.uuid4().hex
    script = (
        "import os,pathlib;"
        f"path=pathlib.Path({path!r});tmp=pathlib.Path({temporary!r});"
        f"data={(phase + chr(10))!r}.encode('ascii');"
        "f=open(tmp,'wb');f.write(data);f.flush();os.fsync(f.fileno());f.close();"
        "os.chmod(tmp,0o600);os.replace(tmp,path);"
        "d=os.open(str(path.parent),os.O_RDONLY);os.fsync(d);os.close(d)"
    )
    command(client, "python3 -c " + shlex.quote(script))


def stage_file_resilient(client, local, remote, transaction):
    """Upload and byte-verify one file inside this release transaction."""
    data = local.read_bytes()
    staged = transaction_file(transaction, remote, "stage")
    parent = str(pathlib.PurePosixPath(staged).parent)
    command(client, "mkdir -p -- " + shlex.quote(parent) + "; chmod 0700 -- " + shlex.quote(parent))
    last_error = None
    for attempt in range(1, 4):
        sftp = None
        try:
            sftp = client.open_sftp()
            with sftp.open(staged, "wb") as handle:
                handle.write(data)
            with sftp.open(staged, "rb") as handle:
                if handle.read() != data:
                    raise RuntimeError(f"staging mismatch: {local}")
            command(client, "chmod 0600 -- " + shlex.quote(staged))
            return staged
        except Exception as error:
            last_error = error
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
    raise last_error


def backup_release(client, sftp, remote_paths, transaction):
    """Snapshot the previous live set into one immutable transaction."""
    manifest = {}
    for remote in remote_paths:
        backup = transaction_file(transaction, remote, "backup")
        parent = str(pathlib.PurePosixPath(backup).parent)
        command(client, "mkdir -p -- " + shlex.quote(parent) + "; chmod 0700 -- " + shlex.quote(parent))
        try:
            remote_stat = sftp.stat(remote)
        except FileNotFoundError:
            manifest[remote] = {"exists": False, "sha256": None, "mode": None}
        else:
            command(client, f"cp -- {shlex.quote(remote)} {shlex.quote(backup)}")
            command(client, f"chmod 0600 -- {shlex.quote(backup)}")
            digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({backup!r},'rb').read()).hexdigest())"
            )).strip()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(f"backup digest invalid: {remote}")
            manifest[remote] = {
                "exists": True, "sha256": digest,
                "mode": int(remote_stat.st_mode) & 0o7777,
            }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    manifest_tmp = transaction["manifest"] + ".tmp-" + uuid.uuid4().hex
    manifest_sha256_tmp = transaction["manifest_sha256"] + ".tmp-" + uuid.uuid4().hex
    script = (
        "import os,pathlib;"
        f"manifest=pathlib.Path({transaction['manifest']!r});"
        f"manifest_tmp=pathlib.Path({manifest_tmp!r});"
        f"manifest_tmp.write_text({payload!r},encoding='utf-8');"
        "os.replace(manifest_tmp,manifest);os.chmod(manifest,0o600);"
        f"manifest_sha256=pathlib.Path({transaction['manifest_sha256']!r});"
        f"manifest_sha256_tmp=pathlib.Path({manifest_sha256_tmp!r});"
        f"manifest_sha256_tmp.write_text({(manifest_digest + chr(10))!r},encoding='ascii');"
        "os.replace(manifest_sha256_tmp,manifest_sha256);os.chmod(manifest_sha256,0o600)"
    )
    command(client, "python3 -c " + shlex.quote(script))
    return manifest


def rollback_release(client, sftp, remote_paths, transaction, public_base=PUBLIC_BASE):
    """Restore one verified transaction; remain stopped on any uncertainty."""
    command(client, "sudo systemctl stop comfy-panel", timeout=240)
    try:
        manifest_raw = command(client, "python3 -c " + shlex.quote(
            f"import pathlib;print(pathlib.Path({transaction['manifest']!r}).read_text(encoding='utf-8'),end='')"
        ))
        expected_digest = command(client, "python3 -c " + shlex.quote(
            f"import pathlib;print(pathlib.Path({transaction['manifest_sha256']!r}).read_text(encoding='ascii').strip())"
        )).strip()
        actual_digest = hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()
        if (not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
                or not hmac.compare_digest(actual_digest, expected_digest)):
            raise ValueError("manifest hash mismatch")
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict) or set(manifest) != set(remote_paths):
            raise ValueError("manifest file set mismatch")
    except Exception as error:
        raise RuntimeError(f"backup manifest unreadable or unverified: {error}; panel left stopped") from error

    errors = []
    for remote in remote_paths:
        try:
            entry = manifest.get(remote)
            if not isinstance(entry, dict) or set(entry) != {"exists", "sha256", "mode"}:
                raise RuntimeError("invalid manifest entry")
            if entry.get("exists") is False:
                if entry.get("sha256") is not None or entry.get("mode") is not None:
                    raise RuntimeError("invalid absent-file digest")
                command(client, f"rm -f -- {shlex.quote(remote)}")
                continue
            expected = str(entry.get("sha256") or "")
            if entry.get("exists") is not True or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise RuntimeError("invalid backup digest")
            mode = entry.get("mode")
            if not isinstance(mode, int) or isinstance(mode, bool) or not (0 <= mode <= 0o7777):
                raise RuntimeError("invalid backup mode")
            backup = transaction_file(transaction, remote, "backup")
            backup_digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({backup!r},'rb').read()).hexdigest())"
            )).strip()
            if not hmac.compare_digest(backup_digest, expected):
                raise RuntimeError(f"backup verification mismatch: {remote}")
            command(client, "mkdir -p -- " + shlex.quote(str(pathlib.PurePosixPath(remote).parent)))
            command(client, f"cp -- {shlex.quote(backup)} {shlex.quote(remote)}")
            command(client, f"chmod {mode:04o} -- {shlex.quote(remote)}")
            live_digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({remote!r},'rb').read()).hexdigest())"
            )).strip()
            if not hmac.compare_digest(live_digest, expected):
                raise RuntimeError(f"rollback verification mismatch: {remote}")
        except Exception as error:
            errors.append(f"{remote}: {error}")
    if errors:
        raise RuntimeError("rollback failed; panel left stopped: " + "; ".join(errors))

    try:
        command(client, "sudo systemctl start comfy-panel", timeout=240)
        live = wait_for_live(public_base, timeout=60, allow_legacy=True)
        if not live.get("ok"):
            raise RuntimeError(str(live))
    except Exception as error:
        command(client, "sudo systemctl stop comfy-panel", timeout=240)
        raise RuntimeError(
            f"rollback health failed; panel left stopped: {error}"
        ) from error


def fetch_json(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=60) as response:
        return json.load(response)


def fetch_bytes(base, path, timeout=60, accept_gzip=False):
    headers = {"Accept-Encoding": "gzip"} if accept_gzip else {}
    request = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return gzip.decompress(body) if response.headers.get("Content-Encoding") == "gzip" else body


def fetch_bytes_resilient(base, path, timeout=300, accept_gzip=False, attempts=3, deadline=None):
    last_error = None
    for attempt in range(1, attempts + 1):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise RuntimeError("public large response verification timeout") from last_error
        request_timeout = timeout if remaining is None else min(timeout, remaining)
        try:
            return fetch_bytes(
                base, path, timeout=request_timeout, accept_gzip=accept_gzip
            )
        except Exception as error:
            last_error = error
            if attempt == attempts:
                raise
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise RuntimeError("public large response verification timeout") from error
            delay = attempt * 2
            if remaining is not None:
                delay = min(delay, remaining)
            time.sleep(delay)
    raise last_error


def verify_public_large_responses(base):
    expected_creator = (BASE / "static" / "index.html").read_bytes()
    expected_preview = (BASE / "static" / "previews" / "style-retro-manga-luxury.webp").read_bytes()
    deadline = time.monotonic() + PUBLIC_LARGE_VERIFY_TIMEOUT
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("public large response verification timeout")
        creator = fetch_bytes_resilient(
            base, "/?style=retro_manga_luxury", timeout=300, accept_gzip=True,
            attempts=3, deadline=deadline,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("public large response verification timeout")
        preview = fetch_bytes_resilient(
            base, "/static/previews/style-retro-manga-luxury.webp",
            timeout=300, attempts=3, deadline=deadline,
        )
        if creator != expected_creator:
            raise RuntimeError(f"public creator large response mismatch on attempt {attempt + 1}")
        if preview != expected_preview:
            raise RuntimeError(f"public creator preview mismatch on attempt {attempt + 1}")
    return expected_creator, expected_preview


def wait_for_health(base, timeout=60):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            result = fetch_json(base, "/api/health")
            if result.get("ok"):
                return result
            last = result
        except Exception as error:
            last = {"error": str(error)[:200]}
        time.sleep(2)
    raise RuntimeError(f"health timeout: {last}")


def wait_for_live(base, timeout=60, allow_legacy=False):
    """Verify the panel process itself, independent of the ComfyUI tunnel."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            result = fetch_json(base, "/api/live")
            if result.get("ok") and result.get("service") == "comfy-panel":
                return result
            last = result
        except urllib.request.HTTPError as error:
            if allow_legacy and error.code == 404:
                try:
                    workflows = fetch_json(base, "/api/workflows")
                    if isinstance(workflows, list):
                        return {"ok": True, "service": "comfy-panel-legacy"}
                except Exception as legacy_error:
                    last = {"error": str(legacy_error)[:200]}
                    time.sleep(2)
                    continue
            last = {"error": str(error)[:200]}
        except Exception as error:
            last = {"error": str(error)[:200]}
        time.sleep(2)
    raise RuntimeError(f"liveness timeout: {last}")


def install_watchdog_units(client):
    service_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.service"
    timer_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.timer"
    command(client, "sudo systemctl unmask comfy-panel-watchdog.service comfy-panel-watchdog.timer || true")
    command(client, "sudo install -d -o root -g root -m 0755 /usr/local/libexec")
    command(client, "sudo install -o root -g root -m 0755 " + shlex.quote(REMOTE_ROOT + "/tools/panel_liveness_watchdog.py") + " " + shlex.quote(WATCHDOG_EXECUTABLE))
    command(client, "sudo install -o root -g root -m 0644 " + shlex.quote(service_src) + " " + shlex.quote(WATCHDOG_SERVICE_UNIT))
    command(client, "sudo install -o root -g root -m 0644 " + shlex.quote(timer_src) + " " + shlex.quote(WATCHDOG_TIMER_UNIT))
    command(client, "sudo systemctl daemon-reload")
    command(client, "sudo systemctl enable --now comfy-panel-watchdog.timer")
    if command(client, "systemctl is-enabled comfy-panel-watchdog.timer").strip() != "enabled":
        raise RuntimeError("watchdog timer is not enabled")
    if command(client, "systemctl is-active comfy-panel-watchdog.timer").strip() != "active":
        raise RuntimeError("watchdog timer is not active")


def capture_watchdog_state(client):
    """Snapshot exact unit bytes plus enabled/active state before mutation."""
    script = """import base64,json,pathlib,subprocess
def unit(path):
    p=pathlib.Path(path)
    return p.is_file(), base64.b64encode(p.read_bytes()).decode() if p.is_file() else ''
def systemctl(*args):
    r=subprocess.run(['systemctl',*args],text=True,capture_output=True)
    return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ''
service_exists,service_b64=unit('/etc/systemd/system/comfy-panel-watchdog.service')
timer_exists,timer_b64=unit('/etc/systemd/system/comfy-panel-watchdog.timer')
executable_exists,executable_b64=unit('/usr/local/libexec/comfy-panel-watchdog.py')
print(json.dumps({'service_exists':service_exists,'service_b64':service_b64,
                  'timer_exists':timer_exists,'timer_b64':timer_b64,
                  'executable_exists':executable_exists,'executable_b64':executable_b64,
                  'service_active':systemctl('is-active','comfy-panel-watchdog.service'),
                  'timer_enabled':systemctl('is-enabled','comfy-panel-watchdog.timer'),
                  'timer_active':systemctl('is-active','comfy-panel-watchdog.timer')}))
"""
    state = json.loads(command(client, "python3 -c " + shlex.quote(script)))
    required = {"service_exists", "service_b64", "timer_exists", "timer_b64",
                "executable_exists", "executable_b64",
                "service_active", "timer_enabled", "timer_active"}
    if not isinstance(state, dict) or not required.issubset(state):
        raise RuntimeError("invalid watchdog state snapshot")
    return state


def restore_watchdog_state(client, state):
    """Restore the exact previous unit files and their enable/activity state."""
    command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer || true")
    command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl unmask comfy-panel-watchdog.service comfy-panel-watchdog.timer || true")
    for exists_key, data_key, remote in (
        ("service_exists", "service_b64", WATCHDOG_SERVICE_UNIT),
        ("timer_exists", "timer_b64", WATCHDOG_TIMER_UNIT),
        ("executable_exists", "executable_b64", WATCHDOG_EXECUTABLE),
    ):
        if state.get(exists_key):
            encoded = str(state.get(data_key) or "")
            script = (
                "import base64,pathlib;"
                f"pathlib.Path({remote!r}).write_bytes(base64.b64decode({encoded!r}))"
            )
            command(client, "sudo python3 -c " + shlex.quote(script))
            if remote == WATCHDOG_EXECUTABLE:
                command(client, "sudo chown root:root " + shlex.quote(remote))
                command(client, "sudo chmod 0755 " + shlex.quote(remote))
        else:
            command(client, "sudo rm -f " + shlex.quote(remote))
    command(client, "sudo systemctl daemon-reload")

    enabled = str(state.get("timer_enabled") or "")
    active = str(state.get("timer_active") or "")
    if enabled == "masked":
        command(client, "sudo systemctl mask comfy-panel-watchdog.timer")
    elif enabled in {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}:
        command(client, "sudo systemctl enable comfy-panel-watchdog.timer")
    if active in {"active", "activating", "reloading"}:
        command(client, "sudo systemctl start comfy-panel-watchdog.timer")
    else:
        command(client, "sudo systemctl stop comfy-panel-watchdog.timer || true")
    service_active = str(state.get("service_active") or "")
    if service_active in {"active", "activating", "reloading"}:
        command(client, "sudo systemctl start comfy-panel-watchdog.service")
    else:
        command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")


def remove_watchdog_units(client):
    command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer || true")
    command(client, "sudo rm -f /etc/systemd/system/comfy-panel-watchdog.service /etc/systemd/system/comfy-panel-watchdog.timer /usr/local/libexec/comfy-panel-watchdog.py")
    command(client, "sudo systemctl daemon-reload")


def deploy(files, public_base=PUBLIC_BASE):
    """Stage all files, verify, swap, read back, health-check; rollback on failure."""
    # Imported and credentials read only after fail-closed local preflight.
    import paramiko

    class PinnedSHA256Policy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            actual = "SHA256:" + base64.b64encode(
                hashlib.sha256(key.asbytes()).digest()
            ).decode("ascii").rstrip("=")
            if not hmac.compare_digest(actual, SSH_HOST_KEY_SHA256):
                raise paramiko.SSHException(
                    f"SSH host key mismatch for {hostname}: expected pinned fingerprint"
                )

    creds_path = BASE / "tools" / "creds.json"
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedSHA256Policy())
    client.connect(
        creds["host"], port=int(creds["port"]), username=creds["user"],
        password=creds["password"], timeout=30,
        allow_agent=False, look_for_keys=False,
    )
    sftp = None
    remote_paths = list(files.values())
    transaction = new_release_transaction()
    lock_acquired = False
    rollback_uncertain = False
    watchdog_state = None
    try:
        acquire_release_lock(client, transaction)
        lock_acquired = True
        watchdog_state = capture_watchdog_state(client)
        remote_parent_paths = sorted({str(pathlib.PurePosixPath(remote).parent) for remote in remote_paths})
        command(client, "mkdir -p -- " + " ".join(shlex.quote(path) for path in remote_parent_paths))
        for local, remote in files.items():
            stage_file_resilient(client, local, remote, transaction)

        sftp = client.open_sftp()
        staged_server = transaction_file(transaction, REMOTE_ROOT + "/server.py", "stage")
        command(client, f"python3 -m py_compile {shlex.quote(staged_server)}")
        staged_config = transaction_file(transaction, REMOTE_ROOT + "/config.json", "stage")
        command(client, "python3 -c " + shlex.quote(
            f"import json; json.load(open({staged_config!r}, encoding='utf-8'))"
        ))
        release_manifest = backup_release(client, sftp, remote_paths, transaction)
        write_transaction_phase(client, transaction, "prepared")

        try:
            command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer || true")
            command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")
            command(client, "sudo systemctl mask --runtime comfy-panel-watchdog.service || true")
            command(client, "sudo systemctl stop comfy-panel", timeout=240)
            write_transaction_phase(client, transaction, "swapping")
            for remote in remote_paths:
                staged = transaction_file(transaction, remote, "stage")
                try:
                    sftp.posix_rename(staged, remote)
                except Exception:
                    command(client, f"mv -f -- {shlex.quote(staged)} {shlex.quote(remote)}")
                previous = release_manifest.get(remote) or {}
                mode = previous.get("mode") if previous.get("exists") is True else 0o644
                if not isinstance(mode, int) or isinstance(mode, bool):
                    raise RuntimeError(f"invalid release mode: {remote}")
                command(client, f"chmod {mode:04o} -- {shlex.quote(remote)}")

            for local, remote in files.items():
                local_data = local.read_bytes()
                with sftp.open(remote, "rb") as handle:
                    live_data = handle.read()
                if live_data != local_data:
                    raise RuntimeError(f"live mismatch: {local}")
                print(local.name, len(local_data), hashlib.sha256(local_data).hexdigest())

            command(client, "sudo systemctl start comfy-panel", timeout=240)
            live = wait_for_live(public_base, timeout=60)
            try:
                health = fetch_json(public_base, "/api/health")
            except Exception as error:
                health = {"ok": False, "error": str(error)[:200]}
            if not isinstance(health, dict) or health.get("dreamapi_configured") is not True:
                raise RuntimeError("public DreamAPI channel is not configured")
            realism = fetch_bytes(public_base, "/realism")
            home = fetch_bytes(public_base, "/")
            creator, creator_preview = verify_public_large_responses(public_base)
            workflows = fetch_json(public_base, "/api/workflows")
            names = {str(item.get("name") or "") for item in workflows if isinstance(item, dict)}
            if b"/api/workflow-generate" not in realism or b"/realism" not in home:
                raise RuntimeError("public route markers missing")
            if not all(marker in creator for marker in (
                b"retro_manga_luxury", b"jt_style321_v1", b"style-retro-manga-luxury.webp",
                b"genApiBtn", b"gpt-image-2.5-flare", "API结果".encode("utf-8"),
            )):
                raise RuntimeError("public creator style/API markers missing")
            expected_preview = (BASE / "static" / "previews" / "style-retro-manga-luxury.webp").read_bytes()
            if creator_preview != expected_preview:
                raise RuntimeError("public creator preview mismatch")
            if not set(TARGET_WORKFLOW_NAMES).issubset(names):
                raise RuntimeError("public workflow list missing target workflows")
            if not set(UPLOADED_WORKFLOW_NAMES.values()).issubset(names):
                raise RuntimeError("public workflow list missing uploaded workflows")
            install_watchdog_units(client)
            write_transaction_phase(client, transaction, "committed")
            cleanup_release_transaction(client, transaction)
            print("LIVE", json.dumps(live, ensure_ascii=False))
            print("COMFY_DIAGNOSTIC", json.dumps(health, ensure_ascii=False))
            print("PUBLIC_MARKERS_OK")
        except Exception:
            command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer || true")
            command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")
            command(client, "sudo systemctl mask --runtime comfy-panel-watchdog.service || true")
            try:
                write_transaction_phase(client, transaction, "rolling-back")
                rollback_release(client, sftp, remote_paths, transaction, public_base=public_base)
            except Exception:
                # An uncertain rollback must remain stopped; restoring an active
                # watchdog could restart a mixed release.
                rollback_uncertain = True
                write_transaction_phase(client, transaction, "rollback-failed")
                raise
            else:
                try:
                    restore_watchdog_state(client, watchdog_state)
                    write_transaction_phase(client, transaction, "rolled-back")
                    cleanup_release_transaction(client, transaction)
                except Exception:
                    rollback_uncertain = True
                    write_transaction_phase(client, transaction, "rollback-failed")
                    raise
            raise
    finally:
        if sftp is not None:
            sftp.close()
        if lock_acquired and not rollback_uncertain:
            release_release_lock(client, transaction)
        client.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed realism release")
    parser.add_argument("--execute", action="store_true", help="allow remote mutation after all gates pass")
    parser.add_argument(
        "--allow-unauthenticated-public", action="store_true",
        help="explicitly accept the current public no-auth risk for this release",
    )
    parser.add_argument("--public-base", default=PUBLIC_BASE)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    server_source = (BASE / "server.py").read_text(encoding="utf-8")
    decision = preflight_decision(
        config, server_source,
        execute=args.execute,
        allow_unauthenticated_public=args.allow_unauthenticated_public,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if not decision["ready"]:
        return 2
    e2e_errors = validate_e2e_manifest(config)
    if e2e_errors:
        print(json.dumps({"e2e_errors": e2e_errors}, ensure_ascii=False, indent=2))
        return 2
    require_clean_git()
    run_release_tests()
    files = release_files()
    deploy(files, public_base=args.public_base)
    print("REALISM_RELEASE_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
