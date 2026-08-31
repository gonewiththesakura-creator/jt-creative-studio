import paramiko, json, pathlib, time

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
JOB = "bbd3281fd309"

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

for i in range(6):
    o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/jobs")
    try:
        jobs = json.loads(o)
    except Exception:
        print(f"poll {i+1}: bad json: {o[:200]}")
        time.sleep(20)
        continue
    j = next((x for x in jobs if x.get("id") == JOB), None)
    if not j:
        print(f"poll {i+1}: job not found yet")
        time.sleep(20)
        continue
    print(f"poll {i+1}: status={j.get('status')} provider_status={j.get('provider_status')} rh_task_id={j.get('rh_task_id')} progress={j.get('progress_pct')} images={len(j.get('images') or [])} error={(j.get('error') or '')[:120]}")
    if j.get("status") in ("done", "error"):
        break
    time.sleep(25)

# final dump of the job
o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/jobs")
try:
    jobs = json.loads(o)
    j = next((x for x in jobs if x.get("id") == JOB), None)
    if j:
        print("\n=== FINAL ===")
        print(json.dumps({k: j.get(k) for k in ("id","workflow","status","provider_status","rh_task_id","error","progress_pct","elapsed","images")}, ensure_ascii=False, indent=1)[:1500])
except Exception as e:
    print("final dump error", e)

cli.close()
