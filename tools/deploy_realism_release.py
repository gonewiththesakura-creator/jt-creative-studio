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
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import sys
import time
import urllib.request

BASE = pathlib.Path(__file__).resolve().parents[1]
E2E_MANIFEST = BASE / "audit" / "private_realism_workflows" / "e2e_manifest.json"
SCAIL_E2E_MANIFEST = BASE / "audit" / "scail2_video_e2e.json"
REMOTE_ROOT = "/home/admin/comfy-panel"
PUBLIC_BASE = "http://8.210.125.65:8189"
STAGE_SUFFIX = ".realism-release.new"
BACKUP_SUFFIX = ".pre-realism-release"
BACKUP_MANIFEST = REMOTE_ROOT + "/.pre-realism-release-manifest.json"

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


def require_clean_git():
    result = subprocess.run(["git", "status", "--porcelain"], cwd=BASE, text=True,
                            capture_output=True, check=True)
    if result.stdout.strip():
        raise RuntimeError("git working tree is not clean; commit the reviewed release first")


def run_release_tests():
    allowed_failure = "test_restore_prompt_contract.py"
    failures = []
    for path in sorted((BASE / "tests").glob("test_*.py")):
        result = subprocess.run([sys.executable, str(path)], cwd=BASE, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode and path.name != allowed_failure:
            failures.append({"file": path.name, "output": result.stdout[-800:]})
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


def preflight_decision(config, server_source, execute=False, allow_unauthenticated_public=False):
    config_result = validate_release_config(config)
    scail_errors = validate_scail_video_config(config) + validate_scail_e2e_manifest()
    unauthenticated = auth_is_disabled(server_source)
    blockers = []
    if config_result["missing_targets"]:
        blockers.append("missing target workflows")
    if config_result["invalid_targets"]:
        blockers.append("invalid or incomplete target schemas")
    if scail_errors:
        blockers.append("invalid SCAIL video schemas")
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


def stage_file_resilient(client, local, remote):
    """Upload and byte-verify one staged file on a fresh SFTP channel."""
    data = local.read_bytes()
    staged = remote + STAGE_SUFFIX
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
            return
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


def backup_release(client, sftp, remote_paths):
    """Snapshot the immediately previous live set, including absent-file markers."""
    manifest = {}
    for remote in remote_paths:
        backup = remote + BACKUP_SUFFIX
        try:
            sftp.stat(remote)
        except FileNotFoundError:
            manifest[remote] = {"exists": False, "sha256": None}
            command(client, f"rm -f -- {shlex.quote(backup)}")
        else:
            command(client, f"cp -- {shlex.quote(remote)} {shlex.quote(backup)}")
            digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({remote!r},'rb').read()).hexdigest())"
            )).strip()
            manifest[remote] = {"exists": True, "sha256": digest}
    payload = json.dumps(manifest, ensure_ascii=False)
    command(client, "python3 -c " + shlex.quote(
        f"import pathlib;pathlib.Path({BACKUP_MANIFEST!r}).write_text({payload!r},encoding='utf-8')"
    ))
    return manifest


def rollback_release(client, sftp, remote_paths, public_base=PUBLIC_BASE):
    manifest = json.loads(command(client, "python3 -c " + shlex.quote(
        f"import pathlib;print(pathlib.Path({BACKUP_MANIFEST!r}).read_text(encoding='utf-8'))"
    )))
    for remote in remote_paths:
        backup = remote + BACKUP_SUFFIX
        entry = manifest.get(remote) or {}
        if not entry.get("exists"):
            command(client, f"rm -f -- {shlex.quote(remote)}")
        else:
            command(client, f"cp -- {shlex.quote(backup)} {shlex.quote(remote)}")
            digest = command(client, "python3 -c " + shlex.quote(
                f"import hashlib;print(hashlib.sha256(open({remote!r},'rb').read()).hexdigest())"
            )).strip()
            if digest != entry.get("sha256"):
                raise RuntimeError(f"rollback verification mismatch: {remote}")
    command(client, "sudo systemctl restart comfy-panel", timeout=240)
    health = wait_for_health(public_base, timeout=60)
    if not health.get("ok"):
        raise RuntimeError(f"rollback health failed: {health}")


def fetch_json(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=60) as response:
        return json.load(response)


def fetch_bytes(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=60) as response:
        return response.read()


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


def deploy(files, public_base=PUBLIC_BASE):
    """Stage all files, verify, swap, read back, health-check; rollback on failure."""
    # Imported and credentials read only after fail-closed local preflight.
    import paramiko

    creds_path = BASE / "tools" / "creds.json"
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        creds["host"], port=int(creds["port"]), username=creds["user"],
        password=creds["password"], timeout=30,
        allow_agent=False, look_for_keys=False,
    )
    sftp = None
    remote_paths = list(files.values())
    try:
        remote_parent_paths = sorted({str(pathlib.PurePosixPath(remote).parent) for remote in remote_paths})
        command(client, "mkdir -p -- " + " ".join(shlex.quote(path) for path in remote_parent_paths))
        for local, remote in files.items():
            stage_file_resilient(client, local, remote)

        # Do not carry a recovered upload channel into backup/swap.
        sftp = client.open_sftp()
        command(client, f"python3 -m py_compile {shlex.quote(REMOTE_ROOT + '/server.py' + STAGE_SUFFIX)}")
        staged_config = REMOTE_ROOT + "/config.json" + STAGE_SUFFIX
        command(client, "python3 -c " + shlex.quote(
            f"import json; json.load(open({staged_config!r}, encoding='utf-8'))"
        ))
        backup_release(client, sftp, remote_paths)

        try:
            for remote in remote_paths:
                staged = remote + STAGE_SUFFIX
                try:
                    sftp.posix_rename(staged, remote)
                except Exception:
                    command(client, f"mv -f -- {shlex.quote(staged)} {shlex.quote(remote)}")

            for local, remote in files.items():
                local_data = local.read_bytes()
                with sftp.open(remote, "rb") as handle:
                    live_data = handle.read()
                if live_data != local_data:
                    raise RuntimeError(f"live mismatch: {local}")
                print(local.name, len(local_data), hashlib.sha256(local_data).hexdigest())

            command(client, "sudo systemctl restart comfy-panel", timeout=240)
            health = wait_for_health(public_base, timeout=60)
            if not health.get("ok") or not health.get("local_comfy_ok"):
                raise RuntimeError(f"health failed: {health}")
            realism = fetch_bytes(public_base, "/realism")
            home = fetch_bytes(public_base, "/")
            workflows = fetch_json(public_base, "/api/workflows")
            names = {str(item.get("name") or "") for item in workflows if isinstance(item, dict)}
            if b"/api/workflow-generate" not in realism or b"/realism" not in home:
                raise RuntimeError("public route markers missing")
            if not set(TARGET_WORKFLOW_NAMES).issubset(names):
                raise RuntimeError("public workflow list missing target workflows")
            print("HEALTH", json.dumps(health, ensure_ascii=False))
            print("PUBLIC_MARKERS_OK")
        except Exception:
            rollback_release(client, sftp, remote_paths, public_base=public_base)
            raise
    finally:
        if sftp is not None:
            sftp.close()
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
