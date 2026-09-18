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
import io
import json
import pathlib
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from PIL import Image, ImageStat

BASE = pathlib.Path(__file__).resolve().parents[1]
E2E_MANIFEST = BASE / "audit" / "private_realism_workflows" / "e2e_manifest.json"
SCAIL_E2E_MANIFEST = BASE / "audit" / "scail2_video_e2e.json"
RETRO_CLOUD_E2E_MANIFEST = BASE / "audit" / "retro_manga_panel_e2e_cloud_w04.json"
DREAMAPI_E2E_MANIFEST = BASE / "audit" / "dreamapi_creator_live_e2e.json"
DREAMAPI_SIDEBAR_E2E_MANIFEST = BASE / "audit" / "dreamapi_sidebar_long_prompt_e2e.json"
DREAMAPI_MIGRATION_E2E_MANIFEST = BASE / "audit" / "dreamapi_migration_20260914" / "verification.json"
NEW_STYLE_E2E_MANIFEST = BASE / "audit" / "style221_222_panel_e2e_20260913.json"
UPLOADED_WORKFLOW_LIVE_SCHEMA_MANIFEST = BASE / "audit" / "uploaded_workflows_live_schema_20260912.json"
UPLOADED_WORKFLOW_E2E_MANIFEST = BASE / "audit" / "uploaded_workflows_live_e2e_20260912.json"
REMOTE_ROOT = "/home/admin/comfy-panel"
PUBLIC_BASE = "http://8.210.125.65:8189"
RELEASE_LOCK_DIR = REMOTE_ROOT + "/.release.lock"
RELEASE_TRANSACTIONS_DIR = REMOTE_ROOT + "/.release-transactions"
WATCHDOG_SERVICE_UNIT = "/etc/systemd/system/comfy-panel-watchdog.service"
WATCHDOG_TIMER_UNIT = "/etc/systemd/system/comfy-panel-watchdog.timer"
WATCHDOG_EXECUTABLE = "/usr/local/libexec/comfy-panel-watchdog.py"
RELEASE_TOKEN_ENV_DIR = "/etc/comfy-panel"
RELEASE_TOKEN_ENV_FILE = RELEASE_TOKEN_ENV_DIR + "/release.env"
RELEASE_DRAIN_DROPIN_DIR = "/etc/systemd/system/comfy-panel.service.d"
RELEASE_DRAIN_DROPIN_FILE = RELEASE_DRAIN_DROPIN_DIR + "/90-release-token.conf"
RELEASE_START_DRAIN_DROPIN_FILE = RELEASE_DRAIN_DROPIN_DIR + "/99-release-draining.conf"
RELEASE_DRAIN_DROPIN_BYTES = (
    "[Service]\n"
    f"EnvironmentFile={RELEASE_TOKEN_ENV_FILE}\n"
).encode("ascii")
RELEASE_START_DRAIN_DROPIN_BYTES = (
    "[Service]\n"
    "Environment=PANEL_RELEASE_DRAIN_ON_START=1\n"
).encode("ascii")
BOOTSTRAP_FENCE_NAME = "comfy_panel_release_fence"
BOOTSTRAP_FENCE_CONFIG = "/etc/systemd/system/comfy-panel-bootstrap-fence.nft"
BOOTSTRAP_FENCE_UNIT_NAME = "comfy-panel-bootstrap-fence.service"
BOOTSTRAP_FENCE_UNIT = "/etc/systemd/system/" + BOOTSTRAP_FENCE_UNIT_NAME
BOOTSTRAP_FENCE_ENABLE_LINK = (
    "/etc/systemd/system/comfy-panel.service.requires/" + BOOTSTRAP_FENCE_UNIT_NAME
)
BOOTSTRAP_FENCE_COMMENT = "comfy-panel bootstrap release admission fence"
BOOTSTRAP_FENCE_CONFIG_BYTES = (
    f"table inet {BOOTSTRAP_FENCE_NAME} {{\n"
    "    chain input {\n"
    "        type filter hook input priority -300; policy accept;\n"
    f"        iifname != \"lo\" tcp dport 8189 reject with tcp reset comment \"{BOOTSTRAP_FENCE_COMMENT}\"\n"
    "    }\n"
    "}\n"
).encode("ascii")
BOOTSTRAP_FENCE_UNIT_BYTES = (
    "[Unit]\n"
    "Description=Comfy Panel bootstrap admission fence\n"
    "DefaultDependencies=no\n"
    "After=network-pre.target nftables.service firewalld.service ufw.service\n"
    "Before=comfy-panel.service\n"
    "\n"
    "[Service]\n"
    "Type=oneshot\n"
    "ExecStart=/bin/sh -ec '"
    f"/usr/sbin/nft list table inet {BOOTSTRAP_FENCE_NAME} >/dev/null 2>&1 || "
    f"/usr/sbin/nft -f {BOOTSTRAP_FENCE_CONFIG}'\n"
    "ExecStop=/bin/sh -ec '"
    f"/usr/sbin/nft list table inet {BOOTSTRAP_FENCE_NAME} >/dev/null 2>&1 && "
    f"/usr/sbin/nft delete table inet {BOOTSTRAP_FENCE_NAME} || :'\n"
    "RemainAfterExit=yes\n"
    "\n"
    "[Install]\n"
    "RequiredBy=comfy-panel.service\n"
).encode("ascii")
SSH_HOST_KEY_SHA256 = "SHA256:TBBAqO1joLOjtttAHJaGdmYYolwwvpkDJaFXGqKEgWA"
DEPLOY_SSH_KEY_PATH = BASE / "tools" / "id_ed25519"
SSH_KEEPALIVE_INTERVAL = 15
PUBLIC_LARGE_VERIFY_TIMEOUT = 15 * 60
PUBLIC_RESPONSE_MAX_BYTES = 16 * 1024 * 1024
PUBLIC_GZIP_WIRE_OVERHEAD = 64 * 1024
IDLE_STABILITY_CHECKS = 3
IDLE_STABILITY_INTERVAL = 1.0
MIN_SCRIPT_CONTRACTS = 55
MIN_PYTEST_FILES = 40
RELEASE_TEST_INVENTORY_SHA256 = "c6b4f35cc3114a4090a53852b31ff60ac6f536828e30202dfbaa7dad72719a24"
DREAMAPI_CONTRACT_SHA256 = "d2e692e229a0525590fbbc5ffc4f466faebe70675278d263a44bfd0dffc6f0fa"
HISTORICAL_DREAMAPI_CONTRACT_SHA256 = "665d283bd420f76f031d9530f1d757f022d6cc16a5c9e9bc315e4966da797959"
DREAMAPI_NATIVE_MANIFEST = BASE / "audit" / "dreamapi_native_20260918" / "verification.json"
# Set only after the single authorized native canary is collected and reviewed.
DREAMAPI_NATIVE_EVIDENCE_SHA256 = "f211e5f1c022b8b5d3374c1a1fc5013706529dabb993dbf9c7d3388b4c84a0e7"
DREAMAPI_TESTED_RELEASE_COMMIT = "f7c179871747355d11cb5f2789f561a256f671d5"
DREAMAPI_RUNTIME_PAYLOAD_FORMAT = "framed-v1"
DREAMAPI_RUNTIME_PAYLOAD_FILES = (
    "comfy_watchdog.py",
    "server.py",
    "static/index.html",
    "static/promptgen.html",
    "tools/start_comfy_watchdog.ps1",
)
NATIVE_RUNTIME_PAYLOAD_FILES = (*DREAMAPI_RUNTIME_PAYLOAD_FILES, "config.json",
    "static/video.html", "static/realism.html",
    *("static/" + path.name for path in sorted((BASE / "static").glob("style-configs.*.json"))))
DREAMAPI_RUNTIME_PAYLOAD_SHA256 = "631f0a5cd36b648165956fd817d79fa66ba83934746da0bd7ed7c207cbec60f0"
DREAMAPI_MIN_VISIBLE_RGB_STDDEV = 2.0
DREAMAPI_PRIVATE_NORMALIZED_KEYS = {
    "api_response_id",
    "api_key",
    "authorization",
    "password",
    "cookie",
    "access_token",
    "refresh_token",
    "bearer_token",
    "secret",
}
DREAMAPI_RELEASE_IDENTITY_EVIDENCE = {
    "method": "formal release transaction, byte hashes, and process timeline",
    "attestation_scope": "operational audit evidence, not job-self-attested or provider-signed",
    "transaction_id": "20260914T121318Z-30c3e020b7104b1b8e4645fe8b48e8ea",
    "phase": "committed",
    "phase_mtime": "2026-09-14T20:16:43+08:00",
    "completed_mtime": "2026-09-14T20:16:44+08:00",
    "server_service": {
        "invocation_id": "6b002a3adfca47329e60abbed99b4199",
        "active_since": "2026-09-14T20:16:19+08:00",
        "restart_count": 0,
    },
    "remote_sha256": {
        "server.py": "0f868fdf1a4e0d37b087dc7e0d9f3a611160a37c476e20243ad66094e81ba9f8",
        "static/index.html": "a3a8f5a6b8e5aba7648ebc6a3c07b1183f581761046348610a4857191791ec56",
        "static/promptgen.html": "a3a8f5a6b8e5aba7648ebc6a3c07b1183f581761046348610a4857191791ec56",
    },
    "workstation_watchdog": {
        "process_id": 26924,
        "active_since": "2026-09-14T18:17:05.129+08:00",
        "file_sha256": "855c283adc8f21a0ac1a61c3ec68d1d31a73c539068623dba803bf1aea968ffa",
        "launcher_sha256": "95bcaf1130313b462d2681a7d0758970d33a5e4c83267e2dd4f2a0e741814bae",
        "dreamapi_contract_sha256": HISTORICAL_DREAMAPI_CONTRACT_SHA256,
        "dreamapi_uncertainty_fence": False,
    },
    "first_job_created_at": "2026-09-14T20:19:18.830+08:00",
    "last_job_created_at": "2026-09-14T20:20:28.230+08:00",
}
KNOWN_BASELINE_SCRIPT_FAILURES = {}
WATCHDOG_STATE_KEYS = {
    "service_exists", "service_b64", "service_mode",
    "timer_exists", "timer_b64", "timer_mode",
    "executable_exists", "executable_b64", "executable_mode",
    "service_active", "service_enabled", "timer_enabled", "timer_active",
}
WATCHDOG_RESTORABLE_ACTIVITY = {"active", "inactive"}
WATCHDOG_RESTORABLE_ENABLEMENT = {
    "enabled", "enabled-runtime", "disabled", "static", "masked", "masked-runtime",
    "not-found",
}


class WatchdogRestoreUncertain(RuntimeError):
    """Raised when a pre-swap watchdog mutation cannot be verified as restored."""


class ReleaseBusyError(RuntimeError):
    """Raised when an atomic drain observes active generation work."""


class ReleaseDrainContractError(RuntimeError):
    """Raised when the running service lacks mandatory drain configuration."""


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
    "h3_edit_n": "da7daf1163aa42e8da1e10bdf6efff18c18f1161a4b9276ad1a110de74e01657",
    "h3_edit_t3": "9c121960605a541ed5c722ba2ce1af80716ef3ccdc457f18d7f67a6622080cb5",
    "h3_edit_remove": "57358745e4100d8516b209ffe950d82ffa27e6282625edd61929e01444d2f0b0",
    "qwen_image_edit_zip": "5adf6399af4a2e6e652600420c69c2914ab8f950802d883b570c77ed3f435151",
    "wan_action_stabilized": "dcf2e7ce6cd2e160c4aa12b733a9e24134325ffa12ab6d5c3a1f697e3d0d6fb3",
    "scail2_action_replace": "73fabac4e15bf7a1ddeaa9ee495d7ddc28369831f2f7741f5525c0901e02468b",
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
    *("static/" + path.name for path in sorted((BASE / "static").glob("style-configs.*.json"))),
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


def validate_dreamapi_sidebar_e2e_manifest():
    try:
        record = json.loads(DREAMAPI_SIDEBAR_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"DreamAPI sidebar E2E manifest unreadable: {error}"]
    artifact = record.get("artifact") or {}
    visual = record.get("visual_review") or {}
    rejected = record.get("preflight_rejection") or {}
    errors = []
    if (record.get("verification") != "PASS" or record.get("submit_attempts") != 1
            or record.get("status") != "done" or record.get("provider_status") != "API_DONE"
            or record.get("api_model") != "gpt-image-2.5-flare"
            or record.get("requested_quality") != "low" or record.get("upstream_quality") != "medium"
            or record.get("quality_override_disclosed") is not True
            or record.get("panel_prompt_chars") != 3690 or record.get("prompt_compacted") is not True
            or record.get("upstream_positive_chars") != 378 or record.get("result_count") != 1):
        errors.append("DreamAPI sidebar E2E job contract invalid")
    if (rejected.get("http_status") != 400 or rejected.get("job_created") is not False
            or rejected.get("upstream_called") is not False):
        errors.append("DreamAPI sidebar preflight rejection evidence invalid")
    expected_hash = "3596874eed855b3187de9a9519c4713f993c388c2cc9b1afeea6fd772afcb271"
    path = DREAMAPI_SIDEBAR_E2E_MANIFEST.parent / str(artifact.get("file") or "")
    try:
        raw = path.read_bytes()
    except Exception:
        errors.append("DreamAPI sidebar E2E artifact missing")
    else:
        if (artifact.get("format") != "PNG" or artifact.get("width") != 768
                or artifact.get("height") != 1024 or artifact.get("bytes") != len(raw)
                or artifact.get("sha256") != expected_hash
                or hashlib.sha256(raw).hexdigest() != expected_hash
                or not raw.startswith(b"\x89PNG\r\n\x1a\n")):
            errors.append("DreamAPI sidebar E2E artifact invalid")
    if (visual.get("status") != "PASS" or visual.get("complete_subject") is not True
            or visual.get("visible_text_logo_watermark") is not False
            or visual.get("traditional_media_style_visible") is not True):
        errors.append("DreamAPI sidebar E2E visual review invalid")
    return errors


def framed_v1_payload_sha256(payloads):
    """Hash named bytes with unambiguous big-endian length framing."""
    if not isinstance(payloads, dict) or not payloads:
        raise ValueError("framed payloads must be a non-empty mapping")
    digest = hashlib.sha256()
    for relative in sorted(payloads):
        data = payloads[relative]
        if not isinstance(relative, str) or not isinstance(data, bytes):
            raise TypeError("framed payload paths must be strings and values must be bytes")
        path_bytes = relative.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def git_runtime_payload_sha256(commit, repository=None, files=None):
    repository = pathlib.Path(repository or BASE)
    if not re.fullmatch(r"[0-9a-f]{40}", str(commit or "")):
        raise RuntimeError("DreamAPI tested release commit must be a full lowercase SHA-1")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=repository,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if exists.returncode:
        raise RuntimeError("DreamAPI tested release commit does not exist")
    payloads = {}
    for relative in (DREAMAPI_RUNTIME_PAYLOAD_FILES if files is None else files):
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative}"], cwd=repository,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError(f"DreamAPI runtime file missing from commit: {relative}")
        payloads[relative] = bytes(result.stdout)
    return framed_v1_payload_sha256(payloads)


def validate_dreamapi_runtime_payload(record, repository=None, require_current=True):
    repository = pathlib.Path(repository or BASE)
    errors = []
    tested_commit = record.get("tested_release_commit")
    expected_payload = {
        "format": DREAMAPI_RUNTIME_PAYLOAD_FORMAT,
        "files": list(DREAMAPI_RUNTIME_PAYLOAD_FILES),
        "sha256": DREAMAPI_RUNTIME_PAYLOAD_SHA256,
    }
    if tested_commit != DREAMAPI_TESTED_RELEASE_COMMIT:
        errors.append("DreamAPI tested release commit pin invalid")
    if (record.get("runtime_payload") or {}) != expected_payload:
        errors.append("DreamAPI runtime payload metadata invalid")

    try:
        candidate_digest = git_runtime_payload_sha256(tested_commit, repository)
    except Exception as error:
        errors.append(f"DreamAPI tested release commit invalid: {error}")
        candidate_digest = None
    if not require_current:
        if candidate_digest != DREAMAPI_RUNTIME_PAYLOAD_SHA256:
            errors.append("DreamAPI historical runtime digest invalid")
        return errors
    try:
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        head = head_result.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise RuntimeError("HEAD is not a full commit SHA-1")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(tested_commit), head], cwd=repository,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if ancestor.returncode == 1:
            errors.append("DreamAPI tested release commit is not an ancestor of HEAD")
        elif ancestor.returncode:
            raise RuntimeError("unable to verify tested release ancestry")
        head_digest = git_runtime_payload_sha256(head, repository)
    except Exception as error:
        errors.append(f"DreamAPI current release commit invalid: {error}")
        head_digest = None

    workspace = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *DREAMAPI_RUNTIME_PAYLOAD_FILES],
        cwd=repository, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    if workspace.returncode == 1:
        errors.append("DreamAPI runtime payload differs between HEAD and workspace")
    elif workspace.returncode:
        errors.append("DreamAPI workspace runtime payload could not be verified")

    recorded_digest = (record.get("runtime_payload") or {}).get("sha256")
    if candidate_digest is not None and not hmac.compare_digest(
            candidate_digest, DREAMAPI_RUNTIME_PAYLOAD_SHA256):
        errors.append("DreamAPI tested release runtime payload digest invalid")
    if head_digest is not None and candidate_digest is not None and not hmac.compare_digest(
            head_digest, candidate_digest):
        errors.append("DreamAPI runtime payload changed after tested release")
    if candidate_digest is not None and not hmac.compare_digest(
            candidate_digest, str(recorded_digest or "")):
        errors.append("DreamAPI recorded runtime payload digest invalid")
    return errors


