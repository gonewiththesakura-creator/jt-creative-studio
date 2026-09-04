import hashlib,json,pathlib,shlex,time,urllib.request
import paramiko

BASE=pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
CREDS=json.loads((BASE/"tools"/"creds.json").read_text(encoding="utf8"))
REMOTE_ROOT="/home/admin/comfy-panel";BACKUP_SUFFIX=".pre-liuli-realcomic"
LOCAL_FILES={
 BASE/"server.py":f"{REMOTE_ROOT}/server.py",
 BASE/"config.json":f"{REMOTE_ROOT}/config.json",
 BASE/"static/promptgen.html":f"{REMOTE_ROOT}/static/promptgen.html",
 BASE/"static/index.html":f"{REMOTE_ROOT}/static/index.html",
 BASE/"static/original_sketch.html":f"{REMOTE_ROOT}/static/original_sketch.html",
 BASE/"static/original_graphic.html":f"{REMOTE_ROOT}/static/original_graphic.html",
 BASE/"static/realcomic.html":f"{REMOTE_ROOT}/static/realcomic.html",
 BASE/"static/video.html":f"{REMOTE_ROOT}/static/video.html",
}
RELEASE_FILES=list(LOCAL_FILES.values())

def command(client,text,timeout=180):
 _,out,err=client.exec_command(text,timeout=timeout);code=out.channel.recv_exit_status();stdout=out.read().decode('utf8','replace');stderr=err.read().decode('utf8','replace')
 if code:raise RuntimeError(f"remote command failed ({code}): {stderr or stdout}")
 return stdout

def rollback_release(client):
 for remote in RELEASE_FILES:
  command(client,f"cp -- {shlex.quote(remote+BACKUP_SUFFIX)} {shlex.quote(remote)}")
 command(client,"sudo systemctl restart comfy-panel",timeout=240)

def health():
 with urllib.request.urlopen("http://8.210.125.65:8189/api/health",timeout=60) as response:return json.load(response)

def fetch(path):
 with urllib.request.urlopen("http://8.210.125.65:8189"+path,timeout=60) as response:return response.read()

client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy());client.connect(CREDS["host"],port=CREDS["port"],username=CREDS["user"],password=CREDS["password"],timeout=30,allow_agent=False,look_for_keys=False);sftp=client.open_sftp()
try:
 for local,remote in LOCAL_FILES.items():
  data=local.read_bytes();staged=remote+".release.new"
  with sftp.open(staged,'wb') as handle:handle.write(data)
  with sftp.open(staged,'rb') as handle:assert handle.read()==data,f"staging mismatch: {local.name}"
 for remote in RELEASE_FILES:
  try:sftp.stat(remote+BACKUP_SUFFIX)
  except FileNotFoundError:
   try:command(client,f"cp -- {shlex.quote(remote)} {shlex.quote(remote+BACKUP_SUFFIX)}")
   except RuntimeError:
    # realcomic.html is new; preserve an explicit empty marker for rollback.
    command(client,f": > {shlex.quote(remote+BACKUP_SUFFIX)}")
 command(client,f"python3 -m py_compile {shlex.quote(REMOTE_ROOT+'/server.py.release.new')}")
 command(client,"python3 -c \"import json;json.load(open('/home/admin/comfy-panel/config.json.release.new',encoding='utf8'))\"")
 try:
  for local,remote in LOCAL_FILES.items():
   staged=remote+".release.new"
   try:sftp.posix_rename(staged,remote)
   except Exception:command(client,f"mv -f -- {shlex.quote(staged)} {shlex.quote(remote)}")
  for local,remote in LOCAL_FILES.items():
   with sftp.open(remote,'rb') as handle:live=handle.read()
   data=local.read_bytes();assert live==data,f"live mismatch: {local.name}"
   print(local.name,len(data),hashlib.sha256(data).hexdigest())
  command(client,"sudo systemctl restart comfy-panel",timeout=240);time.sleep(1)
  state=health();assert state.get('ok') and state.get('local_comfy_ok'),state
  home=fetch('/');real=fetch('/realcomic')
  assert b'data-style="hanmanga"' in home and b'jt_liulistyle_v1' in home and b'/realcomic' in home
  assert b'Anime to Live-Action V6 Speed' in real and b'/api/ai-app-generate' in real
  print('HEALTH',json.dumps(state,ensure_ascii=False));print('PUBLIC_MARKERS_OK')
 except Exception:
  rollback_release(client);raise
finally:sftp.close();client.close()
print('LIULI_REALCOMIC_RELEASE_DEPLOY_OK')
