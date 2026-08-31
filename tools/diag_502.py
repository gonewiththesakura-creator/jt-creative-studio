import paramiko, json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"],
            password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, t=40):
    _, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

print("=== what listens on 8189 ===")
o, e = run("ss -tlnp 2>/dev/null | grep 8189 || sudo ss -tlnp | grep 8189 || netstat -tlnp 2>/dev/null | grep 8189")
print(o, e)

print("\n=== nginx sites / proxy for 8189 ===")
o, e = run("grep -rn '8189' /etc/nginx/ 2>/dev/null | head -20")
print(o, e)

print("\n=== panel service status ===")
o, e = run("systemctl is-active comfy-panel; systemctl status comfy-panel --no-pager -n 8 | tail -15")
print(o, e)

print("\n=== recent panel logs ===")
o, e = run("journalctl -u comfy-panel -n 40 --no-pager 2>/dev/null | tail -40")
print(o, e)

print("\n=== local health ===")
o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/health; echo")
print(o)

print("\n=== test /api/generate with anima02 ===")
o, e = run('''curl -s --max-time 30 -X POST http://127.0.0.1:8189/api/generate -H 'Content-Type: application/json' -H 'X-Panel-Token: x' -d '{"workflow":"anima02","prompt":"test","width":768,"height":1024,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}'; echo''')
print(o)

cli.close()
