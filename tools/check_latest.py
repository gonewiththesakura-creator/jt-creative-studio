import paramiko,json,pathlib,time
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel'); c=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy()); cli.connect(c['host'],port=c['port'],username=c['user'],password=c['password'],timeout=30,allow_agent=False,look_for_keys=False)
def run(cmd,t=60):
 _,o,e=cli.exec_command(cmd,timeout=t); return o.read().decode(errors='replace').strip(),e.read().decode(errors='replace').strip()
o,e=run("curl -s --max-time 10 http://127.0.0.1:8189/api/jobs")
jobs=json.loads(o)
for j in jobs[:5]: print(json.dumps({k:j.get(k) for k in ['id','workflow','status','provider_status','rh_task_id','error','progress_pct','elapsed','images']},ensure_ascii=False)[:1800])
cli.close()
