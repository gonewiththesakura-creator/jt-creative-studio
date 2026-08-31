import paramiko, json, pathlib, base64, time
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel')
C=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
REMOTE='/home/admin/comfy-panel'
FILES=[
 (BASE/'server.py',f'{REMOTE}/server.py'),
 (BASE/'config.json',f'{REMOTE}/config.json'),
 (BASE/'static'/'promptgen.html',f'{REMOTE}/static/promptgen.html'),
 (BASE/'static'/'index.html',f'{REMOTE}/static/index.html'),
 (BASE/'static'/'original_sketch.html',f'{REMOTE}/static/original_sketch.html'),
 (BASE/'static'/'original_graphic.html',f'{REMOTE}/static/original_graphic.html'),
 (BASE/'templates'/'anima02_notrans.json',f'{REMOTE}/templates/anima02_notrans.json'),
]
def connect():
 for a in range(6):
  try:
   c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy());c.connect(C['host'],port=C['port'],username=C['user'],password=C['password'],timeout=20,allow_agent=False,look_for_keys=False);return c
  except Exception as e: print('connect retry',a+1,e,flush=True);time.sleep(3*(a+1))
 raise RuntimeError('connect failed')
def run(c,cmd,t=120):
 _,o,e=c.exec_command(cmd,timeout=t);return o.read().decode(errors='replace').strip(),e.read().decode(errors='replace').strip()
def send_chunk(text):
 for a in range(5):
  c=None
  try:
   c=connect();stdin,o,e=c.exec_command('cat >> /tmp/hermes_upload.b64',timeout=60);stdin.write(text);stdin.channel.shutdown_write();ec=o.channel.recv_exit_status()
   if ec==0:return
  except Exception as ex: print('chunk retry',a+1,ex,flush=True)
  finally:
   if c:
    try:c.close()
    except:pass
  time.sleep(2*(a+1))
 raise RuntimeError('chunk failed')
for src,dst in FILES:
 data=src.read_bytes();b=base64.b64encode(data).decode();c=connect();run(c,'rm -f /tmp/hermes_upload.b64');c.close();print('upload',src.name,len(data),flush=True)
 for i in range(0,len(b),8192):send_chunk(b[i:i+8192])
 c=connect();o,e=run(c,f"base64 -d /tmp/hermes_upload.b64 > '{dst}.new' && rm /tmp/hermes_upload.b64 && mv '{dst}.new' '{dst}' && wc -c '{dst}'");print(o,e);c.close()
c=connect();o,e=run(c,f"python3 -m py_compile '{REMOTE}/server.py' && sudo systemctl restart comfy-panel && sleep 2 && systemctl is-active comfy-panel");print(o,e);c.close()