def normalize_evidence_key(value):
    with_acronym_boundaries = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(value))
    with_word_boundaries = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])", "_", with_acronym_boundaries,
    )
    return re.sub(r"[^a-z0-9]+", "_", with_word_boundaries.lower()).strip("_")


def find_dreamapi_private_evidence(value, path="$"):
    findings = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = normalize_evidence_key(key)
            child_path = f"{path}.{key}"
            if normalized in DREAMAPI_PRIVATE_NORMALIZED_KEYS:
                findings.append(f"forbidden key at {child_path}")
            findings.extend(find_dreamapi_private_evidence(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_dreamapi_private_evidence(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized = value.lstrip().lower()
        if normalized.startswith(("bearer", "sk-", "resp_")):
            findings.append(f"forbidden value prefix at {path}")
    return findings


def validate_png_artifact(path, expected_bytes, expected_sha256, expected_size):
    artifact_path = pathlib.Path(path)
    try:
        if artifact_path.stat().st_size != expected_bytes:
            return ["artifact bytes invalid"]
        raw = artifact_path.read_bytes()
    except Exception:
        return ["artifact missing"]
    if (len(raw) != expected_bytes
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        return ["artifact bytes invalid"]
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG" or image.size != expected_size:
                return ["PNG format or dimensions invalid"]
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            rgba = image.convert("RGBA")
            visible = Image.alpha_composite(
                Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba,
            ).convert("RGB")
            if max(ImageStat.Stat(visible).stddev) < DREAMAPI_MIN_VISIBLE_RGB_STDDEV:
                return ["PNG visible content variance too low"]
    except Exception:
        return ["PNG decode invalid"]
    return []


def validate_dreamapi_migration_e2e_manifest():
    try:
        record = json.loads(DREAMAPI_MIGRATION_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"DreamAPI migration E2E manifest unreadable: {error}"]
    errors = []
    if find_dreamapi_private_evidence(record):
        errors.append("DreamAPI migration manifest contains private response or credential data")
    standard_instructions = (
        "You are an image generation dispatcher. Call the provided image_generation "
        "tool exactly once. Do not return or rewrite a prompt. Return no text."
    )
    strict_instructions = standard_instructions.replace(". Call the", ". You must call the", 1)
    expected_contract = {
        "method": "POST", "base_url": "https://dreamapi.club", "path": "/responses",
        "text_model": "gpt-5.6-luna",
        "instruction_profiles": {
            "standard": standard_instructions, "strict": strict_instructions,
        },
        "instruction_profile_by_model": {
            "gpt-image-2": "standard", "gpt-image-2.5-flare": "standard",
            "gpt-image-2.5-sunburst": "strict",
        },
        "stream": False, "tool_count": 1, "tool_type": "image_generation",
        "top_level_tool_choice_present": False,
        "client_pixel_dimensions_present": False,
        "provider_size_mapped_from_ratio": True,
        "action_by_model": {
            "gpt-image-2": "omitted", "gpt-image-2.5-flare": "generate",
            "gpt-image-2.5-sunburst": "generate",
        },
    }
    if (record.get("verification") != "PASS" or record.get("provider") != "DreamAPI"
            or record.get("evidence_scope")
            != "single-release production E2E for all supported DreamAPI image models"
            or record.get("source_project_version") != "1.0.3"
            or record.get("source_project_checks_passed") != 8
            or record.get("unified_release_e2e") is not True
            or record.get("tested_release_commit") != DREAMAPI_TESTED_RELEASE_COMMIT):
        errors.append("DreamAPI migration E2E identity invalid")
    # Archived Responses evidence remains verifiable, but is not native release evidence.
    errors.extend(validate_dreamapi_runtime_payload(record, require_current=False))
    release_identity = record.get("release_identity_evidence") or {}
    if release_identity != DREAMAPI_RELEASE_IDENTITY_EVIDENCE:
        errors.append("DreamAPI release identity evidence invalid")
    if (record.get("request_contract") or {}) != expected_contract:
        errors.append("DreamAPI migration request contract invalid")
    if (record.get("credential_handling") or {}) != {
        "browser_received_key": False, "repository_contains_key": False,
        "server_secret_environment_only": True,
    }:
        errors.append("DreamAPI migration credential handling invalid")
    try:
        verified_at = datetime.datetime.fromisoformat(str(record.get("verified_at") or ""))
        if verified_at.tzinfo is None:
            raise ValueError("timezone missing")
    except Exception:
        errors.append("DreamAPI migration verification timestamp invalid")

    jobs = record.get("production_jobs") or {}
    expected_jobs = {
        "gpt-image-2": {
            "job_id": "36aa8e4c8776",
            "client_request_id": "migration-e2e-f7c1798-gpt-image-2",
            "created_at": "2026-09-14T20:19:18.830+08:00",
            "profile": "standard", "action": "omitted", "elapsed_seconds": 28.2,
            "artifact_file": "gpt-image-2.png", "artifact_bytes": 904227,
            "artifact_sha256": "8d3b69ebc3d1cfe5b86b314673a02d04b4105e93d31998dcc0c33b580e239c09",
        },
        "gpt-image-2.5-flare": {
            "job_id": "4637a3f0b1f0",
            "client_request_id": "migration-e2e-f7c1798-gpt-image-2_5-flare",
            "created_at": "2026-09-14T20:19:52.301+08:00",
            "profile": "standard", "action": "generate", "elapsed_seconds": 26.2,
            "artifact_file": "gpt-image-2_5-flare.png", "artifact_bytes": 970977,
            "artifact_sha256": "e6c9af8ab362be1a56b6dde43707ce03479c4ef4b679d9419df4189a7e72d815",
        },
        "gpt-image-2.5-sunburst": {
            "job_id": "622a20c8e528",
            "client_request_id": "migration-e2e-f7c1798-gpt-image-2_5-sunburst",
            "created_at": "2026-09-14T20:20:28.230+08:00",
            "profile": "strict", "action": "generate", "elapsed_seconds": 25.2,
            "artifact_file": "gpt-image-2_5-sunburst.png", "artifact_bytes": 687943,
            "artifact_sha256": "fd387e5927defd65f714a8756efebdb4695d141b708520ef41d33ab4c25d0247",
        },
    }
    if set(jobs) != set(expected_jobs):
        errors.append("DreamAPI migration model coverage invalid")
    created_at_values = [
        job.get("created_at") for job in jobs.values() if isinstance(job, dict)
    ]
    if (len(created_at_values) != len(expected_jobs)
            or any(not isinstance(value, str) for value in created_at_values)
            or release_identity.get("first_job_created_at") != min(created_at_values)
            or release_identity.get("last_job_created_at") != max(created_at_values)):
        errors.append("DreamAPI release identity job timeline invalid")
    production_job_ids = []
    client_request_ids = []
    for model, expected in expected_jobs.items():
        job = jobs.get(model) or {}
        artifact = job.get("artifact") or {}
        visual = job.get("visual_review") or {}
        production_job_ids.append(job.get("job_id"))
        client_request_ids.append(job.get("client_request_id"))
        try:
            created_at = datetime.datetime.fromisoformat(str(job.get("created_at") or ""))
            if created_at.tzinfo is None:
                raise ValueError("timezone missing")
        except Exception:
            errors.append(f"DreamAPI migration timestamp invalid: {model}")
        if (job.get("job_id") != expected["job_id"]
                or job.get("client_request_id") != expected["client_request_id"]
                or job.get("created_at") != expected["created_at"]
                or job.get("contract_commit") != DREAMAPI_TESTED_RELEASE_COMMIT
                or job.get("instruction_profile") != expected["profile"]
                or job.get("api_model") != model
                or job.get("api_dispatch_profile") != expected["profile"]
                or job.get("api_action_mode") != expected["action"]
                or job.get("dreamapi_contract_sha256") != HISTORICAL_DREAMAPI_CONTRACT_SHA256
                or job.get("status") != "done"
                or job.get("provider_status") != "API_DONE" or job.get("generation_backend") != "api"
                or job.get("submit_attempts") != 1 or job.get("history_occurrences") != 1
                or job.get("requested_quality") != "low" or job.get("requested_fit") != "contain"
                or job.get("requested_ratio") != "1:1"
                or job.get("upstream_model_reported") != "unknown"
                or job.get("upstream_quality_reported") != "low"
                or job.get("upstream_size_reported") != "1254x1254"
                or job.get("source_size") != "1254x1254" or job.get("output_size") != "1024x1024"
                or job.get("elapsed_seconds") != expected["elapsed_seconds"]
                or job.get("api_response_id_present") is not True
                or "api_response_id" in job):
            errors.append(f"DreamAPI migration job contract invalid: {model}")
        if (artifact.get("file") != expected["artifact_file"] or artifact.get("format") != "PNG"
                or artifact.get("width") != 1024 or artifact.get("height") != 1024
                or artifact.get("bytes") != expected["artifact_bytes"]
                or artifact.get("sha256") != expected["artifact_sha256"]):
            errors.append(f"DreamAPI migration artifact metadata invalid: {model}")
        artifact_path = DREAMAPI_MIGRATION_E2E_MANIFEST.parent / expected["artifact_file"]
        for artifact_error in validate_png_artifact(
                artifact_path, expected["artifact_bytes"], expected["artifact_sha256"], (1024, 1024)):
            errors.append(f"DreamAPI migration {artifact_error}: {model}")
        if (visual.get("status") != "PASS" or visual.get("not_blank_or_corrupt") is not True
                or visual.get("complete_subject") is not True
                or visual.get("visible_text_logo_watermark") is not False
                or visual.get("obvious_crop_problem") is not False):
            errors.append(f"DreamAPI migration visual review invalid: {model}")

    failures = record.get("contrastive_failures") or {}
    expected_failures = {
        "sunburst_with_standard_instruction": {
            "job_id": "183417c847fd", "model": "gpt-image-2.5-sunburst",
            "instruction_profile": "standard",
            "error": "DreamAPI returned no completed image",
        },
        "image_2_with_strict_instruction": {
            "job_id": "958806f9e3e0", "model": "gpt-image-2",
            "instruction_profile": "strict",
            "error": "DreamAPI HTTP 502: Upstream request failed",
        },
    }
    if set(failures) != {*expected_failures, "interpretation"}:
        errors.append("DreamAPI migration contrastive failure coverage invalid")
    failure_job_ids = []
    for name, expected in expected_failures.items():
        failure = failures.get(name) or {}
        failure_job_ids.append(failure.get("job_id"))
        try:
            failed_at = datetime.datetime.fromisoformat(str(failure.get("created_at") or ""))
            if failed_at.tzinfo is None:
                raise ValueError("timezone missing")
        except Exception:
            errors.append(f"DreamAPI migration failure timestamp invalid: {name}")
        if (failure.get("job_id") != expected["job_id"]
                or failure.get("model") != expected["model"]
                or failure.get("instruction_profile") != expected["instruction_profile"]
                or failure.get("status") != "error"
                or failure.get("provider_status") != "API_ERROR"
                or failure.get("submit_attempts") != 1
                or failure.get("error") != expected["error"]):
            errors.append(f"DreamAPI migration contrastive failure invalid: {name}")
    all_job_ids = production_job_ids + failure_job_ids
    if (any(not isinstance(value, str) or not value for value in all_job_ids)
            or len(set(all_job_ids)) != len(all_job_ids)):
        errors.append("DreamAPI migration job IDs are not unique")
    if (any(not isinstance(value, str) or not value for value in client_request_ids)
            or len(set(client_request_ids)) != len(client_request_ids)):
        errors.append("DreamAPI migration client request IDs are not unique")
    interpretation = str(failures.get("interpretation") or "")
    if ("conservative per-model compatibility mapping" not in interpretation
            or "neither single failure proves deterministic provider causality" not in interpretation.lower()):
        errors.append("DreamAPI migration contrastive interpretation invalid")
    return errors


def validate_new_style_e2e_manifest():
    try:
        record = json.loads(NEW_STYLE_E2E_MANIFEST.read_text(encoding="utf-8"))
    except Exception as error:
        return [f"new style E2E manifest unreadable: {error}"]
    expected = {
        "style221": ("zxqelun", "c484a46f6127eab36d2fafb29dace2c13e3bd0a0f3fa9b64db3dd7090be57e3f", "5", "6b61ec6c4c8a", "5cf555e0888c1ffcbe0b9ec560f2fe46ac42b6fc8a6c435ea8652bd0eaa1fd1a"),
        "style222": ("zxqavri", "7f5532a086450fa4f1fd8127e34f6dbfefacdb5b718bdf8209cf17d0e411e7e2", "3", "1d034dbcfdf2", "923542efa1963ba5dda30632e294dcf487f97a272b10d994f8e8ae04d4ebb0cf"),
    }
    rows = record.get("workflows") or {}
    errors = []
    if record.get("verification") != "PASS" or set(rows) != set(expected):
        return ["new style E2E identity invalid"]
    for style_id, (trigger, model_hash, coins, job_id, artifact_hash) in expected.items():
        row = rows.get(style_id) or {}
        if (row.get("trigger") != trigger or row.get("model_sha256") != model_hash
                or row.get("weight") != 0.4 or row.get("submit_attempts") != 1
                or row.get("job_id") != job_id or row.get("status") != "done"
                or row.get("provider_status") != "DONE" or row.get("rh_coins") != coins
                or row.get("result_count") != 1 or row.get("history_occurrences") != 1
                or row.get("artifact_sha256") != artifact_hash or row.get("png_signature") is not True):
            errors.append(f"new style E2E invalid: {style_id}")
    matrix = record.get("visual_matrix") or {}
    if matrix.get("local_three_seed_count") != 12 or "No new formal preview" not in str(matrix.get("preview_decision")):
        errors.append("new style visual matrix evidence invalid")
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


def require_clean_git(expected_head=None):
    result = subprocess.run(["git", "status", "--porcelain"], cwd=BASE, text=True,
                            capture_output=True, check=True)
    if result.stdout.strip():
        raise RuntimeError("git working tree is not clean; commit the reviewed release first")
    head_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BASE, text=True,
                                 capture_output=True, check=True)
    head = head_result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("unable to identify the reviewed release HEAD")
    if expected_head is not None and not hmac.compare_digest(head, str(expected_head)):
        raise RuntimeError("HEAD changed while release tests were running")
    return head


def classify_release_tests(test_dir=None):
    test_dir = pathlib.Path(test_dir or (BASE / "tests"))
    scripts = []
    pytest_files = []
    for path in sorted(test_dir.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_pytest_tests = any(
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"))
            or (isinstance(node, ast.ClassDef) and node.name.startswith("Test"))
            for node in tree.body
        )
        (pytest_files if has_pytest_tests else scripts).append(path)
    return scripts, pytest_files


def release_test_inventory_sha256(test_dir, scripts, pytest_files):
    root = pathlib.Path(test_dir or (BASE / "tests")).resolve()
    rows = []
    for lane, paths in (("script", scripts), ("pytest", pytest_files)):
        for path in paths:
            try:
                relative = pathlib.Path(path).resolve().relative_to(root).as_posix()
            except ValueError as error:
                raise RuntimeError(f"release test escapes test root: {path}") from error
            rows.append(f"{lane}:{relative}")
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def run_release_tests(test_dir=None):
    scripts, pytest_files = classify_release_tests(test_dir)
    if not scripts and not pytest_files:
        raise RuntimeError("no release tests discovered; refusing an untested release")
    if not scripts or not pytest_files:
        missing = "script contracts" if not scripts else "pytest files"
        raise RuntimeError(f"release test lane is empty ({missing}); refusing release")
    if test_dir is None and (len(scripts) < MIN_SCRIPT_CONTRACTS
                             or len(pytest_files) < MIN_PYTEST_FILES):
        raise RuntimeError(
            "release test inventory shrank below the reviewed baseline: "
            f"scripts={len(scripts)}/{MIN_SCRIPT_CONTRACTS}, "
            f"pytest={len(pytest_files)}/{MIN_PYTEST_FILES}"
        )
    if test_dir is None:
        inventory_digest = release_test_inventory_sha256(None, scripts, pytest_files)
        if not hmac.compare_digest(inventory_digest, RELEASE_TEST_INVENTORY_SHA256):
            raise RuntimeError(
                "release test inventory differs from the reviewed baseline; "
                "review the test-set change before updating RELEASE_TEST_INVENTORY_SHA256"
            )
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
    if definitions != 1 or calls != 4:
        errors.append("not all public upload routes are quota guarded")
    if ("_upload_usage_lock = threading.Lock()" not in server_source
            or "load_upload_usage()" not in server_source
            or "Retry-After" not in server_source):
        errors.append("public upload quota persistence or response missing")
    return errors


def validate_public_billable_quota(server_source):
    # The owner explicitly removed website hourly/daily generation caps.
    # Keep registration/ownership safeguards; do not silently restore quotas.
    removed_caps = {"BILLABLE_GLOBAL_HOURLY_LIMIT", "BILLABLE_GLOBAL_DAILY_LIMIT",
                    "BILLABLE_SESSION_HOURLY_LIMIT"}
    try:
        tree = ast.parse(server_source)
    except SyntaxError as error:
        return [f"server source cannot be parsed: {error}"]
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in removed_caps:
            errors.append(f"owner-removed billable cap reintroduced: {node.id}")
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
        errors.append("not all public billable routes register tasks")
    for marker in ("_billable_quota_lock", "idempotency_decision", "_submit_locks", "billable_quota_recorded"):
        if marker not in server_source:
            errors.append(f"missing public billable quota control: {marker}")
    return errors


def only_public_error_changed(before, after):
    """Byte-identical runtime outside the existing undecorated error renderer."""
    def remove_renderer(source):
        nodes = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "public_job_error"]
        if len(nodes) != 1 or nodes[0].decorator_list:
            raise ValueError("invalid renderer")
        node = nodes[0]
        lines = source.splitlines(keepends=True)
        return "".join(lines[:node.lineno - 1] + lines[node.end_lineno:])
    try:
        return before != after and remove_renderer(before) == remove_renderer(after)
    except (SyntaxError, ValueError):
        return False


def only_error_and_admission_changed(before, after):
    """Limit the owner-approved cap removal to admission and error rendering."""
    functions = {"public_job_error", "billable_quota_status", "register_billable_job"}
    constants = {"BILLABLE_GLOBAL_HOURLY_LIMIT", "BILLABLE_GLOBAL_DAILY_LIMIT",
                 "BILLABLE_SESSION_HOURLY_LIMIT"}
    def remainder(source):
        tree = ast.parse(source)
        kept = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in functions:
                if node.decorator_list:
                    raise ValueError("decorated admission function")
                continue
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants):
                continue
            if isinstance(node, ast.ClassDef) and node.name == "Handler":
                methods = []
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name == "_billable_quota_rejection":
                        if method.decorator_list:
                            raise ValueError("decorated admission method")
                        continue
                    methods.append(method)
                node.body = methods
            kept.append(node)
        tree.body = kept
        return ast.dump(tree, include_attributes=False)
    try:
        return before != after and remainder(before) == remainder(after)
    except (SyntaxError, ValueError):
        return False


REVIEWED_UNCAPPED_RUNTIME_SHA256 = "9f2c9fdf6cb0a2b2d23cddc5dd7ac7fffae80a5ebd9b769d1de65cca678a5fd4"


def reviewed_error_presentation_patch(tested_commit, current_commit, current_digest):
    """Reviewed localization and owner-requested cap removal; no new image claim.

    Pin the complete resulting runtime AND prove every change is confined to
    error rendering/admission. Request/UI/transport changes need fresh evidence.
    """
    presentation_only = current_digest == "b9f32822ff5ceed60e6e18b3e244a91643b2856bfda81f97733a453e3c034e05"
    uncapped = current_digest == REVIEWED_UNCAPPED_RUNTIME_SHA256
    if not (presentation_only or uncapped):
        return False
    if tested_commit != "ff87b67c983b1bdf1bbd24bb82c8d1b70b72a83c":
        return False
    for path in NATIVE_RUNTIME_PAYLOAD_FILES:
        before = subprocess.check_output(["git", "show", f"{tested_commit}:{path}"], cwd=BASE)
        after = subprocess.check_output(["git", "show", f"{current_commit}:{path}"], cwd=BASE)
        if path == "server.py":
            comparison = only_error_and_admission_changed if uncapped else only_public_error_changed
            if not comparison(before.decode("utf-8"), after.decode("utf-8")):
                return False
        elif before != after:
            return False
    return True


def validate_native_dreamapi_evidence():
    """Require reviewed native-media evidence for the exact current runtime bytes."""
    try:
        raw = DREAMAPI_NATIVE_MANIFEST.read_bytes()
        if hashlib.sha256(raw).hexdigest() != DREAMAPI_NATIVE_EVIDENCE_SHA256:
            return ["native DreamAPI evidence is absent or not reviewed"]
        record = json.loads(raw)
    except Exception:
        return ["native DreamAPI evidence is absent or unreadable"]
    errors = []
    if find_dreamapi_private_evidence(record):
        errors.append("native DreamAPI evidence contains private data")
    if record.get("verification") != "PASS" or record.get("scope") != "production-loopback native Flare low 9:16 canary":
        errors.append("native DreamAPI verification identity invalid")
    try:
        commit = record["tested_release_commit"]
        payload = record["runtime_payload"]
        expected = git_runtime_payload_sha256(commit, files=NATIVE_RUNTIME_PAYLOAD_FILES)
        current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE, text=True).strip()
        current = git_runtime_payload_sha256(current_head, files=NATIVE_RUNTIME_PAYLOAD_FILES)
        unchanged_generation = current == expected or reviewed_error_presentation_patch(commit, current_head, current)
        if payload != {"format": "framed-v1", "files": list(NATIVE_RUNTIME_PAYLOAD_FILES), "sha256": expected} or not unchanged_generation:
            errors.append("native DreamAPI runtime payload drift")
        if subprocess.run(["git", "merge-base", "--is-ancestor", commit, current_head], cwd=BASE, capture_output=True).returncode:
            errors.append("native DreamAPI tested commit is not an ancestor")
        if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *NATIVE_RUNTIME_PAYLOAD_FILES], cwd=BASE, capture_output=True).returncode:
            errors.append("native DreamAPI workspace runtime drift")
    except Exception:
        errors.append("native DreamAPI runtime identity invalid")
    expected_request = {"method": "POST", "path": "/v1/images/generations",
                        "model": "gpt-image-2.5-flare", "quality": "low", "size": "864x1536", "n": 1, "output_format": "png"}
    if record.get("request_contract") != expected_request:
        errors.append("native DreamAPI request contract invalid")
    job = record.get("job") or {}
    required = {"status": "done", "provider_status": "API_DONE", "api_model": "gpt-image-2.5-flare",
                "api_quality": "low", "api_ratio": "9:16", "api_provider_size": "864x1536",
                "api_transport": "images", "api_action_mode": "direct", "width": 864, "height": 1536,
                "dreamapi_contract_sha256": DREAMAPI_CONTRACT_SHA256}
    if any(job.get(key) != value for key, value in required.items()):
        errors.append("native DreamAPI job contract invalid")
    if record.get("submit_attempts") != 1 or not re.fullmatch(r"[a-f0-9]{12}", str(job.get("id") or "")):
        errors.append("native DreamAPI submission evidence invalid")
    artifact = record.get("artifact") or {}
    if artifact.get("file") != "flare-low-9x16.png":
        errors.append("native DreamAPI artifact path invalid")
    else:
        errors.extend(validate_png_artifact(DREAMAPI_NATIVE_MANIFEST.parent / artifact["file"],
                                           artifact.get("bytes"), artifact.get("sha256"), (864, 1536)))
    if record.get("visual_review") != {"status": "PASS", "not_blank_or_corrupt": True, "complete_subject": True}:
        errors.append("native DreamAPI visual review missing")
    return errors


