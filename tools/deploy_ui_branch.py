import hashlib
import json
import pathlib
import shlex

import paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
CREDS = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf8"))
REMOTE = "/home/admin/comfy-panel/static"
NAMES = [
    'promptgen.html',
    'index.html',
    'original_sketch.html',
    'original_graphic.html',
    'video.html',
]
FILES = [BASE / "static" / name for name in NAMES]


def remote_command(client, command):
    _, stdout, stderr = client.exec_command(command, timeout=60)
    code = stdout.channel.recv_exit_status()
    error = stderr.read().decode("utf8", "replace")
    if code:
        raise RuntimeError(f"remote command failed ({code}): {error}")


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(
    CREDS["host"],
    port=CREDS["port"],
    username=CREDS["user"],
    password=CREDS["password"],
    timeout=20,
    allow_agent=False,
    look_for_keys=False,
)
sftp = client.open_sftp()

try:
    # Stage and byte-verify every file before changing the live site.
    for src in FILES:
        dst = f"{REMOTE}/{src.name}"
        staged = dst + ".ui-polish.new"
        with sftp.open(staged, "wb") as handle:
            handle.write(src.read_bytes())
        with sftp.open(staged, "rb") as handle:
            assert handle.read() == src.read_bytes(), f"staging mismatch: {src.name}"

    # Preserve the complete pre-polish set once for rollback.
    for src in FILES:
        dst = f"{REMOTE}/{src.name}"
        backup = dst + ".pre-ui-polish"
        try:
            sftp.stat(backup)
        except FileNotFoundError:
            remote_command(client, f"cp -- {shlex.quote(dst)} {shlex.quote(backup)}")

    swapped = []
    try:
        # Each rename is atomic on the same filesystem. All files were staged first,
        # and the complete previous set is restored if any swap/verification fails.
        for src in FILES:
            dst = f"{REMOTE}/{src.name}"
            staged = dst + ".ui-polish.new"
            try:
                sftp.posix_rename(staged, dst)
            except Exception:
                remote_command(client, f"mv -f -- {shlex.quote(staged)} {shlex.quote(dst)}")
            swapped.append(src.name)

        for src in FILES:
            dst = f"{REMOTE}/{src.name}"
            with sftp.open(dst, "rb") as handle:
                remote = handle.read()
            local = src.read_bytes()
            assert remote == local, f"live mismatch: {src.name}"
            print(src.name, len(local), hashlib.sha256(local).hexdigest())
    except Exception:
        for name in NAMES:
            dst = f"{REMOTE}/{name}"
            backup = dst + ".pre-ui-polish"
            remote_command(client, f"cp -- {shlex.quote(backup)} {shlex.quote(dst)}")
        raise
finally:
    sftp.close()
    client.close()

print("STATIC_UI_POLISH_DEPLOY_OK")
