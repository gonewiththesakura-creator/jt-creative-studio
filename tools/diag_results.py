import paramiko,json,pathlib
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel'); c=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
cli=paramiko.SSHClient();cli.set_missing_host_key_policy(paramiko.AutoAddPolicy());cli.connect(c['host'],port=c['port'],username=c['user'],password=c['password'],timeout=30,allow_agent=False,look_for_keys=False)
def run(cmd,t=90):
 _,o,e=cli.exec_command(cmd,timeout=t);return o.read().decode(errors='replace').strip(),e.read().decode(errors='replace').strip()
print('=== current jobs compact ===')
o,e=run("curl -s --max-time 10 http://127.0.0.1:8189/api/jobs | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(json.dumps({k:j.get(k) for k in (\"id\",\"status\",\"provider_status\",\"rh_task_id\",\"progress_pct\",\"elapsed\",\"error\",\"images\")},ensure_ascii=False)) for j in d[:8]]'")
print(o)
print('\n=== image dimensions/sizes recent jobs ===')
o,e=run("python3 - <<'PY'\nfrom pathlib import Path\nfrom PIL import Image\nroot=Path('/home/admin/comfy-panel/panel_data/jobs')\nfor d in sorted(root.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)[:8]:\n print('JOB',d.name)\n for f in d.glob('rh_*.png'):\n  try:\n   im=Image.open(f); print(f.name,f.stat().st_size,im.size,im.mode)\n  except Exception as e: print(f.name,'BAD',e)\nPY")
print(o,e)
print('\n=== current RH query raw ===')
# use server's env key indirectly by executing a tiny import? server has fallback key; avoid printing
for tid in ['2092471614417727489','2092466371286286337']:
 o,e=run(f"cd /home/admin/comfy-panel && python3 - <<'PY'\nimport server,json\nprint(json.dumps(server.rh_query('{tid}'),ensure_ascii=False)[:5000])\nPY",120)
 print(tid,o,e)
cli.close()
