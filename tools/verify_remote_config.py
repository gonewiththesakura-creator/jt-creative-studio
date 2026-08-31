"""Verify remote config.json has corrected workflowIds."""
import json, pathlib, paramiko

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
creds = json.loads((BASE / "tools" / "creds.json").read_text(encoding="utf-8"))
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(creds["host"], port=creds["port"], username=creds["user"], password=creds["password"], timeout=20)
_, out, _ = cli.exec_command("cat /home/admin/comfy-panel/config.json", timeout=30)
remote = out.read().decode(errors="replace")
cli.close()

local = (BASE / "config.json").read_text(encoding="utf-8")
print("remote config len:", len(remote), "| local:", len(local))
print("remote has 2093554049743339522 (wardrobe):", "2093554049743339522" in remote)
print("remote has 2093554183483215873 (h3_4step):", "2093554183483215873" in remote)
print("remote has 2093554104655167490 (action):", "2093554104655167490" in remote)
print("remote has 2093554154237509633 (lightx2v):", "2093554154237509633" in remote)
print("local == remote:", remote == local)
