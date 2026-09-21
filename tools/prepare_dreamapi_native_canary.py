#!/usr/bin/env python3
"""Stage and run a loopback-only production DreamAPI canary."""

import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time
import uuid

BASE = pathlib.Path(__file__).resolve().parents[1]
_RELEASE_SPEC = importlib.util.spec_from_file_location(
    "comfy_panel_deploy_realism_release", BASE / "tools" / "deploy_realism_release.py"
)
release = importlib.util.module_from_spec(_RELEASE_SPEC)
_RELEASE_SPEC.loader.exec_module(release)
DEFAULT_STATE = BASE / "panel_data" / "dreamapi-native-canary-state.json"
DEFAULT_OUTPUT = BASE / "audit" / "dreamapi_native_canary_20260915"
REMOTE_PARENT = "/home/admin/.comfy-panel-canary"
CANARY_PORT = 8289


def _atomic_json(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _connect(credentials, ssh_key):
    import paramiko

    class PinnedPolicy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            actual = "SHA256:" + base64.b64encode(
                hashlib.sha256(key.asbytes()).digest()
            ).decode("ascii").rstrip("=")
            if not hmac.compare_digest(actual, release.SSH_HOST_KEY_SHA256):
                raise paramiko.SSHException("SSH host key mismatch")

    creds = json.loads(pathlib.Path(credentials).read_text(encoding="utf-8"))
    key = paramiko.Ed25519Key.from_private_key_file(str(ssh_key))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedPolicy())
    client.connect(
        creds["host"], port=int(creds["port"]), username=creds["user"],
        pkey=key, timeout=30, allow_agent=False, look_for_keys=False,
    )
    release.configure_ssh_transport(client)
    return client


def _mkdirs(sftp, path):
    current = pathlib.PurePosixPath("/")
    for part in pathlib.PurePosixPath(path).parts[1:]:
        current /= part
        try:
            sftp.stat(str(current))
        except OSError:
            sftp.mkdir(str(current), 0o700)


def _upload(sftp, remote, data, mode=0o600):
    _mkdirs(sftp, str(pathlib.PurePosixPath(remote).parent))
    tmp = remote + ".tmp-" + uuid.uuid4().hex
    with sftp.open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
    sftp.chmod(tmp, mode)
    sftp.posix_rename(tmp, remote)
    with sftp.open(remote, "rb") as handle:
        if handle.read() != data:
            raise RuntimeError("canary upload readback mismatch: " + remote)


def _head_and_payloads():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=BASE, text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("invalid candidate commit")
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *release.RELEASE_RELATIVE_PATHS],
        cwd=BASE,
    )
    if changed.returncode:
        raise RuntimeError("release runtime differs from HEAD")
    relative_paths = tuple(dict.fromkeys((
        "config.json", "static/index.html", *release.NATIVE_RUNTIME_PAYLOAD_FILES,
        *release.RELEASE_RELATIVE_PATHS,
    )))
    files = {
        BASE / relative: release.REMOTE_ROOT + "/" + relative
        for relative in relative_paths
    }
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError("missing canary files: " + ", ".join(missing))
    return head, files, release.release_payloads_from_head(files, head)


def candidate_launch_command(root, unit, candidate_key=False, connection_mode="workstation"):
    if connection_mode not in {"direct", "workstation"}:
        raise ValueError("invalid canary connection mode")
    return [
        "sudo", "systemd-run", "--unit=" + unit, "--collect",
        "--property=User=admin", "--property=WorkingDirectory=" + root,
        "--property=EnvironmentFile=-/etc/comfy-panel.d/dreamapi.env",
        "--property=EnvironmentFile=/etc/comfy-panel/release.env",
        "--property=EnvironmentFile=/home/admin/comfy-panel/panel.env",
        *(["--property=EnvironmentFile=" + root + "/dreamapi-canary.env"] if candidate_key else []),
        "/usr/bin/env", "PANEL_BIND=127.0.0.1", f"PANEL_PORT={CANARY_PORT}",
        "PANEL_DIR=" + root + "/data", "PANEL_RELEASE_DRAIN_ON_START=0",
        "DREAMAPI_EGRESS_URL=http://127.0.0.1:8198/dreamapi/images/generations",
        "DREAMAPI_CONNECTION_MODE=" + connection_mode,
        "/usr/bin/python3", root + "/server.py",
    ]


