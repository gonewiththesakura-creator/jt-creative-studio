import paramiko,json,pathlib,hashlib,time
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel')
C=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
REMOTE='/home/admin/comfy-panel/static'
FILES=[BASE/'static'/'promptgen.html',BASE/'static'/'index.html']
c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy());c.connect(C['host'],port=C['port'],username=C['user'],password=C['password'],timeout=20,allow_agent=False,look_for_keys=False)
s=c.open_sftp()
for src in FILES:
 dst=f'{REMOTE}/{src.name}';tmp=dst+'.ui-redesign.new';backup=dst+'.pre-ui-redesign'
 # Preserve one rollback copy of the live pre-redesign page.
 try:s.stat(backup)
 except FileNotFoundError:
  try:s.posix_rename(dst,backup);s.posix_rename(backup,dst)
  except Exception:
   # server-side cp is safer when overwrite-rename semantics differ
   _,o,e=c.exec_command(f"cp '{dst}' '{backup}'",timeout=30);o.channel.recv_exit_status()
 with s.open(tmp,'wb') as f:f.write(src.read_bytes())
 # atomic replace on same filesystem
 try:s.posix_rename(tmp,dst)
 except Exception:
  _,o,e=c.exec_command(f"mv -f '{tmp}' '{dst}'",timeout=30);ec=o.channel.recv_exit_status();assert ec==0,e.read().decode()
 with s.open(dst,'rb') as f:remote=f.read()
 local=src.read_bytes();assert remote==local
 print(src.name,len(local),hashlib.sha256(local).hexdigest())
s.close();c.close();print('STATIC_UI_DEPLOY_OK')
