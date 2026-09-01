import hashlib
import json
import pathlib
import shlex
import time
import urllib.request

import paramiko

BASE=pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
CREDS=json.loads((BASE/"tools"/"creds.json").read_text(encoding="utf8"))
REMOTE_ROOT="/home/admin/comfy-panel"
BACKUP_SUFFIX=".pre-nff-motion-workbench"
LOCAL_FILES={
 BASE/"server.py":f"{REMOTE_ROOT}/server.py",
 BASE/"static"/"promptgen.html":f"{REMOTE_ROOT}/static/promptgen.html",
 BASE/"static"/"index.html":f"{REMOTE_ROOT}/static/index.html",
 BASE/"static"/"original_sketch.html":f"{REMOTE_ROOT}/static/original_sketch.html",
 BASE/"static"/"original_graphic.html":f"{REMOTE_ROOT}/static/original_graphic.html",
 BASE/"static"/"video.html":f"{REMOTE_ROOT}/static/video.html",
}
RELEASE_FILES=list(LOCAL_FILES.values())

def command(client,text,timeout=120):
 _,out,err=client.exec_command(text,timeout=timeout);code=out.channel.recv_exit_status();stdout=out.read().decode("utf8","replace");stderr=err.read().decode("utf8","replace")
 if code:raise RuntimeError(f"remote command failed ({code}): {stderr or stdout}")
 return stdout

def rollback_release(client):
 for remote in RELEASE_FILES:
  command(client,f"cp -- {shlex.quote(remote+BACKUP_SUFFIX)} {shlex.quote(remote)}")
 command(client,"systemctl restart comfy-panel",timeout=180)

def health_check():
 with urllib.request.urlopen("http://8.210.125.65:8189/api/health",timeout=60) as response:return json.load(response)

client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy());client.connect(CREDS["host"],port=CREDS["port"],username=CREDS["user"],password=CREDS["password"],timeout=30,allow_agent=False,look_for_keys=False)
sftp=client.open_sftp()
try:
 for local,remote in LOCAL_FILES.items():
  staged=remote+".release.new";data=local.read_bytes()
  with sftp.open(staged,"wb") as handle:handle.write(data)
  with sftp.open(staged,"rb") as handle:assert handle.read()==data,f"staging mismatch: {local.name}"
 for remote in RELEASE_FILES:
  try:sftp.stat(remote+BACKUP_SUFFIX)
  except FileNotFoundError:command(client,f"cp -- {shlex.quote(remote)} {shlex.quote(remote+BACKUP_SUFFIX)}")
 command(client,f"python3 -m py_compile {shlex.quote(REMOTE_ROOT+'/server.py.release.new')}")
 try:
  for local,remote in LOCAL_FILES.items():
   staged=remote+".release.new"
   try:sftp.posix_rename(staged,remote)
   except Exception:command(client,f"mv -f -- {shlex.quote(staged)} {shlex.quote(remote)}")
  for local,remote in LOCAL_FILES.items():
   with sftp.open(remote,"rb") as handle:live=handle.read()
   data=local.read_bytes();assert live==data,f"live mismatch: {local.name}"
   print(local.name,len(data),hashlib.sha256(data).hexdigest())
  command(client,"systemctl restart comfy-panel",timeout=180)
  time.sleep(1)
  state=health_check();assert state.get("ok") and state.get("local_comfy_ok"),state
  print("HEALTH",json.dumps(state,ensure_ascii=False))
 except Exception:
  rollback_release(client);raise
finally:
 sftp.close();client.close()
print("NFF_MOTION_RELEASE_DEPLOY_OK")
