"""Generic SSH runner: python ssh_run.py '<remote command>'"""
import json, sys, pathlib
import paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/tools")
creds = json.loads((BASE / "creds.json").read_text(encoding="utf-8"))
cmd = sys.argv[1]

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)
stdin, stdout, stderr = cli.exec_command(cmd, timeout=60)
out = stdout.read().decode(errors="replace")
err = stderr.read().decode(errors="replace")
print(out)
if err.strip():
    print("[stderr]", err[:2000])
cli.close()
