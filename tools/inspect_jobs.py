import paramiko, json, pathlib, urllib.request

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
REMOTE = "/home/admin/comfy-panel"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"],
            password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, t=40):
    _, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

# 1. dump jobs.json
o, e = run(f"cat {REMOTE}/panel_data/jobs.json")
try:
    jobs = json.loads(o)
except Exception as ex:
    print("jobs.json parse failed:", ex)
    print(o[:2000])
    jobs = {}

print("=== all jobs (id, workflow, status, rh_task_id, created, elapsed) ===")
for jid, j in jobs.items():
    print(json.dumps({
        "id": jid,
        "workflow": j.get("workflow"),
        "status": j.get("status"),
        "provider_status": j.get("provider_status"),
        "rh_task_id": j.get("rh_task_id"),
        "error": (j.get("error") or "")[:120],
        "created": j.get("created"),
        "elapsed": j.get("elapsed"),
    }, ensure_ascii=False))

# 2. find any job in "running" and query RunningHub for it directly
running = [j for j in jobs.values() if j.get("status") == "running"]
print(f"\n=== {len(running)} running job(s) ===")
for j in running:
    tid = j.get("rh_task_id")
    print(f"job {j.get('id')} workflow={j.get('workflow')} rh_task_id={tid}")
    if tid:
        body = json.dumps({"taskId": tid}).encode()
        req = urllib.request.Request("https://www.runninghub.ai/openapi/v2/query",
                                     data=body,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + creds.get("rh_key", "")},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                r = json.loads(resp.read().decode())
            print("  RH query:", json.dumps(r, ensure_ascii=False)[:600])
        except Exception as e:
            print("  RH query error:", e)

cli.close()
