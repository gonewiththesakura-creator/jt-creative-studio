import paramiko, json, pathlib, base64, time, sys

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
REMOTE = "/home/admin/comfy-panel"

def connect():
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for attempt in range(4):
        try:
            cli.connect(creds["host"], port=creds["port"], username=creds["user"],
                        password=creds["password"], timeout=20, allow_agent=False, look_for_keys=False)
            return cli
        except Exception as e:
            print(f"  connect attempt {attempt+1} failed: {e}", flush=True)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("could not connect")

def run(cli, cmd, timeout=60):
    _, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors="replace").strip()
    e = err.read().decode(errors="replace").strip()
    return o, e

def send_chunk(b64chunk):
    """Send one base64 chunk via a fresh connection, appending to /tmp/upload.b64."""
    for attempt in range(4):
        cli = None
        try:
            cli = connect()
            cmd = "cat >> /tmp/upload.b64"
            stdin, out, err = cli.exec_command(cmd, timeout=60)
            stdin.write(b64chunk)
            stdin.channel.shutdown_write()
            ec = out.channel.recv_exit_status()
            if ec == 0:
                return len(b64chunk)
            print(f"  chunk write exit {ec}, retrying", flush=True)
        except Exception as e:
            print(f"  chunk write failed: {e}", flush=True)
        finally:
            if cli:
                try: cli.close()
                except Exception: pass
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("chunk write failed after retries")

data = pathlib.Path(BASE / "server.py").read_bytes()
b64 = base64.b64encode(data).decode()

# Reset the temp file
cli = connect()
run(cli, "rm -f /tmp/upload.b64")
cli.close()
print(f"uploading server.py ({len(data)} bytes) in chunks...", flush=True)

chunk = 8 * 1024
total = 0
for i in range(0, len(b64), chunk):
    total += send_chunk(b64[i:i+chunk])
    if (i // chunk) % 8 == 0:
        print(f"  {total}/{len(b64)} b64 bytes", flush=True)

print("chunks done; decoding and installing...", flush=True)
cli = connect()
o, e = run(cli, f"base64 -d /tmp/upload.b64 > '{REMOTE}/server.py.new' && rm /tmp/upload.b64 && mv '{REMOTE}/server.py.new' '{REMOTE}/server.py' && ls -la '{REMOTE}/server.py'")
print(o)
if e: print("[stderr]", e[:400], flush=True)

o, e = run(cli, f"python3 -m py_compile '{REMOTE}/server.py' && echo SYNTAX_OK")
print(o)
if e: print("[stderr]", e[:400], flush=True)

o, e = run(cli, "sudo systemctl restart comfy-panel && sleep 2 && systemctl is-active comfy-panel")
print("restart:", o)
if e: print("[stderr]", e[:400], flush=True)

o, e = run(cli, "curl -s --max-time 10 http://127.0.0.1:8189/api/health")
print("health:", o)
cli.close()
print("DONE", flush=True)