def preflight_decision(config, server_source, execute=False, allow_unauthenticated_public=False):
    config_result = validate_release_config(config)
    scail_errors = validate_scail_video_config(config) + validate_scail_e2e_manifest()
    uploaded_errors = validate_uploaded_workflow_config(config)
    uploaded_live_schema_errors = validate_uploaded_workflow_live_schema_manifest(config)
    uploaded_e2e_errors = validate_uploaded_workflow_e2e_manifest(config)
    dreamapi_e2e_errors = validate_dreamapi_e2e_manifest()
    dreamapi_sidebar_e2e_errors = validate_dreamapi_sidebar_e2e_manifest()
    dreamapi_migration_e2e_errors = validate_dreamapi_migration_e2e_manifest()
    native_dreamapi_errors = validate_native_dreamapi_evidence()
    new_style_e2e_errors = validate_new_style_e2e_manifest()
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
    if dreamapi_sidebar_e2e_errors:
        blockers.append("invalid DreamAPI sidebar E2E")
    if dreamapi_migration_e2e_errors:
        blockers.append("invalid DreamAPI migration E2E")
    if native_dreamapi_errors:
        blockers.append("invalid native DreamAPI E2E")
    if new_style_e2e_errors:
        blockers.append("invalid new style E2E")
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
        "dreamapi_sidebar_e2e_errors": dreamapi_sidebar_e2e_errors,
        "dreamapi_migration_e2e_errors": dreamapi_migration_e2e_errors,
        "native_dreamapi_e2e_errors": native_dreamapi_errors,
        "new_style_e2e_errors": new_style_e2e_errors,
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


def release_payloads_from_head(files, reviewed_head):
    """Materialize immutable release bytes from the exact tested commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", str(reviewed_head or "")):
        raise RuntimeError("invalid reviewed release HEAD")
    payloads = {}
    for local in files:
        try:
            relative = local.resolve().relative_to(BASE.resolve()).as_posix()
        except ValueError as error:
            raise RuntimeError(f"release file escapes repository: {local}") from error
        result = subprocess.run(
            ["git", "show", f"{reviewed_head}:{relative}"], cwd=BASE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError(f"release file is not present in reviewed HEAD: {relative}")
        data = bytes(result.stdout)
        lower = data.lower()
        if any(marker in lower for marker in (
                b"fixture_3in1", b"fixture-never-sent", b"realism_fixture")):
            raise RuntimeError(f"test fixture marker in reviewed release file: {relative}")
        payloads[local] = data
    if set(payloads) != set(files):
        raise RuntimeError("reviewed release payload set mismatch")
    return payloads


def command(client, text, timeout=240):
    _, stdout, stderr = client.exec_command(text, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    if code:
        raise RuntimeError(f"remote command failed ({code}): {err or out}")
    return out


def configure_ssh_transport(client):
    """Require one active SSH transport and keep it alive during long releases."""
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        raise RuntimeError("SSH transport is not active after authentication")
    transport.set_keepalive(SSH_KEEPALIVE_INTERVAL)
    return transport


def _bootstrap_fence_probe_source():
    return """import json,os,pathlib,shlex,stat,subprocess
name=FENCE_NAME;unit_name=UNIT_NAME
config=pathlib.Path(CONFIG_PATH);unit=pathlib.Path(UNIT_PATH);link=pathlib.Path(LINK_PATH)
expected_config=CONFIG_BYTES;expected_unit=UNIT_BYTES
def run(argv): return subprocess.run(argv,text=True,capture_output=True)
def show(prop):
    result=run(['systemctl','show','--property',prop,'--value',unit_name])
    return result.stdout.strip() if result.returncode==0 else ''
def panel_show(prop):
    result=run(['systemctl','show','--property',prop,'--value','comfy-panel.service'])
    return result.stdout.strip() if result.returncode==0 else ''
def file_exact(path,data,mode):
    if path.is_symlink() or not path.is_file(): return False
    info=path.stat()
    return info.st_uid==0 and info.st_gid==0 and stat.S_IMODE(info.st_mode)==mode and path.read_bytes()==data
tables_result=run(['/usr/sbin/nft','-j','list','tables'])
if tables_result.returncode: raise RuntimeError('cannot inspect nft tables')
tables=json.loads(tables_result.stdout).get('nftables',[])
table_present=any(row.get('table',{}).get('family')=='inet' and row.get('table',{}).get('name')==name for row in tables if isinstance(row,dict))
file_present=any(path.exists() or path.is_symlink() for path in (config,unit,link))
fragment=show('FragmentPath');active=run(['systemctl','is-active',unit_name]).stdout.strip();enabled=run(['systemctl','is-enabled',unit_name]).stdout.strip()
if not table_present and not file_present and not fragment and active!='active' and enabled!='enabled':
    print(json.dumps({'state':'absent'},separators=(',',':')));raise SystemExit(0)
if not file_exact(config,expected_config,0o600) or not file_exact(unit,expected_unit,0o644): raise RuntimeError('bootstrap fence file mismatch')
if not link.is_symlink() or pathlib.Path(os.path.realpath(link))!=unit: raise RuntimeError('bootstrap fence enable link mismatch')
if fragment!=str(unit) or shlex.split(show('DropInPaths')): raise RuntimeError('bootstrap fence systemd fragment mismatch')
if active!='active' or enabled!='enabled': raise RuntimeError('bootstrap fence systemd state mismatch')
before=set(shlex.split(show('Before')));after=set(shlex.split(show('After')))
if 'comfy-panel.service' not in before or not {'network-pre.target','nftables.service','firewalld.service','ufw.service'}<=after: raise RuntimeError('bootstrap fence ordering mismatch')
if unit_name not in set(shlex.split(panel_show('Requires'))): raise RuntimeError('bootstrap fence required dependency mismatch')
table_result=run(['/usr/sbin/nft','-j','list','table','inet',name])
if table_result.returncode: raise RuntimeError('bootstrap fence nft table missing')
rows=json.loads(table_result.stdout).get('nftables',[])
chains=[row['chain'] for row in rows if isinstance(row,dict) and 'chain' in row]
rules=[row['rule'] for row in rows if isinstance(row,dict) and 'rule' in row]
if len(chains)!=1 or len(rules)!=1: raise RuntimeError('bootstrap fence nft object count mismatch')
chain=chains[0]
if any(chain.get(key)!=value for key,value in {'family':'inet','table':name,'name':'input','type':'filter','hook':'input','prio':-300,'policy':'accept'}.items()): raise RuntimeError('bootstrap fence nft chain mismatch')
rule=rules[0]
expr=rule.get('expr')
iif={'match':{'op':'!=','left':{'meta':{'key':'iifname'}},'right':'lo'}}
dport={'match':{'op':'==','left':{'payload':{'protocol':'tcp','field':'dport'}},'right':8189}}
if rule.get('family')!='inet' or rule.get('table')!=name or rule.get('chain')!='input' or rule.get('comment')!=COMMENT: raise RuntimeError('bootstrap fence nft rule identity mismatch')
if not isinstance(expr,list) or len(expr)!=3 or expr[0]!=iif or expr[1]!=dport or not isinstance(expr[2],dict) or set(expr[2])!={'reject'}: raise RuntimeError('bootstrap fence nft rule mismatch')
reject=expr[2]['reject']
if reject not in ({'type':'tcp reset'},{'type':'tcp-reset'}): raise RuntimeError('bootstrap fence nft reject mismatch')
print(json.dumps({'state':'active'},separators=(',',':')))
""".replace("FENCE_NAME", repr(BOOTSTRAP_FENCE_NAME)).replace(
        "UNIT_NAME", repr(BOOTSTRAP_FENCE_UNIT_NAME)
    ).replace("CONFIG_PATH", repr(BOOTSTRAP_FENCE_CONFIG)).replace(
        "UNIT_PATH", repr(BOOTSTRAP_FENCE_UNIT)
    ).replace("LINK_PATH", repr(BOOTSTRAP_FENCE_ENABLE_LINK)).replace(
        "CONFIG_BYTES", repr(BOOTSTRAP_FENCE_CONFIG_BYTES)
    ).replace("UNIT_BYTES", repr(BOOTSTRAP_FENCE_UNIT_BYTES)).replace(
        "COMMENT", repr(BOOTSTRAP_FENCE_COMMENT)
    )


def probe_bootstrap_fence(client):
    """Return only exact active/absent states; reject every partial state."""
    raw = command(
        client, "sudo python3 -c " + shlex.quote(_bootstrap_fence_probe_source()),
        timeout=30,
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("bootstrap fence probe returned invalid JSON") from error
    if not isinstance(result, dict) or set(result) != {"state"}:
        raise RuntimeError("bootstrap fence probe returned invalid state")
    state = result["state"]
    if state not in {"active", "absent"}:
        raise RuntimeError("bootstrap fence probe returned unknown state")
    return state


def require_bootstrap_fence_capability_absent(client):
    """Read-only preflight: require nft/systemd support and no owned-name collision."""
    if probe_bootstrap_fence(client) != "absent":
        raise RuntimeError("bootstrap admission fence is already active")
    script = """import os,pathlib,stat,subprocess
