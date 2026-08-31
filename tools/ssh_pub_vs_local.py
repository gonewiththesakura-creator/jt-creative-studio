"""Check public 8189 vs localhost 8189 responses; test noproxy locally."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)

def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=60)
    return out.read().decode(errors="replace").strip(), err.read().decode(errors="replace").strip()

# from the server itself, curl its own public IP
o, _ = run("curl -s --max-time 10 http://8.210.125.65:8189/ | wc -c")
print("server->public 8189 / :", o, "bytes")
o, _ = run("curl -s --max-time 10 http://8.210.125.65:8189/ | grep -c navSwitch")
print("server->public 8189 navSwitch:", o)
o, _ = run("curl -s --max-time 10 http://8.210.125.65:8189/ | grep -c '原始铅绘'")
print("server->public 8189 orig-sketch-btn:", o)
# iptables / nat on 8189?
o, _ = run("sudo iptables -t nat -L -n 2>/dev/null | grep -i 8189; sudo nft list ruleset 2>/dev/null | grep -i 8189")
print("nat rules for 8189:", o or "(none)")
cli.close()