def _remove_remote_candidate(client, root, unit):
    if (not re.fullmatch(
            r"/home/admin/\.comfy-panel-canary/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{10}", root)
            or not re.fullmatch(
                r"comfy-panel-canary-[0-9]{8}t[0-9]{6}z-[0-9a-f]{10}", unit)):
        raise RuntimeError("invalid candidate cleanup identity")
    release.command(client, "sudo systemctl stop " + shlex.quote(unit) + " || true")
    remove = (
        "import pathlib,shutil;"
        f"root=pathlib.Path({root!r});parent=pathlib.Path({REMOTE_PARENT!r});"
        "resolved=root.resolve();"
        "(_ for _ in ()).throw(RuntimeError('invalid cleanup root')) if resolved.parent!=parent else None;"
        "shutil.rmtree(resolved) if resolved.exists() else None"
    )
    release.command(client, "python3 -c " + shlex.quote(remove))


def prepare(args):
    state_path = pathlib.Path(args.state)
    if state_path.exists():
        raise RuntimeError("canary state already exists; collect or clean it first")
    head, files, payloads = _head_and_payloads()
    suffix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + head[:10]
    root = REMOTE_PARENT + "/" + suffix
    unit = "comfy-panel-canary-" + suffix.lower()
    client = _connect(args.credentials, args.ssh_key)
    sftp = None
    root_created = False
    try:
        create = (
            "import pathlib;"
            f"parent=pathlib.Path({REMOTE_PARENT!r});root=pathlib.Path({root!r});"
            "parent.mkdir(mode=0o700,parents=True,exist_ok=True);"
            "(_ for _ in ()).throw(RuntimeError('candidate root already exists')) if root.exists() else None;"
            "root.mkdir(mode=0o700)"
        )
        release.command(client, "python3 -c " + shlex.quote(create))
        root_created = True
        port_probe = (
            "import socket;"
            "s=socket.socket();"
            f"s.bind(('127.0.0.1',{CANARY_PORT}));s.close()"
        )
        release.command(client, "python3 -c " + shlex.quote(port_probe))
        sftp = client.open_sftp()
        for local, remote_live in files.items():
            relative = pathlib.PurePosixPath(remote_live).relative_to(release.REMOTE_ROOT)
            _upload(sftp, str(pathlib.PurePosixPath(root) / relative), payloads[local])
        client_source = (BASE / "tools" / "dreamapi_native_canary_client.py").read_bytes()
        _upload(sftp, root + "/tools/dreamapi_native_canary_client.py", client_source, 0o700)
        candidate_key = bool(getattr(args, "dreamapi_key_file", None))
        if candidate_key:
            key = pathlib.Path(args.dreamapi_key_file).read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,256}", key):
                raise RuntimeError("invalid candidate key format")
            _upload(sftp, root + "/dreamapi-canary.env", ("DREAMAPI_KEY=" + key + "\n").encode(), 0o600)
        connection_mode = getattr(args, "connection_mode", "workstation")
        command = candidate_launch_command(root, unit, candidate_key, connection_mode)
        release.command(client, " ".join(shlex.quote(item) for item in command))
        deadline = time.time() + 30
        health = None
        while time.time() < deadline:
            probe = (
                "import json,urllib.request;"
                f"print(urllib.request.urlopen('http://127.0.0.1:{CANARY_PORT}/api/health',timeout=3).read().decode())"
            )
            try:
                health = json.loads(release.command(client, "python3 -c " + shlex.quote(probe)))
                if health.get("dreamapi_contract_match") is True:
                    break
            except Exception:
                time.sleep(1)
        if not isinstance(health, dict):
            raise RuntimeError("candidate health did not become available")
        required = {
            "dreamapi_configured": True,
            "dreamapi_transport_ready": True,
            "dreamapi_connection_mode": connection_mode,
            "dreamapi_contract_match": True,
            "dreamapi_uncertainty_fence": False,
            "draining": False,
            "api_busy": False,
        }
        if any(health.get(key) != value for key, value in required.items()):
            raise RuntimeError("candidate DreamAPI health is not ready")
        state = {
            "phase": "prepared", "candidate_commit": head,
            "runtime_payload_sha256": release.git_runtime_payload_sha256(head, files=release.NATIVE_RUNTIME_PAYLOAD_FILES),
            "remote_root": root, "unit": unit, "port": CANARY_PORT,
            "contract_sha256": health.get("dreamapi_contract_sha256"),
            "connection_mode": connection_mode,
            "model": getattr(args, "model", "gpt-image-2.5-flare"),
            "prepared_at": time.time(),
        }
        _atomic_json(state_path, state)
        root_created = False
        print(json.dumps({key: state[key] for key in (
            "phase", "candidate_commit", "runtime_payload_sha256",
            "unit", "port", "contract_sha256",
        )}, indent=2))
    except BaseException as error:
        if root_created:
            try:
                cleanup_client = client
                transport = client.get_transport()
                if transport is None or not transport.is_active():
                    client.close()
                    cleanup_client = _connect(args.credentials, args.ssh_key)
                try:
                    _remove_remote_candidate(cleanup_client, root, unit)
                finally:
                    if cleanup_client is not client:
                        cleanup_client.close()
            except BaseException as cleanup_error:
                error.add_note("candidate cleanup failed: " + str(cleanup_error))
        raise
    finally:
        if sftp is not None:
            sftp.close()
        client.close()


