"""Compare remote vs local config.json content structure."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)
_, out, _ = cli.exec_command("cat /home/admin/comfy-panel/config.json", timeout=30)
remote_raw = out.read().decode(errors="replace")
cli.close()

remote = json.loads(remote_raw)
local = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

for w in [x for x in local["workflows"] if x.get("kind") == "video"]:
    rw = next((x for x in remote["workflows"] if x.get("id") == w["id"]), None)
    if not rw:
        print(w["id"], "MISSING on remote!"); continue
    same = rw.get("rh_workflow_id") == w["rh_workflow_id"] and rw.get("rh_media") == w["rh_media"] and rw.get("rh_params") == w["rh_params"]
    print(w["id"], "remote wfid:", rw.get("rh_workflow_id"), "| local:", w["rh_workflow_id"], "| match:", same)
