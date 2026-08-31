"""Compare localhost vs public response on the relay server."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)

def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=60)
    return out.read().decode(errors="replace").strip(), err.read().decode(errors="replace").strip()

o, _ = run("curl -s http://127.0.0.1:8189/ | wc -c")
print("localhost:8189 / ->", o, "bytes")
o, _ = run("curl -s http://127.0.0.1:8189/ | grep -c navSwitch")
print("localhost:8189 / navSwitch ->", o)
o, _ = run("curl -s http://127.0.0.1:8189/ | grep -c '视频生成面板'")
print("localhost:8189 / video btn ->", o)
o, _ = run("curl -s http://127.0.0.1:8189/promptgen | wc -c")
print("localhost:8189 /promptgen ->", o, "bytes")
o, _ = run("curl -s http://127.0.0.1:8189/promptgen | grep -c navSwitch")
print("localhost:8189 /promptgen navSwitch ->", o)

# check listeners on 8189 + nginx config
o, _ = run("ss -tlnp | grep 8189")
print("listeners:", o)
o, _ = run("ps aux | grep -E 'server.py|nginx' | grep -v grep | head")
print("procs:", o[:600])
cli.close()
