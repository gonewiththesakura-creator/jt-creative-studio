import paramiko, json, pathlib, time

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"],
            password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, t=60):
    _, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()

# 1. current server time vs stuck job created time
o, e = run("date +%s; date")
now = int(o.splitlines()[0])
print("server now unix:", now, "| human:", o.splitlines()[1] if len(o.splitlines())>1 else "")
stuck_created = 1787658508
print("stuck job created:", stuck_created, "=> age seconds:", now - stuck_created)

# 2. RunningHub connectivity from server
print("\n=== RunningHub reachability from server ===")
o, e = run("curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 20 https://www.runninghub.ai/openapi/v2/query -X POST -H 'Content-Type: application/json' -d '{\"taskId\":\"2092076705679224834\"}' ; echo")
print("RH query http:", o, e)

# 3. threads of the panel process
print("\n=== panel process threads ===")
o, e = run("ps -eLf | grep -c '[s]erver.py' ; ls /proc/2243139/task 2>/dev/null | wc -l")
print("thread count:", o)

# 4. is the stuck job thread still alive? check via /proc
o, e = run("for t in /proc/2243139/task/*; do echo \"== $t ==\"; cat $t/status 2>/dev/null | grep -E 'Name|State'; cat $t/wchan 2>/dev/null; echo; done 2>/dev/null | head -60")
print(o)

cli.close()
