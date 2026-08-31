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

# proxy env vars in the running panel process
o, e = run("tr '\\0' '\\n' < /proc/2243139/environ | grep -iE 'proxy|rh|runninghub' || echo '(no proxy vars)'")
print("=== panel process proxy/rh env ==="); print(o)

# does the stuck job thread still exist / is it still running?
o, e = run("cat /proc/2243139/task/2244181/status 2>/dev/null | grep -E 'State' ; cat /proc/2243139/task/2244181/wchan 2>/dev/null; echo; echo '---'; date +%s")
print("=== thread 2244181 state ==="); print(o)

# RH submit endpoint latency (harmless GET to the v2 root)
o, e = run("curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 25 https://www.runninghub.ai/openapi/v2/query -X POST -H 'Content-Type: application/json' -d '{}' ; echo")
print("=== RH query empty POST ==="); print(o, e)

cli.close()
