import paramiko, json, pathlib, time

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

def connect(retries=6):
    for a in range(retries):
        try:
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cli.connect(creds["host"], port=creds["port"], username=creds["user"],
                        password=creds["password"], timeout=20, allow_agent=False, look_for_keys=False)
            return cli
        except Exception as e:
            print(f"  connect retry {a+1}: {e}", flush=True)
            time.sleep(4 * (a + 1))
    raise RuntimeError("cannot connect")

cli = connect()
def run(cmd, t=60):
    _, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

print("=== health ===")
o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/health; echo")
print(o)

print("\n=== submit test anima02 (minimal prompt) ===")
payload = json.dumps({
    "workflow": "anima02",
    "prompt": "1girl, solo, short silver bob hair, blue eyes, simple portrait",
    "width": 512, "height": 768, "batch": 1, "hd": 0,
    "loras": {"LORA1": "05_style3_v2_step1600.safetensors", "LORA2": "04_style3_step800.safetensors"},
    "trigger": "jt_style3_v2",
})
o, e = run(f"curl -s --max-time 30 -X POST http://127.0.0.1:8189/api/generate -H 'Content-Type: application/json' -d '{payload}'; echo")
print("submit resp:", o)

cli.close()
print("\njob submitted; poll /api/jobs in a follow-up to see it complete")
