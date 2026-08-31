import paramiko, json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"],
            password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, t=60):
    _, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

# in-memory job state via /api/jobs (authoritative, unlike stale jobs.json)
print("=== /api/jobs (in-memory, first 2 jobs) ===")
o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/jobs | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(json.dumps({k:j.get(k) for k in (\"id\",\"workflow\",\"status\",\"provider_status\",\"rh_task_id\",\"error\",\"progress_pct\",\"elapsed\")},ensure_ascii=False)) for j in d[:3]]'")
print(o)

# HTTP status code of a fresh /api/generate while locked
print("\n=== /api/generate status code while locked ===")
o, e = run("curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST http://127.0.0.1:8189/api/generate -H 'Content-Type: application/json' -d '{\"workflow\":\"anima02\",\"prompt\":\"x\",\"width\":768,\"height\":1024,\"batch\":1,\"hd\":0}'; echo")
print("http code:", o)

# grep all _send codes with line numbers (raw, using grep -n)
print("\n=== _send calls (line numbers) ===")
o, e = run("grep -n 'self._send' /home/admin/comfy-panel/server.py")
print(o)

cli.close()