nft=pathlib.Path('/usr/sbin/nft')
if not nft.exists(): raise RuntimeError('nft is unavailable')
resolved=nft.resolve(strict=True);info=resolved.stat()
if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or not os.access(resolved,os.X_OK): raise RuntimeError('nft executable is unsafe')
for raw in (CONFIG_PARENT,UNIT_PARENT,LINK_PARENT):
    path=pathlib.Path(raw)
    if path.is_symlink(): raise RuntimeError('bootstrap fence parent is a symlink: '+str(path))
    if not path.exists(): path=path.parent
    if path.is_symlink() or not path.is_dir(): raise RuntimeError('bootstrap fence parent is missing or unsafe: '+str(path))
    meta=path.stat()
    if meta.st_uid!=0 or meta.st_gid!=0 or meta.st_mode&0o022: raise RuntimeError('bootstrap fence parent metadata mismatch: '+str(path))
result=subprocess.run(['/usr/sbin/nft','--check','-f','-'],input=CONFIG_BYTES,capture_output=True)
if result.returncode: raise RuntimeError('nft bootstrap fence check failed')
""".replace("CONFIG_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_CONFIG).parent))).replace(
        "UNIT_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_UNIT).parent))
    ).replace("LINK_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_ENABLE_LINK).parent))).replace(
        "CONFIG_BYTES", repr(BOOTSTRAP_FENCE_CONFIG_BYTES)
    )
    command(client, "sudo python3 -c " + shlex.quote(script), timeout=30)


def arm_bootstrap_fence(client, attempts=3):
    """Install the persistent fence; reconcile a lost command response by probing."""
    script = """import os,pathlib,shlex,stat,subprocess,uuid
config=pathlib.Path(CONFIG_PATH);unit=pathlib.Path(UNIT_PATH);link=pathlib.Path(LINK_PATH);unit_name=UNIT_NAME
files=((config,CONFIG_BYTES,0o600),(unit,UNIT_BYTES,0o644))
def sync_dir(path):
    d=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
def require_safe_dir(path):
    if path.is_symlink() or not path.is_dir(): raise RuntimeError('bootstrap fence parent is missing or unsafe: '+str(path))
    info=path.stat()
    if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('bootstrap fence parent metadata mismatch: '+str(path))
for path,data,mode in files:
    require_safe_dir(path.parent)
    if path.is_symlink(): raise RuntimeError('bootstrap fence target is a symlink')
    if path.exists():
        info=path.stat()
        if not path.is_file() or info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=mode or path.read_bytes()!=data: raise RuntimeError('bootstrap fence target mismatch: '+str(path))
link_parent=link.parent
if link_parent.is_symlink(): raise RuntimeError('bootstrap fence link parent is a symlink')
if not link_parent.exists():
    require_safe_dir(link_parent.parent)
    link_parent.mkdir(mode=0o755);os.chown(link_parent,0,0);os.chmod(link_parent,0o755);sync_dir(link_parent.parent)
require_safe_dir(link_parent)
if link.exists() or link.is_symlink():
    info=link.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or info.st_gid!=0 or pathlib.Path(os.path.realpath(link))!=unit: raise RuntimeError('bootstrap fence enable link mismatch')
else:
    tmp=link.with_name(link.name+'.tmp-'+uuid.uuid4().hex)
    try:
        os.symlink(str(unit),tmp);os.lchown(tmp,0,0);os.replace(tmp,link);sync_dir(link_parent)
    finally:
        if tmp.is_symlink(): tmp.unlink()
subprocess.run(['systemctl','daemon-reload'],check=True)
requires=subprocess.run(['systemctl','show','--property','Requires','--value','comfy-panel.service'],text=True,capture_output=True,check=True).stdout.strip()
if unit_name not in set(shlex.split(requires)): raise RuntimeError('bootstrap fence required dependency was not loaded')
for path,data,mode in files:
    if path.exists(): continue
    tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        f=open(tmp,'wb');f.write(data);f.flush();os.fsync(f.fileno());f.close()
        os.chown(tmp,0,0);os.chmod(tmp,mode);os.replace(tmp,path)
        f=open(path,'rb');os.fsync(f.fileno());f.close();sync_dir(path.parent)
    finally:
        if tmp.exists() or tmp.is_symlink(): tmp.unlink()
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','start',unit_name],check=True)
for path in {config.parent,unit.parent,link_parent}: sync_dir(path)
""".replace("CONFIG_PATH", repr(BOOTSTRAP_FENCE_CONFIG)).replace(
        "UNIT_PATH", repr(BOOTSTRAP_FENCE_UNIT)
    ).replace("LINK_PATH", repr(BOOTSTRAP_FENCE_ENABLE_LINK)).replace(
        "CONFIG_BYTES", repr(BOOTSTRAP_FENCE_CONFIG_BYTES)
    ).replace(
        "UNIT_BYTES", repr(BOOTSTRAP_FENCE_UNIT_BYTES)
    ).replace("UNIT_NAME", repr(BOOTSTRAP_FENCE_UNIT_NAME))
    last_error = None
    for _ in range(attempts):
        try:
            command(client, "sudo python3 -c " + shlex.quote(script), timeout=60)
        except Exception as error:
            last_error = error
        try:
            if probe_bootstrap_fence(client) == "active":
                return
        except Exception as error:
            last_error = error
    raise RuntimeError(f"bootstrap fence could not be armed exactly: {last_error}") from last_error


def disarm_bootstrap_fence(client, attempts=3):
    """Remove only an exact owned fence; reconcile lost responses to exact absence."""
    script = """import json,os,pathlib,shlex,stat,subprocess
config=pathlib.Path(CONFIG_PATH);unit=pathlib.Path(UNIT_PATH);link=pathlib.Path(LINK_PATH);unit_name=UNIT_NAME
def sync_dir(path):
    d=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
def panel_active(): return subprocess.run(['systemctl','is-active','comfy-panel.service'],text=True,capture_output=True).stdout.strip()=='active'
def exact(path,data,mode):
    if not path.exists() and not path.is_symlink(): return
    if path.is_symlink() or not path.is_file(): raise RuntimeError('bootstrap fence cleanup target is unsafe: '+str(path))
    info=path.stat()
    if info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=mode or path.read_bytes()!=data: raise RuntimeError('bootstrap fence cleanup target mismatch: '+str(path))
exact(config,CONFIG_BYTES,0o600);exact(unit,UNIT_BYTES,0o644)
if link.exists() or link.is_symlink():
    info=link.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or info.st_gid!=0 or pathlib.Path(os.path.realpath(link))!=unit: raise RuntimeError('bootstrap fence cleanup link mismatch')
tables=subprocess.run(['/usr/sbin/nft','-j','list','tables'],text=True,capture_output=True,check=True)
present=any(row.get('table',{}).get('family')=='inet' and row.get('table',{}).get('name')==FENCE_NAME for row in json.loads(tables.stdout).get('nftables',[]) if isinstance(row,dict))
if present:
    table=subprocess.run(['/usr/sbin/nft','-j','list','table','inet',FENCE_NAME],text=True,capture_output=True,check=True)
    rows=json.loads(table.stdout).get('nftables',[])
    chains=[row['chain'] for row in rows if isinstance(row,dict) and 'chain' in row];rules=[row['rule'] for row in rows if isinstance(row,dict) and 'rule' in row]
    if len(chains)!=1 or len(rules)!=1: raise RuntimeError('bootstrap fence cleanup nft object count mismatch')
    chain=chains[0];rule=rules[0];expr=rule.get('expr')
    expected_chain={'family':'inet','table':FENCE_NAME,'name':'input','type':'filter','hook':'input','prio':-300,'policy':'accept'}
    iif={'match':{'op':'!=','left':{'meta':{'key':'iifname'}},'right':'lo'}};dport={'match':{'op':'==','left':{'payload':{'protocol':'tcp','field':'dport'}},'right':8189}}
    if any(chain.get(key)!=value for key,value in expected_chain.items()): raise RuntimeError('bootstrap fence cleanup nft chain mismatch')
    if rule.get('family')!='inet' or rule.get('table')!=FENCE_NAME or rule.get('chain')!='input' or rule.get('comment')!=COMMENT: raise RuntimeError('bootstrap fence cleanup nft identity mismatch')
    if not isinstance(expr,list) or len(expr)!=3 or expr[0]!=iif or expr[1]!=dport or not isinstance(expr[2],dict) or set(expr[2])!={'reject'} or expr[2]['reject'] not in ({'type':'tcp reset'},{'type':'tcp-reset'}): raise RuntimeError('bootstrap fence cleanup nft rule mismatch')
if not panel_active(): raise RuntimeError('panel must be active before reopening bootstrap admission')
if link.exists() or link.is_symlink(): link.unlink();sync_dir(link.parent)
subprocess.run(['systemctl','daemon-reload'],check=True)
requires=subprocess.run(['systemctl','show','--property','Requires','--value','comfy-panel.service'],text=True,capture_output=True,check=True).stdout.strip()
if unit_name in set(shlex.split(requires)): raise RuntimeError('bootstrap fence dependency remained after unlink')
if not panel_active(): raise RuntimeError('panel stopped while removing bootstrap fence dependency')
load=subprocess.run(['systemctl','show','--property','LoadState','--value',unit_name],text=True,capture_output=True).stdout.strip()
active=subprocess.run(['systemctl','is-active',unit_name],text=True,capture_output=True).stdout.strip()
if load!='not-found' or active=='active': subprocess.run(['systemctl','stop',unit_name],check=True)
if not panel_active(): raise RuntimeError('panel stopped while stopping bootstrap fence')
remaining=subprocess.run(['/usr/sbin/nft','-j','list','tables'],text=True,capture_output=True,check=True)
still_present=any(row.get('table',{}).get('family')=='inet' and row.get('table',{}).get('name')==FENCE_NAME for row in json.loads(remaining.stdout).get('nftables',[]) if isinstance(row,dict))
if still_present: subprocess.run(['/usr/sbin/nft','delete','table','inet',FENCE_NAME],check=True)
for path in (unit,config):
    if path.exists(): path.unlink()
for raw in (CONFIG_PARENT,UNIT_PARENT,LINK_PARENT):
    path=pathlib.Path(raw)
    if path.exists() and not path.is_symlink(): sync_dir(path)
subprocess.run(['systemctl','daemon-reload'],check=True)
if not panel_active(): raise RuntimeError('panel stopped while finalizing bootstrap fence removal')
""".replace("CONFIG_PATH", repr(BOOTSTRAP_FENCE_CONFIG)).replace(
        "UNIT_PATH", repr(BOOTSTRAP_FENCE_UNIT)
    ).replace("LINK_PATH", repr(BOOTSTRAP_FENCE_ENABLE_LINK)).replace(
        "CONFIG_BYTES", repr(BOOTSTRAP_FENCE_CONFIG_BYTES)
    ).replace("UNIT_BYTES", repr(BOOTSTRAP_FENCE_UNIT_BYTES)).replace(
        "FENCE_NAME", repr(BOOTSTRAP_FENCE_NAME)
    ).replace("COMMENT", repr(BOOTSTRAP_FENCE_COMMENT)
    ).replace("UNIT_NAME", repr(BOOTSTRAP_FENCE_UNIT_NAME)).replace(
        "CONFIG_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_CONFIG).parent))
    ).replace("UNIT_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_UNIT).parent))).replace(
        "LINK_PARENT", repr(str(pathlib.PurePosixPath(BOOTSTRAP_FENCE_ENABLE_LINK).parent))
    )
    last_error = None
    for _ in range(attempts):
        try:
            state = probe_bootstrap_fence(client)
            if state == "absent":
                return
        except Exception as error:
            last_error = error
        try:
            # The cleanup script validates every surviving object before removal,
            # so it can finish an owned partial state after a lost response.
            command(client, "sudo python3 -c " + shlex.quote(script), timeout=60)
        except Exception as error:
            last_error = error
        try:
            if probe_bootstrap_fence(client) == "absent":
                return
        except Exception as error:
            last_error = error
    raise RuntimeError(f"bootstrap fence could not be removed exactly: {last_error}") from last_error


def require_loopback_idle(client, phase, samples=IDLE_STABILITY_CHECKS,
                          interval=IDLE_STABILITY_INTERVAL):
    """Verify all admission counters over loopback while the public fence is active."""
    script = """import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8189/api/health',timeout=15) as response: print(json.dumps(json.load(response),separators=(',',':')))
"""
    last = None
    for sample in range(samples):
        raw = command(client, "python3 -c " + shlex.quote(script), timeout=30)
        try:
            health = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{phase}: invalid loopback health JSON") from error
        busy_fields = ("cloud_busy", "local_busy", "api_busy")
        if (not isinstance(health, dict) or type(health.get("ok")) is not bool
                or any(type(health.get(key)) is not bool for key in busy_fields)):
            raise RuntimeError(f"{phase}: invalid loopback health response")
        active = [key for key in busy_fields if health[key]]
        if active:
            raise ReleaseBusyError(
                f"{phase}: active generation backend(s): {', '.join(active)}"
            )
        last = health
        if sample + 1 < samples:
            time.sleep(interval)
    return last


def wait_for_loopback_live(client, timeout=60, allow_legacy=False):
    """Wait for panel liveness without crossing the bootstrap admission fence."""
    script = """import json,urllib.error,urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8189/api/live',timeout=15) as response: result=json.load(response)
except urllib.error.HTTPError as error:
    if not ALLOW_LEGACY or error.code!=404: raise
    with urllib.request.urlopen('http://127.0.0.1:8189/api/workflows',timeout=15) as response: workflows=json.load(response)
    if not isinstance(workflows,list): raise RuntimeError('legacy workflow response invalid')
    result={'ok':True,'service':'comfy-panel-legacy'}
print(json.dumps(result,separators=(',',':')))
""".replace("ALLOW_LEGACY", "True" if allow_legacy else "False")
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = json.loads(command(
                client, "python3 -c " + shlex.quote(script), timeout=30,
            ))
            if result.get("ok") and result.get("service") in {
                    "comfy-panel", "comfy-panel-legacy"}:
                return result
            last = result
        except Exception as error:
            last = {"error": str(error)[:200]}
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"loopback liveness timeout: {last}")


def stop_panel_resilient(client, attempts=3):
    """Stop the fenced panel and reconcile a lost systemctl response."""
    last_error = None
    for _ in range(attempts):
        try:
            command(client, "sudo systemctl stop comfy-panel", timeout=240)
        except Exception as error:
            last_error = error
        try:
            state = command(client, "systemctl is-active comfy-panel || true").strip()
            if state in {"inactive", "failed"}:
                return
            if state not in {"active", "activating", "deactivating", "reloading"}:
                raise RuntimeError(f"unknown panel service state: {state or 'empty'}")
        except Exception as error:
            last_error = error
    raise RuntimeError(f"panel stop could not be verified: {last_error}") from last_error


def set_remote_release_drain(client, enabled, require_start_draining=False):
    """Toggle admission draining over the authenticated loopback-only endpoint."""
    script = """import json,pathlib,subprocess,urllib.request
