import paramiko, json, pathlib, base64

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
REMOTE = "/home/admin/comfy-panel"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"],
            password=creds["password"], timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=60):
    _, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    return o, e

def upload_via_stdin(local_path, remote_path):
    data = pathlib.Path(local_path).read_bytes()
    b64 = base64.b64encode(data).decode()
    # Write b64 to a temp file on remote in chunks via stdin, then decode.
    cmd = f"cat > /tmp/upload.b64 && base64 -d /tmp/upload.b64 > '{remote_path}.new' && rm /tmp/upload.b64 && mv '{remote_path}.new' '{remote_path}'"
    stdin, out, err = cli.exec_command(cmd, timeout=120)
    # Feed b64 through stdin in chunks to avoid buffering issues
    chunk = 60 * 1024
    for i in range(0, len(b64), chunk):
        stdin.write(b64[i:i+chunk])
    stdin.channel.shutdown_write()
    exit_status = out.channel.recv_exit_status()
    err_txt = err.read().decode(errors="replace").strip()
    if exit_status != 0:
        raise RuntimeError(f"remote write failed (exit {exit_status}): {err_txt}")
    return len(data)

# Only server.py changed for the QUEUED fix; everything else was uploaded fine
# in the previous successful deploy. Upload it robustly.
n = upload_via_stdin(BASE / "server.py", f"{REMOTE}/server.py")
print(f"uploaded server.py ({n} bytes)")

# Verify size + syntax on remote, then restart.
o, e = run(f"ls -la {REMOTE}/server.py; python3 -m py_compile {REMOTE}/server.py && echo SYNTAX_OK")
print(o)
if e:
    print("[stderr]", e[:400])

o, e = run("sudo systemctl restart comfy-panel && sleep 2 && systemctl is-active comfy-panel")
print("restart:", o)
if e:
    print("[stderr]", e[:400])

o, e = run("curl -s --max-time 10 http://127.0.0.1:8189/api/health")
print("health:", o)

cli.close()
