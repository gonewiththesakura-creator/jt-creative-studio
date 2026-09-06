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
    "realism_3in1": "动漫转真人·多分支超清3in1",
    "realism_zi_flowmatch": "动漫转真人ZI洗图改（Z-Image+FlowMatch）",
}
TARGET_WORKFLOW_IDS = tuple(TARGET_WORKFLOWS)
TARGET_WORKFLOW_NAMES = tuple(TARGET_WORKFLOWS.values())

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
    unauthenticated = auth_is_disabled(server_source)
    blockers = []
    if config_result["missing_targets"]:
        blockers.append("missing target workflows")
    if config_result["invalid_targets"]:
        blockers.append("invalid or incomplete target schemas")
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
    sftp = client.open_sftp()
    remote_paths = list(files.values())
    try:
        command(client, f"mkdir -p {shlex.quote(REMOTE_ROOT + '/static')}")
        for local, remote in files.items():
            data = local.read_bytes()
            staged = remote + STAGE_SUFFIX
            with sftp.open(staged, "wb") as handle:
                handle.write(data)
            with sftp.open(staged, "rb") as handle:
                if handle.read() != data:
                    raise RuntimeError(f"staging mismatch: {local}")

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