pid=subprocess.run(['systemctl','show','--property','MainPID','--value','comfy-panel'],text=True,capture_output=True,check=True).stdout.strip()
if not pid.isdigit() or int(pid)<=0: raise RuntimeError('comfy-panel has no running MainPID')
entries=pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\\0')
environment=dict(entry.split(b'=',1) for entry in entries if b'=' in entry)
token=environment.get(b'PANEL_RELEASE_TOKEN',b'').decode('ascii')
if not token: raise SystemExit(77)
if REQUIRE_START and environment.get(b'PANEL_RELEASE_DRAIN_ON_START')!=b'1': raise SystemExit(78)
payload=json.dumps({'enabled':ENABLED},separators=(',',':')).encode('ascii')
request=urllib.request.Request('http://127.0.0.1:8189/api/admin/release-drain',data=payload,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(request,timeout=15) as response: result=json.load(response)
print(json.dumps(result,separators=(',',':')))
""".replace("REQUIRE_START", "True" if require_start_draining else "False").replace(
        "ENABLED", "True" if enabled else "False"
    )
    try:
        raw = command(client, "sudo python3 -c " + shlex.quote(script), timeout=30)
    except RuntimeError as error:
        message = str(error)
        if "remote command failed (77):" in message:
            raise ReleaseDrainContractError(
                "running panel did not inherit PANEL_RELEASE_TOKEN"
            ) from error
        if "remote command failed (78):" in message:
            raise ReleaseDrainContractError(
                "restarted panel did not inherit release draining"
            ) from error
        raise
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("release drain returned invalid JSON") from error
    required = {"draining", "cloud_busy", "local_busy", "api_busy"}
    if (not isinstance(result, dict) or not required.issubset(result)
            or any(type(result.get(key)) is not bool for key in required)
            or result["draining"] != bool(enabled)):
        raise RuntimeError("release drain returned an invalid state")
    return {key: result[key] for key in required}


def enable_remote_release_drain(client, undo_if_busy=True,
                                require_start_draining=False):
    state = set_remote_release_drain(
        client, True, require_start_draining=require_start_draining,
    )
    active = [key for key in ("cloud_busy", "local_busy", "api_busy") if state[key]]
    if active:
        if undo_if_busy:
            try:
                set_remote_release_drain(client, False)
            except BaseException as disable_error:
                raise ReleaseBusyError(
                    "release drain found active work and could not be disabled: "
                    + ", ".join(active)
                ) from disable_error
        raise ReleaseBusyError(
            "release drain found active work: " + ", ".join(active)
        )
    return state


def wait_for_remote_release_drain(client, timeout=60):
    """Wait only for the restarted HTTP endpoint, never for active jobs."""
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return enable_remote_release_drain(
                client, undo_if_busy=False, require_start_draining=True,
            )
        except (ReleaseBusyError, ReleaseDrainContractError):
            raise
        except Exception as error:
            last_error = error
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"release drain endpoint did not become ready: {last_error}") from last_error


def require_bootstrap_drain_contract_absent(client):
    """Reject an inapplicable bootstrap without leaving a retained lock."""
    script = """import pathlib
targets=(pathlib.Path(ENV_PATH),pathlib.Path(DROPIN_PATH),pathlib.Path(START_PATH))
for path in targets:
    if path.exists() or path.is_symlink(): raise RuntimeError('bootstrap drain contract is already initialized: '+str(path))
for directory in sorted({path.parent for path in targets},key=str):
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir(): raise RuntimeError('invalid release contract directory: '+str(directory))
        info=directory.stat()
        if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('unsafe release contract directory: '+str(directory))
""".replace("ENV_PATH", repr(RELEASE_TOKEN_ENV_FILE)).replace(
        "DROPIN_PATH", repr(RELEASE_DRAIN_DROPIN_FILE)
    ).replace("START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE))
    command(client, "sudo python3 -c " + shlex.quote(script))


def snapshot_bootstrap_drain_contract(client, transaction):
    """Durably record the legacy host state before creating any drop-in."""
    state_path = transaction["root"] + "/bootstrap-drain-state.json"
    script = """import json,os,pathlib,stat,uuid
state_path=pathlib.Path(STATE_PATH)
targets=(pathlib.Path(ENV_PATH),pathlib.Path(DROPIN_PATH),pathlib.Path(START_PATH))
if state_path.exists() or state_path.is_symlink(): raise RuntimeError('bootstrap state already exists')
for path in targets:
    if path.exists() or path.is_symlink(): raise RuntimeError('bootstrap drain contract is already initialized: '+str(path))
directories=tuple(sorted({path.parent for path in targets},key=str))
for directory in directories:
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir(): raise RuntimeError('invalid release contract directory: '+str(directory))
        info=directory.stat()
        if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('unsafe release contract directory: '+str(directory))
state={'files':{str(path):{'exists':False,'data':'','mode':None} for path in targets},'created_directories':[str(directory) for directory in directories if not directory.exists()]}
tmp=state_path.with_name(state_path.name+'.tmp-'+uuid.uuid4().hex)
data=json.dumps(state,sort_keys=True,separators=(',',':')).encode('utf-8')
f=open(tmp,'wb');f.write(data);f.flush();os.fsync(f.fileno());f.close()
owner=state_path.parent.stat();os.chown(tmp,owner.st_uid,owner.st_gid);os.chmod(tmp,0o600);os.replace(tmp,state_path)
f=open(state_path,'rb');os.fsync(f.fileno());f.close()
d=os.open(str(state_path.parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
info=state_path.stat()
if state_path.is_symlink() or not state_path.is_file() or state_path.read_bytes()!=data: raise RuntimeError('bootstrap state readback mismatch')
if info.st_uid!=owner.st_uid or info.st_gid!=owner.st_gid or stat.S_IMODE(info.st_mode)!=0o600: raise RuntimeError('bootstrap state metadata mismatch')
""".replace("STATE_PATH", repr(state_path)).replace(
        "ENV_PATH", repr(RELEASE_TOKEN_ENV_FILE)
    ).replace("DROPIN_PATH", repr(RELEASE_DRAIN_DROPIN_FILE)).replace(
        "START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE)
    )
    command(client, "sudo python3 -c " + shlex.quote(script))


def require_persistent_release_drain_contract(client):
    """Verify restart-time drain/token configuration without returning the token."""
    script = """import pathlib,shlex,stat,subprocess
env_path=pathlib.Path(ENV_PATH);dropin_path=pathlib.Path(DROPIN_PATH)
for directory in (env_path.parent,dropin_path.parent):
    if directory.is_symlink() or not directory.is_dir(): raise RuntimeError('release contract directory is missing or unsafe: '+str(directory))
    info=directory.stat()
    if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('release contract directory metadata mismatch: '+str(directory))
for path,mode in ((env_path,0o600),(dropin_path,0o644)):
    if path.is_symlink() or not path.is_file(): raise RuntimeError('release drain contract file is missing or unsafe: '+str(path))
    info=path.stat()
    if info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=mode: raise RuntimeError('release drain contract metadata mismatch: '+str(path))
env_data=env_path.read_bytes()
if not env_data.startswith(b'PANEL_RELEASE_TOKEN=') or env_data.count(b'\\n')!=1 or not env_data.endswith(b'\\n'): raise RuntimeError('release token file shape mismatch')
token=env_data[len(b'PANEL_RELEASE_TOKEN='):-1]
if not token or any(byte<=32 or byte>=127 for byte in token): raise RuntimeError('release token is empty or malformed')
if dropin_path.read_bytes()!=DROPIN_BYTES: raise RuntimeError('release drain drop-in mismatch')
subprocess.run(['systemctl','daemon-reload'],check=True)
def show(name): return subprocess.run(['systemctl','show','--property',name,'--value','comfy-panel'],text=True,capture_output=True,check=True).stdout.strip()
loaded=shlex.split(show('DropInPaths'))
if str(dropin_path) not in loaded: raise RuntimeError('release drain drop-in is not loaded by systemd')
environment_files=shlex.split(show('EnvironmentFiles'))
if str(env_path) not in environment_files: raise RuntimeError('release token environment file is not effective')
unset=shlex.split(show('UnsetEnvironment'))
if any(value=='PANEL_RELEASE_TOKEN' or value.startswith('PANEL_RELEASE_TOKEN=') for value in unset): raise RuntimeError('release token is removed by UnsetEnvironment')
""".replace("ENV_PATH", repr(RELEASE_TOKEN_ENV_FILE)).replace(
        "DROPIN_PATH", repr(RELEASE_DRAIN_DROPIN_FILE)
    ).replace("DROPIN_BYTES", repr(RELEASE_DRAIN_DROPIN_BYTES))
    command(client, "sudo python3 -c " + shlex.quote(script))


def require_release_start_draining_unset(client):
    """Refuse stale/conflicting restart-time drain configuration."""
    script = """import pathlib,shlex,subprocess
name='PANEL_RELEASE_DRAIN_ON_START'
path=pathlib.Path(START_PATH)
if path.exists() or path.is_symlink(): raise RuntimeError('release start-drain drop-in already exists')
subprocess.run(['systemctl','daemon-reload'],check=True)
def show(prop): return subprocess.run(['systemctl','show','--property',prop,'--value','comfy-panel'],text=True,capture_output=True,check=True).stdout.strip()
if str(path) in shlex.split(show('DropInPaths')): raise RuntimeError('stale release start-drain drop-in is still loaded')
environment=shlex.split(show('Environment'))
if any(value.split('=',1)[0]==name for value in environment): raise RuntimeError('PANEL_RELEASE_DRAIN_ON_START is already set')
unset=shlex.split(show('UnsetEnvironment'))
if any(value==name or value.startswith(name+'=') for value in unset): raise RuntimeError('PANEL_RELEASE_DRAIN_ON_START is blocked by UnsetEnvironment')
""".replace("START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE))
    command(client, "sudo python3 -c " + shlex.quote(script))


def set_release_start_draining(client, enabled):
    """Ensure the next panel process rejects work before opening its socket."""
    script = """import os,pathlib,shlex,stat,subprocess,uuid
name='PANEL_RELEASE_DRAIN_ON_START'
enabled=ENABLED
path=pathlib.Path(START_PATH);expected=START_BYTES
parent=path.parent
if parent.exists():
    if parent.is_symlink() or not parent.is_dir(): raise RuntimeError('invalid release drop-in directory')
    info=parent.stat()
    if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('unsafe release drop-in directory')
elif enabled:
    parent.mkdir(mode=0o755)
    os.chown(parent,0,0);os.chmod(parent,0o755)
    d=os.open(str(parent.parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
if path.is_symlink(): raise RuntimeError('release start-drain target must not be a symlink')
if enabled:
    if path.exists() and (not path.is_file() or path.read_bytes()!=expected): raise RuntimeError('release start-drain target has unexpected content')
    tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    f=open(tmp,'wb');f.write(expected);f.flush();os.fsync(f.fileno());f.close()
    os.chown(tmp,0,0);os.chmod(tmp,0o644);os.replace(tmp,path)
    f=open(path,'rb');os.fsync(f.fileno());f.close()
    d=os.open(str(parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
else:
    if path.exists():
        info=path.stat()
        if not path.is_file() or info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o644 or path.read_bytes()!=expected: raise RuntimeError('release start-drain target cannot be safely removed')
        path.unlink()
        d=os.open(str(parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
subprocess.run(['systemctl','daemon-reload'],check=True)
def show(prop): return subprocess.run(['systemctl','show','--property',prop,'--value','comfy-panel'],text=True,capture_output=True,check=True).stdout.strip()
dropins=shlex.split(show('DropInPaths'))
environment=shlex.split(show('Environment'))
matches=[value for value in environment if value.split('=',1)[0]==name]
if enabled:
    if str(path) not in dropins or matches!=[name+'=1']: raise RuntimeError('systemd release start-drain verification failed')
    unset=shlex.split(show('UnsetEnvironment'))
    if any(value==name or value.startswith(name+'=') for value in unset): raise RuntimeError('release start-drain is blocked by UnsetEnvironment')
    info=path.stat()
    if info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=0o644 or path.read_bytes()!=expected: raise RuntimeError('release start-drain readback mismatch')
elif str(path) in dropins or matches:
    raise RuntimeError('systemd release start-drain removal verification failed')
""".replace("START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE)).replace(
        "START_BYTES", repr(RELEASE_START_DRAIN_DROPIN_BYTES)
    ).replace("ENABLED", "True" if enabled else "False")
    command(client, "sudo python3 -c " + shlex.quote(script))


def install_bootstrap_drain_contract(client, transaction):
    """Install a dedicated release token/drop-in without returning the token."""
    state_path = transaction["root"] + "/bootstrap-drain-state.json"
    script = """import json,os,pathlib,secrets,stat,uuid
state_path=pathlib.Path(STATE_PATH)
targets=[pathlib.Path(ENV_PATH),pathlib.Path(DROPIN_PATH)]
active_path=pathlib.Path(START_PATH)
state=json.loads(state_path.read_text(encoding='utf-8'))
expected={str(pathlib.Path(ENV_PATH)),str(pathlib.Path(DROPIN_PATH)),str(active_path)}
if not isinstance(state,dict) or set(state)!={'files','created_directories'} or set(state.get('files',{}))!=expected: raise RuntimeError('invalid bootstrap state structure')
if any(entry!={'exists':False,'data':'','mode':None} for entry in state['files'].values()): raise RuntimeError('bootstrap state is not a legacy absence snapshot')
for path in targets:
    if path.is_symlink(): raise RuntimeError('bootstrap target must not be a symlink: '+str(path))
    if path.exists(): raise RuntimeError('bootstrap drain contract is already initialized: '+str(path))
directories=(pathlib.Path(ENV_PATH).parent,pathlib.Path(DROPIN_PATH).parent)
def atomic(path,data,mode):
    parent_existed=path.parent.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    if not parent_existed:
        d=os.open(str(path.parent.parent),os.O_RDONLY);os.fsync(d);os.close(d)
    tmp=path.with_name(path.name+'.bootstrap-'+uuid.uuid4().hex)
    f=open(tmp,'wb');f.write(data);f.flush();os.fsync(f.fileno());f.close()
    os.chown(tmp,0,0);os.chmod(tmp,mode);os.replace(tmp,path)
    f=open(path,'rb');os.fsync(f.fileno());f.close()
    d=os.open(str(path.parent),os.O_RDONLY);os.fsync(d);os.close(d)
for directory in directories:
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir(): raise RuntimeError('invalid release contract directory: '+str(directory))
        info=directory.stat()
        if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022: raise RuntimeError('unsafe release contract directory: '+str(directory))
    else:
        directory.mkdir(parents=True,mode=0o755)
        os.chown(directory,0,0);os.chmod(directory,0o755)
        d=os.open(str(directory),os.O_RDONLY);os.fsync(d);os.close(d)
        d=os.open(str(directory.parent),os.O_RDONLY);os.fsync(d);os.close(d)
if active_path.is_symlink() or not active_path.is_file(): raise RuntimeError('release start-drain drop-in is not armed')
active_info=active_path.stat()
if active_info.st_uid!=0 or active_info.st_gid!=0 or stat.S_IMODE(active_info.st_mode)!=0o644 or active_path.read_bytes()!=START_BYTES: raise RuntimeError('release start-drain drop-in mismatch')
token=secrets.token_urlsafe(48)
atomic(pathlib.Path(ENV_PATH),('PANEL_RELEASE_TOKEN='+token+'\\n').encode('ascii'),0o600)
atomic(pathlib.Path(DROPIN_PATH),DROPIN_BYTES,0o644)
env_path=pathlib.Path(ENV_PATH);dropin_path=pathlib.Path(DROPIN_PATH)
if stat.S_IMODE(env_path.stat().st_mode)!=0o600 or env_path.stat().st_uid!=0 or env_path.stat().st_gid!=0: raise RuntimeError('bootstrap token metadata mismatch')
env_data=env_path.read_bytes()
if not env_data.startswith(b'PANEL_RELEASE_TOKEN=') or env_data.count(b'\\n')!=1 or not env_data.endswith(b'\\n'): raise RuntimeError('bootstrap token readback mismatch')
if stat.S_IMODE(dropin_path.stat().st_mode)!=0o644 or dropin_path.stat().st_uid!=0 or dropin_path.stat().st_gid!=0: raise RuntimeError('bootstrap drop-in metadata mismatch')
if dropin_path.read_bytes()!=DROPIN_BYTES: raise RuntimeError('bootstrap drop-in readback mismatch')
""".replace("STATE_PATH", repr(state_path)).replace(
        "ENV_PATH", repr(RELEASE_TOKEN_ENV_FILE)
    ).replace("DROPIN_PATH", repr(RELEASE_DRAIN_DROPIN_FILE)).replace(
        "START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE)
    ).replace("DROPIN_BYTES", repr(RELEASE_DRAIN_DROPIN_BYTES)).replace(
        "START_BYTES", repr(RELEASE_START_DRAIN_DROPIN_BYTES)
    )
    command(client, "sudo python3 -c " + shlex.quote(script))
    command(client, "sudo systemctl daemon-reload")


def restore_bootstrap_drain_contract(client, transaction):
    """Restore the exact pre-bootstrap token/drop-in state and verify it."""
    state_path = transaction["root"] + "/bootstrap-drain-state.json"
    script = """import json,os,pathlib
state=json.loads(pathlib.Path(STATE_PATH).read_text(encoding='utf-8'))
expected={ENV_PATH,DROPIN_PATH,START_PATH}
allowed_directories={str(pathlib.Path(value).parent) for value in expected}
if not isinstance(state,dict) or set(state)!={'files','created_directories'}: raise RuntimeError('invalid bootstrap state structure')
files=state['files'];created_directories=state['created_directories']
if not isinstance(files,dict) or set(files)!=expected: raise RuntimeError('invalid bootstrap state file set')
if not isinstance(created_directories,list) or len(created_directories)!=len(set(created_directories)) or not set(created_directories)<=allowed_directories: raise RuntimeError('invalid bootstrap directory state')
for raw_path,entry in files.items():
    path=pathlib.Path(raw_path)
    if path.is_symlink(): raise RuntimeError('bootstrap restore target became a symlink')
    if entry=={'exists':False,'data':'','mode':None}:
        if path.exists() and not path.is_file(): raise RuntimeError('bootstrap restore target is not a regular file')
        path.unlink(missing_ok=True)
        if path.parent.is_dir():
            d=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
    else: raise RuntimeError('invalid bootstrap state')
for raw_directory in sorted(created_directories,key=lambda value:len(pathlib.Path(value).parts),reverse=True):
    directory=pathlib.Path(raw_directory)
    if directory.is_symlink(): raise RuntimeError('bootstrap restore directory became a symlink')
    if directory.exists():
        if not directory.is_dir(): raise RuntimeError('bootstrap restore directory is invalid')
        directory.rmdir()
        d=os.open(str(directory.parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)
for raw_path in files:
    path=pathlib.Path(raw_path)
    if path.exists() or path.is_symlink(): raise RuntimeError('bootstrap restore absence mismatch')
""".replace("STATE_PATH", repr(state_path)).replace(
        "ENV_PATH", repr(RELEASE_TOKEN_ENV_FILE)
    ).replace("DROPIN_PATH", repr(RELEASE_DRAIN_DROPIN_FILE)).replace(
        "START_PATH", repr(RELEASE_START_DRAIN_DROPIN_FILE)
    )
    command(client, "sudo python3 -c " + shlex.quote(script))
    command(client, "sudo systemctl daemon-reload")
    require_release_start_draining_unset(client)


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
    durability_script = (
        "import os;"
        f"f=open({(RELEASE_LOCK_DIR + '/owner')!r},'rb');os.fsync(f.fileno());f.close();"
        f"paths={(RELEASE_LOCK_DIR, transaction['stage_root'], transaction['backup_root'], transaction['root'], RELEASE_TRANSACTIONS_DIR, REMOTE_ROOT)!r};"
        "[(lambda d:(os.fsync(d),os.close(d)))(os.open(path,os.O_RDONLY)) for path in paths]"
    )
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
        f"{shlex.quote(transaction['backup_root'])}; "
        f"python3 -c {shlex.quote(durability_script)}; trap - EXIT"
    )
    command(client, script)


def release_release_lock(client, transaction):
    owner = str(transaction["id"])
    script = (
        "set -eu; "
        f"test \"$(cat {shlex.quote(RELEASE_LOCK_DIR + '/owner')})\" = {shlex.quote(owner)}; "
        f"rm -rf -- {shlex.quote(RELEASE_LOCK_DIR)}; "
        "python3 -c " + shlex.quote(
            f"import os;d=os.open({REMOTE_ROOT!r},os.O_RDONLY);os.fsync(d);os.close(d)"
        )
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


def fsync_remote_file(client, path):
    """Flush one remote file and its containing directory before phase commit."""
    script = (
        "import os,pathlib;"
        f"p=pathlib.Path({path!r});"
        "f=open(p,'rb');os.fsync(f.fileno());f.close();"
        "d=os.open(str(p.parent),os.O_RDONLY);os.fsync(d);os.close(d)"
    )
    command(client, "python3 -c " + shlex.quote(script))


def fsync_remote_directory(client, path):
    """Flush a remote directory after an entry is removed or renamed."""
    script = (
        "import os;"
        f"d=os.open({str(path)!r},os.O_RDONLY);os.fsync(d);os.close(d)"
    )
    command(client, "python3 -c " + shlex.quote(script))


def fsync_systemd_unit_state(client):
    """Flush systemd unit directories after enable/disable/mask mutations."""
    script = """import os,pathlib
paths=set()
for raw in ('/etc/systemd/system','/run/systemd/system'):
    root=pathlib.Path(raw)
    if root.is_dir():
        for current,dirs,files in os.walk(root): paths.add(pathlib.Path(current))
for path in sorted(paths,key=lambda value:len(value.parts),reverse=True):
        descriptor=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY)
        os.fsync(descriptor)
        os.close(descriptor)
"""
    command(client, "sudo python3 -c " + shlex.quote(script))


def stage_file_resilient(client, sftp, local, remote, transaction, data):
    """Upload and byte-verify one file inside this release transaction."""
    if not isinstance(data, bytes):
        raise TypeError(f"release payload must be immutable bytes: {local}")
    staged = transaction_file(transaction, remote, "stage")
    parent = str(pathlib.PurePosixPath(staged).parent)
    command(client, "mkdir -p -- " + shlex.quote(parent) + "; chmod 0700 -- " + shlex.quote(parent))
    last_error = None
    for attempt in range(1, 4):
        try:
            with sftp.open(staged, "wb") as handle:
                handle.write(data)
            with sftp.open(staged, "rb") as handle:
                if handle.read() != data:
                    raise RuntimeError(f"staging mismatch: {local}")
            command(client, "chmod 0600 -- " + shlex.quote(staged))
            fsync_remote_file(client, staged)
            return staged
        except Exception as error:
            last_error = error
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise last_error


def backup_release(client, sftp, remote_paths, transaction):
    """Snapshot the previous live set into one immutable transaction."""
    manifest = {}
    for remote in remote_paths:
        backup = transaction_file(transaction, remote, "backup")
        parent = str(pathlib.PurePosixPath(backup).parent)
        command(client, "mkdir -p -- " + shlex.quote(parent) + "; chmod 0700 -- " + shlex.quote(parent))
        try:
            remote_stat = sftp.lstat(remote)
        except FileNotFoundError:
            manifest[remote] = {"exists": False, "sha256": None, "mode": None}
        else:
            if not stat.S_ISREG(int(remote_stat.st_mode)):
                raise RuntimeError(f"release target is not a regular file: {remote}")
            command(client, f"cp -- {shlex.quote(remote)} {shlex.quote(backup)}")
            command(client, f"chmod 0600 -- {shlex.quote(backup)}")
            fsync_remote_file(client, backup)
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
        "f=open(manifest_tmp,'rb');os.fsync(f.fileno());f.close();"
        "os.replace(manifest_tmp,manifest);os.chmod(manifest,0o600);"
        f"manifest_sha256=pathlib.Path({transaction['manifest_sha256']!r});"
        f"manifest_sha256_tmp=pathlib.Path({manifest_sha256_tmp!r});"
        f"manifest_sha256_tmp.write_text({(manifest_digest + chr(10))!r},encoding='ascii');"
        "f=open(manifest_sha256_tmp,'rb');os.fsync(f.fileno());f.close();"
        "os.replace(manifest_sha256_tmp,manifest_sha256);os.chmod(manifest_sha256,0o600);"
        "f=open(manifest,'rb');os.fsync(f.fileno());f.close();"
        "f=open(manifest_sha256,'rb');os.fsync(f.fileno());f.close();"
        "d=os.open(str(manifest.parent),os.O_RDONLY);os.fsync(d);os.close(d)"
    )
    command(client, "python3 -c " + shlex.quote(script))
    return manifest


def rollback_release(client, sftp, remote_paths, transaction, public_base=PUBLIC_BASE,
                     restore_bootstrap=False, bootstrap_fence=False):
    """Restore one verified transaction; remain stopped on any uncertainty."""
    if bootstrap_fence:
        if probe_bootstrap_fence(client) != "active":
            raise RuntimeError("bootstrap rollback requires an exact active fence")
        stop_panel_resilient(client)
    else:
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
                fsync_remote_directory(client, str(pathlib.PurePosixPath(remote).parent))
                command(
                    client,
                    "python3 -c " + shlex.quote(
                        f"import pathlib; p=pathlib.Path({remote!r}); "
                        "assert not p.exists() and not p.is_symlink(), 'rollback absence mismatch'"
                    ),
                )
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
            rollback_temp = remote + ".rollback-" + uuid.uuid4().hex
            command(client, f"cp -- {shlex.quote(backup)} {shlex.quote(rollback_temp)}")
            command(client, f"chmod {mode:04o} -- {shlex.quote(rollback_temp)}")
            fsync_remote_file(client, rollback_temp)
            command(client, f"mv -f -- {shlex.quote(rollback_temp)} {shlex.quote(remote)}")
            fsync_remote_file(client, remote)
            live_digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({remote!r},'rb').read()).hexdigest())"
            )).strip()
            if not hmac.compare_digest(live_digest, expected):
                raise RuntimeError(f"rollback verification mismatch: {remote}")
        except Exception as error:
            errors.append(f"{remote}: {error}")
    if errors:
        raise RuntimeError("rollback failed; panel left stopped: " + "; ".join(errors))

    if restore_bootstrap:
        restore_bootstrap_drain_contract(client, transaction)

    try:
        command(client, "sudo systemctl start comfy-panel", timeout=240)
        if bootstrap_fence:
            # Keep the persistent fence until the caller has also restored the
            # watchdog. Reopening here would expose legacy state on a later
            # watchdog-restore failure.
            live = wait_for_loopback_live(client, timeout=60, allow_legacy=True)
        else:
            live = wait_for_live(public_base, timeout=60, allow_legacy=True)
        if not live.get("ok"):
            raise RuntimeError(str(live))
    except Exception as error:
        if bootstrap_fence:
            try:
                arm_bootstrap_fence(client)
                stop_panel_resilient(client)
            except BaseException as fence_error:
                error.add_note(f"bootstrap rollback fence restore failed: {fence_error}")
        else:
            command(client, "sudo systemctl stop comfy-panel", timeout=240)
        raise RuntimeError(
            f"rollback health failed; panel left stopped: {error}"
        ) from error


def emergency_stop_after_failed_release(client):
    """Best-effort fail-closed stop used when normal rollback cannot begin."""
    errors = []
    for label, text in (
        ("watchdog timer", "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.timer)\" != not-found ]; then sudo systemctl disable --runtime --now comfy-panel-watchdog.timer; sudo systemctl disable --now comfy-panel-watchdog.timer; fi"),
        ("watchdog service", "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.service)\" != not-found ]; then sudo systemctl disable --runtime --now comfy-panel-watchdog.service; sudo systemctl disable --now comfy-panel-watchdog.service; sudo systemctl stop comfy-panel-watchdog.service; fi"),
        ("watchdog mask", "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.service)\" != not-found ]; then sudo systemctl mask --runtime comfy-panel-watchdog.service; fi"),
        ("panel", "sudo systemctl stop comfy-panel"),
    ):
        try:
            command(client, text, timeout=240)
        except BaseException as error:
            errors.append(f"{label}: {error}")
    try:
        fsync_systemd_unit_state(client)
    except BaseException as error:
        errors.append(f"systemd state durability: {error}")
    try:
        panel_state = command(client, "systemctl is-active comfy-panel || true").strip()
        watchdog_state = watchdog_isolation_state(client)
        timer_active, timer_enabled, service_active, service_enabled = watchdog_state
        if panel_state != "inactive":
            errors.append(f"panel still {panel_state or 'unknown'}")
        if (timer_active != "inactive"
                or timer_enabled not in {"disabled", "masked", "masked-runtime", "not-found"}
                or service_active != "inactive"
                or service_enabled not in {"static", "masked", "masked-runtime", "not-found"}):
            errors.append("watchdog is not isolated")
    except BaseException as error:
        errors.append(f"stop verification: {error}")
    if errors:
        raise RuntimeError("emergency release stop is uncertain: " + "; ".join(errors))


def fetch_json(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=60) as response:
        return json.load(response)


def require_dreamapi_release_health(health):
    """Require the selected direct or workstation transport to be ready."""
    if not isinstance(health, dict):
        raise RuntimeError("public DreamAPI health response is invalid")
    mode = health.get("dreamapi_connection_mode", "workstation")
    if mode not in {"direct", "workstation"}:
        raise RuntimeError("public DreamAPI transport mode is invalid")
    required_true = ("dreamapi_configured", "dreamapi_contract_match",
                     "dreamapi_transport_ready" if mode == "direct" else "dreamapi_workstation_egress")
    if any(health.get(field) is not True for field in required_true):
        raise RuntimeError("public DreamAPI workstation contract is not ready")
    if health.get("dreamapi_contract_sha256") != DREAMAPI_CONTRACT_SHA256:
        raise RuntimeError("public DreamAPI contract hash is unexpected")
    if health.get("dreamapi_uncertainty_fence") is not False:
        raise RuntimeError("public DreamAPI outcome is still uncertain")
    return health


def require_public_idle(base, phase, samples=IDLE_STABILITY_CHECKS,
                        interval=IDLE_STABILITY_INTERVAL):
    """Fail closed unless every generation backend stays idle across samples."""
    busy_fields = ("cloud_busy", "local_busy", "api_busy")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ValueError("idle samples must be a positive integer")
    last = None
    for sample in range(samples):
        try:
            health = fetch_json(base, "/api/health")
        except Exception as error:
            raise RuntimeError(f"{phase}: health check failed closed: {error}") from error
        if (not isinstance(health, dict) or type(health.get("ok")) is not bool
                or any(type(health.get(key)) is not bool for key in busy_fields)):
            raise RuntimeError(f"{phase}: invalid health response; refusing release")
        active = [key for key in busy_fields if health[key]]
        if active:
            raise RuntimeError(
                f"{phase}: active generation backend(s): {', '.join(active)}; refusing release"
            )
        last = health
        if sample + 1 < samples:
            time.sleep(interval)
    return last


def _last_http_headers(raw):
    """Return the final HTTP header block emitted by curl."""
    blocks = re.split(br"\r?\n\r?\n", raw)
    candidates = [block for block in blocks if block.startswith(b"HTTP/")]
    if not candidates:
        raise RuntimeError("public response headers are missing")
    headers = {}
    for line in candidates[-1].splitlines()[1:]:
        if b":" not in line:
            continue
        name, value = line.split(b":", 1)
        headers[name.strip().lower()] = value.strip().lower()
    return headers


def fetch_bytes(base, path, timeout=60, accept_gzip=False,
                max_bytes=PUBLIC_RESPONSE_MAX_BYTES):
    """Download one bounded response with a killable wall-clock timeout."""
    if (not isinstance(max_bytes, int) or isinstance(max_bytes, bool)
            or max_bytes < 1):
        raise ValueError("public response byte limit must be a positive integer")
    if timeout <= 0:
        raise RuntimeError("public large response verification timeout")
    url = base.rstrip("/") + path
    wire_max_bytes = max_bytes + PUBLIC_GZIP_WIRE_OVERHEAD if accept_gzip else max_bytes
    with tempfile.TemporaryDirectory(prefix="comfy-release-fetch-") as temporary:
        body_path = pathlib.Path(temporary) / "body"
        header_path = pathlib.Path(temporary) / "headers"
        command_line = [
            "curl", "--fail", "--silent", "--show-error",
            "--proto", "=http,https", "--max-redirs", "0",
            "--max-time", f"{timeout:.3f}",
            "--max-filesize", str(wire_max_bytes),
            "--dump-header", str(header_path),
            "--output", str(body_path),
        ]
        if accept_gzip:
            command_line.extend(["--header", "Accept-Encoding: gzip"])
        command_line.append(url)
        try:
            result = subprocess.run(
                command_line, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("public large response verification timeout") from error
        headers = None
        if header_path.is_file():
            try:
                headers = _last_http_headers(header_path.read_bytes())
            except RuntimeError:
                if result.returncode == 0:
                    raise
        if body_path.is_file() and body_path.stat().st_size > wire_max_bytes:
            raise RuntimeError("public response exceeds byte limit")
        if headers is not None:
            length = headers.get(b"content-length")
            if length is not None:
                try:
                    if int(length) > wire_max_bytes:
                        raise RuntimeError("public response exceeds byte limit")
                except ValueError as error:
                    raise RuntimeError("public response Content-Length is invalid") from error
        if result.returncode == 28:
            raise RuntimeError("public large response verification timeout")
        if result.returncode == 63:
            raise RuntimeError("public response exceeds byte limit")
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace")[:300].strip()
            raise RuntimeError(f"public response download failed: {detail or result.returncode}")
        if not body_path.is_file() or not header_path.is_file():
            raise RuntimeError("public response download is incomplete")
        if headers is None:
            raise RuntimeError("public response headers are missing")
        body = body_path.read_bytes()
    encoding = headers.get(b"content-encoding", b"").split(b",", 1)[0].strip()
    if encoding == b"gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
                decoded = archive.read(max_bytes + 1)
        except (EOFError, OSError) as error:
            raise RuntimeError("public gzip response is invalid") from error
        if len(decoded) > max_bytes:
            raise RuntimeError("public gzip response exceeds byte limit")
        return decoded
    if encoding:
        raise RuntimeError("public response uses unsupported content encoding")
    if len(body) > max_bytes:
        raise RuntimeError("public response exceeds byte limit")
    return body


def fetch_bytes_resilient(base, path, timeout=300, accept_gzip=False, attempts=3,
                          deadline=None, max_bytes=None):
    last_error = None
    for attempt in range(1, attempts + 1):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise RuntimeError("public large response verification timeout") from last_error
        request_timeout = timeout if remaining is None else min(timeout, remaining)
        try:
            kwargs = {"timeout": request_timeout, "accept_gzip": accept_gzip}
            if max_bytes is not None:
                kwargs["max_bytes"] = max_bytes
            return fetch_bytes(base, path, **kwargs)
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


def verify_public_large_responses(base, expected_creator, expected_preview,
                                  deadline=None, expected_realism=None):
    if (not isinstance(expected_creator, bytes)
            or not isinstance(expected_preview, bytes)
            or (expected_realism is not None
                and not isinstance(expected_realism, bytes))):
        raise TypeError("public verification requires immutable expected bytes")
    if deadline is None:
        deadline = time.monotonic() + PUBLIC_LARGE_VERIFY_TIMEOUT
    realism = home = None
    if expected_realism is not None:
        realism = fetch_bytes_resilient(
            base, "/realism", timeout=300, attempts=3,
            deadline=deadline, max_bytes=len(expected_realism),
        )
        home = fetch_bytes_resilient(
            base, "/", timeout=300, attempts=3,
            deadline=deadline, max_bytes=len(expected_creator),
        )
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("public large response verification timeout")
        creator = fetch_bytes_resilient(
            base, "/?style=retro_manga_luxury", timeout=300, accept_gzip=True,
            attempts=3, deadline=deadline, max_bytes=len(expected_creator),
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("public large response verification timeout")
        preview = fetch_bytes_resilient(
            base, "/static/previews/style-retro-manga-luxury.webp",
            timeout=300, attempts=3, deadline=deadline,
            max_bytes=len(expected_preview),
        )
        if creator != expected_creator:
            raise RuntimeError(f"public creator large response mismatch on attempt {attempt + 1}")
        if preview != expected_preview:
            raise RuntimeError(f"public creator preview mismatch on attempt {attempt + 1}")
    if expected_realism is not None:
        return realism, home, expected_creator, expected_preview
    return expected_creator, expected_preview


def verify_public_creator_config(base, creator, payloads):
    """Verify the lazy-loaded config referenced by the exact released HTML."""
    match = re.search(rb'const STYLE_CONFIG_URL="(/static/style-configs\.[0-9a-f]{12}\.json)"', creator)
    if not match:
        raise RuntimeError("public creator config reference missing")
    route = match.group(1).decode("ascii")
    expected = payloads.get(BASE / route.lstrip("/"))
    if not isinstance(expected, bytes):
        raise RuntimeError("creator config missing from immutable release")
    actual = fetch_bytes_resilient(base, route, max_bytes=len(expected))
    if actual != expected:
        raise RuntimeError("public creator config bytes mismatch")
    profiles = json.loads(actual)
    for key, trigger in (("retro_manga_luxury", "jt_style321_v1"),
                         ("style221", "zxqelun"), ("style222", "zxqavri")):
        if profiles.get(key, {}).get("trigger") != trigger:
            raise RuntimeError("public creator style config mismatch: " + key)


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


def verify_installed_watchdog_contract(client):
    """Verify systemd loaded exactly the watchdog release, without overrides."""
    service_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.service"
    timer_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.timer"
    script = """import pathlib,shlex,stat,subprocess
def show(unit,prop): return subprocess.run(['systemctl','show','--property',prop,'--value',unit],text=True,capture_output=True,check=True).stdout.strip()
service='comfy-panel-watchdog.service';timer='comfy-panel-watchdog.timer'
service_path=pathlib.Path(SERVICE_PATH);timer_path=pathlib.Path(TIMER_PATH);executable_path=pathlib.Path(EXECUTABLE_PATH)
for unit,path in ((service,service_path),(timer,timer_path)):
    if show(unit,'FragmentPath')!=str(path): raise RuntimeError('watchdog effective FragmentPath mismatch: '+unit)
    if shlex.split(show(unit,'DropInPaths')): raise RuntimeError('watchdog effective drop-ins are not allowed: '+unit)
for path,source,mode in ((service_path,pathlib.Path(SERVICE_SOURCE),0o644),(timer_path,pathlib.Path(TIMER_SOURCE),0o644),(executable_path,pathlib.Path(EXECUTABLE_SOURCE),0o755)):
    if path.is_symlink() or not path.is_file() or path.read_bytes()!=source.read_bytes(): raise RuntimeError('watchdog installed bytes mismatch: '+str(path))
    info=path.stat()
    if info.st_uid!=0 or info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=mode: raise RuntimeError('watchdog installed metadata mismatch: '+str(path))
exec_start=show(service,'ExecStart')
expected_argv='argv[]=/usr/bin/python3 /usr/local/libexec/comfy-panel-watchdog.py'
if exec_start.count('path=')!=1 or exec_start.count('argv[]=')!=1 or 'path=/usr/bin/python3' not in exec_start or expected_argv not in exec_start: raise RuntimeError('watchdog effective ExecStart mismatch')
if show(timer,'Unit')!=service or show(timer,'Persistent')!='yes': raise RuntimeError('watchdog effective timer target/persistence mismatch')
timers=show(timer,'TimersMonotonic')
if 'OnBootUSec=2min' not in timers or 'OnUnitActiveUSec=1min' not in timers: raise RuntimeError('watchdog effective timer schedule mismatch')
""".replace("SERVICE_PATH", repr(WATCHDOG_SERVICE_UNIT)).replace(
        "TIMER_PATH", repr(WATCHDOG_TIMER_UNIT)
    ).replace("EXECUTABLE_PATH", repr(WATCHDOG_EXECUTABLE)).replace(
        "SERVICE_SOURCE", repr(service_src)
    ).replace("TIMER_SOURCE", repr(timer_src)).replace(
        "EXECUTABLE_SOURCE", repr(REMOTE_ROOT + "/tools/panel_liveness_watchdog.py")
    )
    command(client, "sudo python3 -c " + shlex.quote(script))


def install_watchdog_units(client):
    service_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.service"
    timer_src = REMOTE_ROOT + "/deploy/comfy-panel-watchdog.timer"
    command(client, "sudo systemctl unmask --runtime comfy-panel-watchdog.service comfy-panel-watchdog.timer")
    command(client, "sudo systemctl unmask comfy-panel-watchdog.service comfy-panel-watchdog.timer")
    command(client, "sudo install -d -o root -g root -m 0755 /usr/local/libexec")
    command(client, "sudo install -o root -g root -m 0755 " + shlex.quote(REMOTE_ROOT + "/tools/panel_liveness_watchdog.py") + " " + shlex.quote(WATCHDOG_EXECUTABLE))
    command(client, "sudo install -o root -g root -m 0644 " + shlex.quote(service_src) + " " + shlex.quote(WATCHDOG_SERVICE_UNIT))
    command(client, "sudo install -o root -g root -m 0644 " + shlex.quote(timer_src) + " " + shlex.quote(WATCHDOG_TIMER_UNIT))
    for path in (WATCHDOG_EXECUTABLE, WATCHDOG_SERVICE_UNIT, WATCHDOG_TIMER_UNIT):
        fsync_remote_file(client, path)
    command(client, "sudo systemctl daemon-reload")
    verify_installed_watchdog_contract(client)
    command(client, "sudo systemctl enable --now comfy-panel-watchdog.timer")
    fsync_systemd_unit_state(client)
    if command(client, "systemctl is-enabled comfy-panel-watchdog.timer").strip() != "enabled":
        raise RuntimeError("watchdog timer is not enabled")
    if command(client, "systemctl is-active comfy-panel-watchdog.timer").strip() != "active":
        raise RuntimeError("watchdog timer is not active")
    command(client, "sudo systemctl start comfy-panel-watchdog.service", timeout=240)
    script = """import subprocess
def show(prop): return subprocess.run(['systemctl','show','--property',prop,'--value','comfy-panel-watchdog.service'],text=True,capture_output=True,check=True).stdout.strip()
print(show('LoadState'));print(show('UnitFileState'));print(show('ActiveState'));print(show('Result'))
"""
    service_state = command(
        client, "python3 -c " + shlex.quote(script),
    ).splitlines()
    if service_state != ["loaded", "static", "inactive", "success"]:
        raise RuntimeError("watchdog service execution verification failed")
    verify_installed_watchdog_contract(client)


def watchdog_isolation_state(client):
    script = """import subprocess
def state(*args):
    r=subprocess.run(['systemctl',*args],text=True,capture_output=True)
    return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ''
print(state('is-active','comfy-panel-watchdog.timer'))
print(state('is-enabled','comfy-panel-watchdog.timer'))
print(state('is-active','comfy-panel-watchdog.service'))
print(state('is-enabled','comfy-panel-watchdog.service'))
"""
    rows = command(client, "python3 -c " + shlex.quote(script)).splitlines()
    if len(rows) != 4:
        raise RuntimeError("watchdog isolation state probe failed")
    return tuple(row.strip() for row in rows)


def isolate_watchdog(client):
    """Fail closed unless both watchdog units cannot restart the panel."""
    command(client, "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.timer)\" != not-found ]; then sudo systemctl disable --runtime --now comfy-panel-watchdog.timer; sudo systemctl disable --now comfy-panel-watchdog.timer; fi")
    command(client, "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.service)\" != not-found ]; then sudo systemctl disable --runtime --now comfy-panel-watchdog.service; sudo systemctl disable --now comfy-panel-watchdog.service; sudo systemctl stop comfy-panel-watchdog.service; fi")
    command(client, "if [ \"$(systemctl show --property LoadState --value comfy-panel-watchdog.service)\" != not-found ]; then sudo systemctl mask --runtime comfy-panel-watchdog.service; fi")
    fsync_systemd_unit_state(client)
    timer_active, timer_enabled, service_active, service_enabled = watchdog_isolation_state(client)
    if (timer_active != "inactive"
            or timer_enabled not in {"disabled", "masked", "masked-runtime", "not-found"}
            or service_active != "inactive"
            or service_enabled not in {"static", "masked", "masked-runtime", "not-found"}):
        raise RuntimeError(
            "watchdog isolation failed: "
            f"timer={timer_active}/{timer_enabled} "
            f"service={service_active}/{service_enabled}"
        )


def capture_watchdog_state(client):
    """Snapshot supported unit bytes/modes/state and reject custom link topology."""
    script = """import base64,json,os,pathlib,shlex,stat,subprocess
def unit(path):
    p=pathlib.Path(path)
    if p.is_symlink(): return False,'',None
    if not p.exists(): return False,'',None
    if not p.is_file(): raise RuntimeError('watchdog target is not a regular file: '+str(p))
    info=p.stat()
    if info.st_uid != 0 or info.st_gid != 0: raise RuntimeError('watchdog target must be root-owned: '+str(p))
    return True,base64.b64encode(p.read_bytes()).decode(),stat.S_IMODE(info.st_mode)
def systemctl(*args):
    r=subprocess.run(['systemctl',*args],text=True,capture_output=True)
    return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ''
def related_links():
    names={'comfy-panel-watchdog.service','comfy-panel-watchdog.timer'};result={}
    for raw_root in ('/etc/systemd/system','/run/systemd/system'):
        root=pathlib.Path(raw_root)
        if not root.is_dir(): continue
        for current,dirs,files in os.walk(root,followlinks=False):
            for name in dirs+files:
                path=pathlib.Path(current)/name
                if not path.is_symlink(): continue
                target=os.readlink(path)
                if path.name not in names and pathlib.PurePosixPath(target).name not in names: continue
                if path.lstat().st_uid!=0 or path.lstat().st_gid!=0: raise RuntimeError('watchdog systemd link must be root-owned: '+str(path))
                resolved=str((path.parent/pathlib.Path(target)).resolve(strict=False)) if not pathlib.Path(target).is_absolute() else str(pathlib.Path(target).resolve(strict=False))
                result[str(path)]=resolved
    return result
service_exists,service_b64,service_mode=unit('/etc/systemd/system/comfy-panel-watchdog.service')
timer_exists,timer_b64,timer_mode=unit('/etc/systemd/system/comfy-panel-watchdog.timer')
executable_exists,executable_b64,executable_mode=unit('/usr/local/libexec/comfy-panel-watchdog.py')
service_active=systemctl('is-active','comfy-panel-watchdog.service');service_enabled=systemctl('is-enabled','comfy-panel-watchdog.service')
timer_active=systemctl('is-active','comfy-panel-watchdog.timer');timer_enabled=systemctl('is-enabled','comfy-panel-watchdog.timer')
for unit,path,exists,enabled in (
    ('comfy-panel-watchdog.service','/etc/systemd/system/comfy-panel-watchdog.service',service_exists,service_enabled),
    ('comfy-panel-watchdog.timer','/etc/systemd/system/comfy-panel-watchdog.timer',timer_exists,timer_enabled),
):
    fragment=systemctl('show','--property','FragmentPath','--value',unit)
    dropins=shlex.split(systemctl('show','--property','DropInPaths','--value',unit))
    allowed_fragments={'',path}
    if enabled=='masked-runtime': allowed_fragments.add('/run/systemd/system/'+unit)
    if dropins or fragment not in allowed_fragments: raise RuntimeError('unsupported watchdog FragmentPath/DropInPaths: '+unit)
    if exists and fragment!=path: raise RuntimeError('watchdog effective fragment does not match captured file: '+unit)
    if fragment and pathlib.Path(fragment).is_symlink() and enabled not in {'masked','masked-runtime'}: raise RuntimeError('unexpected watchdog fragment symlink: '+unit)
    if fragment and not pathlib.Path(fragment).is_symlink():
        data=pathlib.Path(fragment).read_bytes().decode('utf-8')
        for raw in data.splitlines():
            line=raw.strip()
            if not line or line.startswith(('#',';')) or '=' not in line: continue
            key,value=(part.strip() for part in line.split('=',1))
            if key in {'Alias','Also'} and value: raise RuntimeError('unsupported watchdog install topology: '+unit)
expected={}
if timer_enabled=='enabled': expected['/etc/systemd/system/timers.target.wants/comfy-panel-watchdog.timer']='/etc/systemd/system/comfy-panel-watchdog.timer'
elif timer_enabled=='enabled-runtime': expected['/run/systemd/system/timers.target.wants/comfy-panel-watchdog.timer']='/etc/systemd/system/comfy-panel-watchdog.timer'
elif timer_enabled=='masked': expected['/etc/systemd/system/comfy-panel-watchdog.timer']='/dev/null'
elif timer_enabled=='masked-runtime': expected['/run/systemd/system/comfy-panel-watchdog.timer']='/dev/null'
if service_enabled=='masked': expected['/etc/systemd/system/comfy-panel-watchdog.service']='/dev/null'
elif service_enabled=='masked-runtime': expected['/run/systemd/system/comfy-panel-watchdog.service']='/dev/null'
elif service_enabled in {'enabled','enabled-runtime'}: raise RuntimeError('custom watchdog service enablement cannot be restored exactly')
links=related_links()
if links!=expected: raise RuntimeError('custom watchdog systemd link topology cannot be restored exactly')
print(json.dumps({'service_exists':service_exists,'service_b64':service_b64,'service_mode':service_mode,
                  'timer_exists':timer_exists,'timer_b64':timer_b64,'timer_mode':timer_mode,
                  'executable_exists':executable_exists,'executable_b64':executable_b64,'executable_mode':executable_mode,
                  'service_active':service_active,'service_enabled':service_enabled,
                  'timer_enabled':timer_enabled,'timer_active':timer_active}))
"""
    state = json.loads(command(client, "python3 -c " + shlex.quote(script)))
    return validate_watchdog_state(state)


def validate_watchdog_state(state):
    """Reject snapshots that cannot be restored and verified exactly."""
    if not isinstance(state, dict) or set(state) != WATCHDOG_STATE_KEYS:
        raise RuntimeError("invalid watchdog state snapshot")
    for exists_key, data_key, mode_key in (
        ("service_exists", "service_b64", "service_mode"),
        ("timer_exists", "timer_b64", "timer_mode"),
        ("executable_exists", "executable_b64", "executable_mode"),
    ):
        exists = state.get(exists_key)
        data = state.get(data_key)
        mode = state.get(mode_key)
        if type(exists) is not bool or not isinstance(data, str):
            raise RuntimeError("invalid watchdog file snapshot")
        if exists:
            if not isinstance(mode, int) or isinstance(mode, bool) or not (0 <= mode <= 0o7777):
                raise RuntimeError("invalid watchdog file mode")
            try:
                base64.b64decode(data.encode("ascii"), validate=True)
            except Exception as error:
                raise RuntimeError("invalid watchdog file bytes") from error
        elif data != "" or mode is not None:
            raise RuntimeError("invalid absent watchdog file snapshot")
    for key in ("service_active", "timer_active"):
        if state.get(key) not in WATCHDOG_RESTORABLE_ACTIVITY:
            raise RuntimeError(f"watchdog {key} state cannot be restored exactly")
    for key in ("service_enabled", "timer_enabled"):
        if state.get(key) not in WATCHDOG_RESTORABLE_ENABLEMENT:
            raise RuntimeError(f"watchdog {key} state cannot be restored exactly")
    return state


def verify_watchdog_state(client, expected):
    """Read back every captured watchdog property after restoration."""
    actual = capture_watchdog_state(client)
    mismatches = [key for key in sorted(WATCHDOG_STATE_KEYS)
                  if actual.get(key) != expected.get(key)]
    if mismatches:
        raise RuntimeError(
            "watchdog restore verification mismatch: " + ", ".join(mismatches)
        )


def restore_watchdog_state(client, state):
    """Restore the exact previous unit files and their enable/activity state."""
    validate_watchdog_state(state)
    command(client, "sudo systemctl disable --runtime --now comfy-panel-watchdog.timer comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl unmask --runtime comfy-panel-watchdog.service comfy-panel-watchdog.timer || true")
    command(client, "sudo systemctl unmask comfy-panel-watchdog.service comfy-panel-watchdog.timer || true")
    for exists_key, data_key, mode_key, remote in (
        ("service_exists", "service_b64", "service_mode", WATCHDOG_SERVICE_UNIT),
        ("timer_exists", "timer_b64", "timer_mode", WATCHDOG_TIMER_UNIT),
        ("executable_exists", "executable_b64", "executable_mode", WATCHDOG_EXECUTABLE),
    ):
        if state.get(exists_key):
            encoded = str(state.get(data_key) or "")
            mode = state.get(mode_key)
            if not isinstance(mode, int) or isinstance(mode, bool) or not (0 <= mode <= 0o7777):
                raise RuntimeError(f"invalid watchdog file mode: {remote}")
            script = (
                "import base64,os,pathlib,uuid;"
                f"path=pathlib.Path({remote!r});"
                "tmp=path.with_name(path.name+'.restore-'+uuid.uuid4().hex);"
                f"data=base64.b64decode({encoded!r});"
                "f=open(tmp,'wb');f.write(data);f.flush();os.fsync(f.fileno());f.close();"
                f"os.chmod(tmp,{mode});os.chown(tmp,0,0);os.replace(tmp,path);"
                "f=open(path,'rb');os.fsync(f.fileno());f.close();"
                "d=os.open(str(path.parent),os.O_RDONLY);os.fsync(d);os.close(d)"
            )
            command(client, "sudo python3 -c " + shlex.quote(script))
        else:
            command(client, "sudo rm -f " + shlex.quote(remote))
            parent = str(pathlib.PurePosixPath(remote).parent)
            script = (
                "import os;"
                f"d=os.open({parent!r},os.O_RDONLY);os.fsync(d);os.close(d)"
            )
            command(client, "sudo python3 -c " + shlex.quote(script))
    command(client, "sudo systemctl daemon-reload")

    enabled = str(state.get("timer_enabled") or "")
    active = str(state.get("timer_active") or "")
    if enabled == "masked":
        command(client, "sudo systemctl mask comfy-panel-watchdog.timer")
    elif enabled == "masked-runtime":
        command(client, "sudo systemctl mask --runtime comfy-panel-watchdog.timer")
    elif enabled in {"enabled", "enabled-runtime"}:
        enable_flag = "--runtime " if enabled == "enabled-runtime" else ""
        command(client, f"sudo systemctl enable {enable_flag}comfy-panel-watchdog.timer")
    if active in {"active", "activating", "reloading"}:
        command(client, "sudo systemctl start comfy-panel-watchdog.timer")
    else:
        command(client, "sudo systemctl stop comfy-panel-watchdog.timer || true")
    service_active = str(state.get("service_active") or "")
    service_enabled = str(state.get("service_enabled") or "")
    if service_enabled == "masked":
        command(client, "sudo systemctl mask comfy-panel-watchdog.service")
    elif service_enabled == "masked-runtime":
        command(client, "sudo systemctl mask --runtime comfy-panel-watchdog.service")
    elif service_enabled in {"enabled", "enabled-runtime"}:
        enable_flag = "--runtime " if service_enabled == "enabled-runtime" else ""
        command(client, f"sudo systemctl enable {enable_flag}comfy-panel-watchdog.service")
    if service_active in {"active", "activating", "reloading"}:
        command(client, "sudo systemctl start comfy-panel-watchdog.service")
    else:
        command(client, "sudo systemctl stop comfy-panel-watchdog.service || true")
    fsync_systemd_unit_state(client)
    verify_watchdog_state(client, state)


def remove_watchdog_units(client):
    command(client, "sudo systemctl disable --runtime --now comfy-panel-watchdog.timer comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl disable --now comfy-panel-watchdog.timer comfy-panel-watchdog.service || true")
    command(client, "sudo systemctl unmask --runtime comfy-panel-watchdog.timer comfy-panel-watchdog.service || true")
    command(client, "sudo rm -f /etc/systemd/system/comfy-panel-watchdog.service /etc/systemd/system/comfy-panel-watchdog.timer /usr/local/libexec/comfy-panel-watchdog.py")
    command(client, "sudo systemctl daemon-reload")


def deploy(files, payloads, public_base=PUBLIC_BASE,
           bootstrap_drain_contract=False):
    """Stage all files, verify, swap, read back, health-check; rollback on failure."""
    if set(payloads) != set(files) or any(not isinstance(data, bytes)
                                          for data in payloads.values()):
        raise RuntimeError("immutable release payload set is invalid")
    require_public_idle(public_base, phase="preflight")
    # Imported and connection metadata/key read only after fail-closed local preflight.
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
    deploy_key = paramiko.Ed25519Key.from_private_key_file(
        str(DEPLOY_SSH_KEY_PATH)
    )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedSHA256Policy())
    sftp = None
    remote_paths = list(files.values())
    transaction = new_release_transaction()
    lock_acquired = False
    rollback_uncertain = False
    watchdog_state = None
    watchdog_isolated = False
    drain_enabled = False
    start_draining_set = False
    bootstrap_snapshot_ready = False
    bootstrap_fence_maybe_armed = False
    release_committed = False
    try:
        client.connect(
            creds["host"], port=int(creds["port"]), username=creds["user"],
            pkey=deploy_key, timeout=30,
            allow_agent=False, look_for_keys=False,
        )
        configure_ssh_transport(client)
        # Owner-verified cleanup is safe even when the acquire response is lost.
        lock_acquired = True
        acquire_release_lock(client, transaction)
        if bootstrap_drain_contract:
            require_bootstrap_drain_contract_absent(client)
            require_bootstrap_fence_capability_absent(client)
            # Pre-mark the snapshot because a lost SSH response leaves its
            # completion uncertain. Never unlock that state without verification.
            rollback_uncertain = True
            bootstrap_snapshot_ready = True
            snapshot_bootstrap_drain_contract(client, transaction)
            rollback_uncertain = False
        else:
            require_persistent_release_drain_contract(client)
        require_release_start_draining_unset(client)
        watchdog_state = capture_watchdog_state(client)
        remote_parent_paths = sorted({str(pathlib.PurePosixPath(remote).parent) for remote in remote_paths})
        command(client, "mkdir -p -- " + " ".join(shlex.quote(path) for path in remote_parent_paths))
        sftp = client.open_sftp()
        for local, remote in files.items():
            stage_file_resilient(client, sftp, local, remote, transaction, payloads[local])

        staged_server = transaction_file(transaction, REMOTE_ROOT + "/server.py", "stage")
        command(client, f"python3 -m py_compile {shlex.quote(staged_server)}")
        staged_config = transaction_file(transaction, REMOTE_ROOT + "/config.json", "stage")
        command(client, "python3 -c " + shlex.quote(
            f"import json; json.load(open({staged_config!r}, encoding='utf-8'))"
        ))
        release_manifest = backup_release(client, sftp, remote_paths, transaction)
        write_transaction_phase(client, transaction, "prepared")

        require_public_idle(public_base, phase="pre-stop")
        rollback_uncertain = True
        try:
            # Arm restart-time draining first so a spontaneous service restart
            # anywhere in the preparation window cannot reopen admission.
            start_draining_set = True
            set_release_start_draining(client, True)
            if not bootstrap_drain_contract:
                # A lost response can leave the server draining. Mark the state
                # uncertain before the POST so failure handling always retries off.
                drain_enabled = True
                enable_remote_release_drain(client)
            watchdog_isolated = True
            isolate_watchdog(client)
            if bootstrap_drain_contract:
                # Pre-mark because a lost enable response can still leave the
                # persistent systemd/nft fence active.
                bootstrap_fence_maybe_armed = True
                arm_bootstrap_fence(client)
                require_loopback_idle(
                    client, phase="fenced-pre-stop",
                    samples=IDLE_STABILITY_CHECKS,
                    interval=IDLE_STABILITY_INTERVAL,
                )
        except BaseException as preparation_error:
            cleanup_errors = []
            if isinstance(preparation_error, WatchdogRestoreUncertain):
                cleanup_errors.append(f"watchdog: {preparation_error}")
            if watchdog_isolated:
                try:
                    restore_watchdog_state(client, watchdog_state)
                    watchdog_isolated = False
                except BaseException as error:
                    cleanup_errors.append(f"watchdog: {error}")
            if drain_enabled:
                try:
                    set_remote_release_drain(client, False)
                    drain_enabled = False
                except BaseException as error:
                    cleanup_errors.append(f"release drain: {error}")
            if bootstrap_snapshot_ready:
                try:
                    restore_bootstrap_drain_contract(client, transaction)
                    bootstrap_snapshot_ready = False
                    start_draining_set = False
                except BaseException as error:
                    cleanup_errors.append(f"bootstrap drain contract: {error}")
            elif start_draining_set:
                try:
                    set_release_start_draining(client, False)
                    start_draining_set = False
                except BaseException as error:
                    cleanup_errors.append(f"start-draining drop-in: {error}")
            if bootstrap_fence_maybe_armed and not cleanup_errors:
                try:
                    # Restore all legacy state before reopening public admission.
                    disarm_bootstrap_fence(client)
                    bootstrap_fence_maybe_armed = False
                except BaseException as error:
                    cleanup_errors.append(f"bootstrap admission fence: {error}")
            if cleanup_errors:
                try:
                    emergency_stop_after_failed_release(client)
                except BaseException as error:
                    cleanup_errors.append(f"emergency stop: {error}")
                raise WatchdogRestoreUncertain(
                    "pre-stop release preparation could not be restored: "
                    + "; ".join(cleanup_errors)
                ) from preparation_error
            rollback_uncertain = False
            raise
        try:
            if bootstrap_drain_contract:
                if probe_bootstrap_fence(client) != "active":
                    raise RuntimeError("bootstrap fence was lost before panel stop")
                stop_panel_resilient(client)
            else:
                command(client, "sudo systemctl stop comfy-panel", timeout=240)
            drain_enabled = False
            write_transaction_phase(client, transaction, "swapping")
            if bootstrap_drain_contract:
                install_bootstrap_drain_contract(client, transaction)
                require_persistent_release_drain_contract(client)
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
                fsync_remote_file(client, remote)

            for local, remote in files.items():
                local_data = payloads[local]
                with sftp.open(remote, "rb") as handle:
                    live_data = handle.read()
                if live_data != local_data:
                    raise RuntimeError(f"live mismatch: {local}")
                print(local.name, len(local_data), hashlib.sha256(local_data).hexdigest())

            command(client, "sudo systemctl start comfy-panel", timeout=240)
            drain_enabled = True
            wait_for_remote_release_drain(client)
            if bootstrap_drain_contract:
                disarm_bootstrap_fence(client)
                bootstrap_fence_maybe_armed = False
            live = wait_for_live(public_base, timeout=60)
            try:
                health = fetch_json(public_base, "/api/health")
            except Exception as error:
                health = {"ok": False, "error": str(error)[:200]}
            if not isinstance(health, dict) or health.get("dreamapi_configured") is not True:
                raise RuntimeError("public DreamAPI channel is not configured")
            expected_creator = payloads[BASE / "static" / "index.html"]
            expected_realism = payloads[BASE / "static" / "realism.html"]
            expected_preview = payloads[
                BASE / "static" / "previews" / "style-retro-manga-luxury.webp"
            ]
            realism, home, creator, creator_preview = verify_public_large_responses(
                public_base, expected_creator, expected_preview,
                expected_realism=expected_realism,
            )
            workflows = fetch_json(public_base, "/api/workflows")
            names = {str(item.get("name") or "") for item in workflows if isinstance(item, dict)}
            if b"/api/workflow-generate" not in realism or b"/realism" not in home:
                raise RuntimeError("public route markers missing")
            if not all(marker in creator for marker in (
                b"retro_manga_luxury", b"style-retro-manga-luxury.webp",
                b"genApiBtn", b"apiDrawerOpen", b"gpt-image-2.5-flare", "API结果".encode("utf-8"),
                b"style221", b"style222",
            )):
                raise RuntimeError("public creator style/API markers missing")
            verify_public_creator_config(public_base, creator, payloads)
            if creator_preview != expected_preview:
                raise RuntimeError("public creator preview mismatch")
            if not set(TARGET_WORKFLOW_NAMES).issubset(names):
                raise RuntimeError("public workflow list missing target workflows")
            if not set(UPLOADED_WORKFLOW_NAMES.values()).issubset(names):
                raise RuntimeError("public workflow list missing uploaded workflows")
            health = require_dreamapi_release_health(
                fetch_json(public_base, "/api/health")
            )
            install_watchdog_units(client)
            # From this point the release is fully verified. Persist commit before
            # reopening either restart-time or current-process admission.
            release_committed = True
            write_transaction_phase(client, transaction, "committed")
            set_release_start_draining(client, False)
            start_draining_set = False
            set_remote_release_drain(client, False)
            drain_enabled = False
            cleanup_release_transaction(client, transaction)
            rollback_uncertain = False
            print("LIVE", json.dumps(live, ensure_ascii=False))
            print("COMFY_DIAGNOSTIC", json.dumps(health, ensure_ascii=False))
            print("PUBLIC_MARKERS_OK")
        except BaseException:
            if release_committed:
                # The deployed bytes passed every check. Preserve the lock when
                # post-commit maintenance cleanup cannot be verified.
                rollback_uncertain = True
                if start_draining_set:
                    try:
                        set_release_start_draining(client, False)
                        start_draining_set = False
                    except BaseException:
                        pass
                if drain_enabled:
                    try:
                        set_remote_release_drain(client, False)
                        drain_enabled = False
                    except BaseException:
                        pass
                raise
            try:
                isolate_watchdog(client)
                if bootstrap_drain_contract:
                    # Reconcile even a partially removed fence before restoring
                    # legacy bytes; the local flag cannot prove remote state.
                    bootstrap_fence_maybe_armed = True
                    arm_bootstrap_fence(client)
                write_transaction_phase(client, transaction, "rolling-back")
                rollback_release(
                    client, sftp, remote_paths, transaction,
                    public_base=public_base,
                    restore_bootstrap=bootstrap_snapshot_ready,
                    bootstrap_fence=(
                        bootstrap_drain_contract and bootstrap_fence_maybe_armed
                    ),
                )
                if bootstrap_snapshot_ready:
                    bootstrap_snapshot_ready = False
                    start_draining_set = False
                restore_watchdog_state(client, watchdog_state)
                watchdog_isolated = False
                if start_draining_set:
                    set_release_start_draining(client, False)
                    start_draining_set = False
                if not bootstrap_drain_contract:
                    set_remote_release_drain(client, False)
                else:
                    disarm_bootstrap_fence(client)
                    bootstrap_fence_maybe_armed = False
                    legacy_live = wait_for_live(
                        public_base, timeout=60, allow_legacy=True,
                    )
                    if not legacy_live.get("ok"):
                        raise RuntimeError(str(legacy_live))
                    drain_enabled = False
                write_transaction_phase(client, transaction, "rolled-back")
                cleanup_release_transaction(client, transaction)
            except BaseException as rollback_error:
                # An uncertain rollback must remain stopped; restoring an active
                # watchdog or removing the persistent drain could expose a mixed release.
                rollback_uncertain = True
                if bootstrap_drain_contract:
                    try:
                        bootstrap_fence_maybe_armed = True
                        arm_bootstrap_fence(client)
                    except BaseException as fence_error:
                        rollback_error.add_note(
                            f"bootstrap rollback fence restore failed: {fence_error}"
                        )
                try:
                    emergency_stop_after_failed_release(client)
                except BaseException as stop_error:
                    rollback_error.add_note(str(stop_error))
                try:
                    write_transaction_phase(client, transaction, "rollback-failed")
                except BaseException:
                    pass
                raise
            else:
                rollback_uncertain = False
            raise
    finally:
        cleanup_errors = []
        if sftp is not None:
            try:
                sftp.close()
            except BaseException as error:
                cleanup_errors.append(error)
        try:
            if lock_acquired and not rollback_uncertain:
                try:
                    release_release_lock(client, transaction)
                except BaseException as error:
                    cleanup_errors.append(error)
        finally:
            try:
                client.close()
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors and sys.exc_info()[0] is None:
            primary = cleanup_errors[0]
            for secondary in cleanup_errors[1:]:
                primary.add_note(str(secondary))
            raise primary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fail-closed realism release")
    parser.add_argument("--execute", action="store_true", help="allow remote mutation after all gates pass")
    parser.add_argument(
        "--allow-unauthenticated-public", action="store_true",
        help="explicitly accept the current public no-auth risk for this release",
    )
    parser.add_argument(
        "--bootstrap-drain-contract", action="store_true",
        help="one-time migration for a verified idle legacy server without the drain endpoint",
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
    reviewed_head = require_clean_git()
    run_release_tests()
    require_clean_git(expected_head=reviewed_head)
    files = release_files()
    payloads = release_payloads_from_head(files, reviewed_head)
    deploy(
        files, payloads, public_base=args.public_base,
        bootstrap_drain_contract=args.bootstrap_drain_contract,
    )
    print("REALISM_RELEASE_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
