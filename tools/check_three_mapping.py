import paramiko,json,pathlib
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel');c=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
ids=['604d014e3bf6','ce6062a336d5','d19502702f8a']
x=paramiko.SSHClient();x.set_missing_host_key_policy(paramiko.AutoAddPolicy());x.connect(c['host'],port=c['port'],username=c['user'],password=c['password'],timeout=30,allow_agent=False,look_for_keys=False)
cmd="python3 - <<'PY'\nimport json\nd=json.load(open('/home/admin/comfy-panel/panel_data/jobs.json'))\nfor i in "+repr(ids)+":\n j=d[i]; print(json.dumps({k:j.get(k) for k in ['id','style_id','mode','trigger','loras','lora_strengths','status','rh_task_id']},ensure_ascii=False))\nPY"
_,o,e=x.exec_command(cmd,timeout=60);print(o.read().decode());print(e.read().decode());x.close()
