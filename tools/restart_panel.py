"""Restart comfy-panel systemd service so the new config.json is loaded."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)

def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=60)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    return o, e

o, e = run("sudo systemctl restart comfy-panel && sleep 3 && systemctl is-active comfy-panel")
print("restart:", o, e[:200])
o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/health")
print("health:", o[:200])
cli.close()
