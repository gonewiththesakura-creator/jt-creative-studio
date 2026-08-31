"""Deploy comfy-panel to the relay server via SFTP + systemd."""
import json, secrets, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
REMOTE = "/home/admin/comfy-panel"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)

def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=60)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    if o: print(o)
    if e: print("[stderr]", e[:400])
    return o, e

# Read DEEPSEEK_API_KEY from local ComfyUI node .env (panel server needs it for RH translate)
ds_key = ""
env_path = pathlib.Path(r"D:/ComfyUI_Mie/ComfyUI/custom_nodes/ComfyUI-AnimaJT-ChineseLLM/.env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY="):
            ds_key = line.split("=", 1)[1].strip()
            break
print("DEEPSEEK_API_KEY:", ("set (" + ds_key[:6] + "...)" ) if ds_key else "NOT FOUND (translate will be identity)")

token_file = BASE / "PANEL_TOKEN.txt"
if token_file.exists():
    token = token_file.read_text(encoding="utf-8").strip()
    print("reusing existing token:", token[:6] + "..." + token[-4:])
else:
    token = secrets.token_urlsafe(24)
    print("generated token:", token[:6] + "..." + token[-4:])

run(f"mkdir -p {REMOTE}/templates {REMOTE}/static")
sftp = cli.open_sftp()
for local, remote in [
    (BASE / "server.py", f"{REMOTE}/server.py"),
    (BASE / "config.json", f"{REMOTE}/config.json"),
    (BASE / "_translate.py", f"{REMOTE}/_translate.py"),
]:
    sftp.put(str(local), remote)
    print("uploaded:", remote)
for f in (BASE / "static").glob("*"):
    if f.is_file():
        sftp.put(str(f), f"{REMOTE}/static/{f.name}")
        print("uploaded:", f"static/{f.name}")
for tpl in (BASE / "templates").glob("*.json"):
    sftp.put(str(tpl), f"{REMOTE}/templates/{tpl.name}")
    print("uploaded:", f"templates/{tpl.name}")
sftp.close()

unit = f"""[Unit]
Description=JT ComfyUI Remote Panel
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory={REMOTE}
Environment=PANEL_TOKEN={token}
Environment=COMFY_URL=http://127.0.0.1:8199
Environment=PANEL_PORT=8189
Environment=PANEL_DIR={REMOTE}/panel_data
Environment=DEEPSEEK_API_KEY={ds_key}
ExecStart=/usr/bin/python3 {REMOTE}/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
run(f"cat > /tmp/comfy-panel.service <<'UNITEOF'\n{unit}\nUNITEOF")
run("sudo mv /tmp/comfy-panel.service /etc/systemd/system/comfy-panel.service")
run("sudo systemctl daemon-reload")
run("sudo systemctl enable --now comfy-panel")
run("sleep 2; systemctl is-active comfy-panel")
run("curl -s --max-time 10 http://127.0.0.1:8189/api/health")

# persist token locally for the user
out = BASE / "PANEL_TOKEN.txt"
out.write_text(token, encoding="utf-8")
print("token saved to", out)
cli.close()
