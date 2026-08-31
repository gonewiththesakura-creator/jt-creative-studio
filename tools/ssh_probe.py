"""SSH probe + pubkey deploy for the public relay server (paramiko)."""
import json, os, sys, pathlib
import paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/tools")
creds = json.loads((BASE / "creds.json").read_text(encoding="utf-8"))

key_path = BASE / "id_ed25519.pub"
pubkey = key_path.read_text().strip()

cmds = [
    "whoami; id",
    "sudo -n true 2>&1 && echo SUDO_OK || echo SUDO_FAIL",
    "head -2 /etc/os-release",
    "python3 --version 2>&1; which python3 pip3 2>&1",
    "free -h | head -2",
    "df -h / | tail -1",
    "nvidia-smi 2>&1 | head -3; lspci 2>/dev/null | grep -iE 'vga|3d|nvidia' || echo NO_GPU_LSPCI",
    "ss -tlnp 2>/dev/null | head -30",
    "systemctl is-active tinyproxy 2>&1",
    "uptime",
]

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)
print("== CONNECTED ==")
for c in cmds:
    print(f"$ {c}")
    _, out, err = cli.exec_command(c, timeout=30)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    if o: print(o)
    if e: print("[stderr]", e[:300])
    print("---")

# deploy pubkey (idempotent)
cmd = f"""mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && grep -qF '{pubkey}' ~/.ssh/authorized_keys || echo '{pubkey}' >> ~/.ssh/authorized_keys; echo KEY_DEPLOYED; grep -c 'ed25519' ~/.ssh/authorized_keys"""
_, out, err = cli.exec_command(cmd, timeout=30)
print("$ deploy key")
print(out.read().decode(errors="replace").strip())
cli.close()
print("== DONE ==")