def _invoke_client(args, mode):
    state_path = pathlib.Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if mode == "submit" and state.get("phase") != "prepared":
        raise RuntimeError("paid submit is not allowed from the current phase")
    if mode == "submit":
        state["phase"] = "submit_invoked_uncertain"
        state["submit_invoked_at"] = time.time()
        _atomic_json(state_path, state)
    root = str(state["remote_root"])
    port = int(state["port"])
    model = state.get("model", "gpt-image-2.5-flare")
    client_id = "native-images-" + str(state["candidate_commit"])[:12] + "-" + model + "-low-9x16"
    remote_mode = "submit" if mode == "submit" else "collect"
    command = [
        "/usr/bin/python3", root + "/tools/dreamapi_native_canary_client.py", remote_mode,
        "--base", f"http://127.0.0.1:{port}",
        "--state", root + "/canary-state.json",
        "--result", root + "/result.json",
        "--image", root + "/result.png",
        "--client-request-id", client_id,
        "--model", model,
    ]
    client = _connect(args.credentials, args.ssh_key)
    try:
        try:
            output = release.command(
                client, " ".join(shlex.quote(item) for item in command), timeout=720,
            )
        except RuntimeError:
            # Recover the terminal public result without another submission.
            sftp = client.open_sftp()
            try:
                with sftp.open(root + "/result.json", "rb") as handle:
                    terminal = json.loads(handle.read())
                if terminal.get("status") in {"error", "failed", "cancelled"}:
                    _atomic_json(pathlib.Path(args.output) / "failed-result.json", terminal)
                    state["phase"] = "failed"
                    state["terminal_status"] = terminal["status"]
                    _atomic_json(state_path, state)
            except OSError:
                pass
            finally:
                sftp.close()
            raise
        output_dir = pathlib.Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sftp = client.open_sftp()
        try:
            sftp.get(root + "/result.json", str(output_dir / "raw-result.json"))
            sftp.get(root + "/result.png", str(output_dir / (model.replace(".", "_") + "-low-9x16.png")))
        finally:
            sftp.close()
        state["phase"] = "collected"
        state["client_request_id"] = client_id
        state["collected_at"] = time.time()
        _atomic_json(state_path, state)
        print(output)
    finally:
        client.close()


def cleanup(args):
    state_path = pathlib.Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    root = str(state.get("remote_root") or "")
    unit = str(state.get("unit") or "")
    if (state.get("phase") not in {"prepared", "collected", "failed"}
            or not re.fullmatch(r"/home/admin/\.comfy-panel-canary/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{10}", root)
            or not re.fullmatch(r"comfy-panel-canary-[0-9]{8}t[0-9]{6}z-[0-9a-f]{10}", unit)):
        raise RuntimeError("canary cleanup target or phase is invalid")
    client = _connect(args.credentials, args.ssh_key)
    try:
        _remove_remote_candidate(client, root, unit)
        state["phase"] = "cleaned"
        state["cleaned_at"] = time.time()
        _atomic_json(state_path, state)
        print("CANARY_CLEANUP_OK")
    finally:
        client.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "submit", "collect", "cleanup"))
    parser.add_argument("--credentials", default=str(BASE / "tools" / "creds.json"))
    parser.add_argument("--ssh-key", default=str(BASE / "tools" / "id_ed25519"))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dreamapi-key-file", help="private local key file, used only by the isolated candidate")
    parser.add_argument("--connection-mode", choices=("direct", "workstation"), default="workstation")
    parser.add_argument("--model", choices=("gpt-image-2", "gpt-image-2.5-flare"), default="gpt-image-2.5-flare")
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        prepare(args)
    elif args.mode in {"submit", "collect"}:
        _invoke_client(args, args.mode)
    else:
        cleanup(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
