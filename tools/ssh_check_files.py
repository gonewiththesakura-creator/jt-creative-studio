"""SSH check server-side files: size + content markers."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
REMOTE = "/home/admin/comfy-panel"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)

def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=60)
    return out.read().decode(errors="replace").strip(), err.read().decode(errors="replace").strip()

for f in ["index.html", "promptgen.html", "video.html", "orig_sketch.html", "orig_graphic.html"]:
    o, e = run(f"ls -la {REMOTE}/static/{f} 2>&1; md5sum {REMOTE}/static/{f} 2>/dev/null | cut -c1-16")
    print(f, "->", o.replace("\n", " | "))

o, _ = run(f"grep -c navSwitch {REMOTE}/static/index.html 2>&1; grep -c navSwitch {REMOTE}/static/promptgen.html 2>&1")
print("navSwitch counts (index, promptgen):", o)

o, _ = run(f"grep -c '视频生成面板' {REMOTE}/static/index.html 2>&1")
print("video button count index:", o)

# check service working dir
o, _ = run("systemctl cat comfy-panel | grep -E 'WorkingDirectory|ExecStart'")
print("service:", o.replace("\n", " | "))
cli.close()
