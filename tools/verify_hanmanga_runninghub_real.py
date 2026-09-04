import base64,json,paramiko,pathlib
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel');CREDS=json.loads((BASE/'tools/creds.json').read_text(encoding='utf8'));profile=json.loads((BASE/'sources/hanmanga_profile.source.json').read_text(encoding='utf8'))
parts=[profile['prefix'],profile['head']]
for key,label in profile['defaultSelections'].items():
 hit=next((row for row in profile['pools'][key] if row[0]==label),None)
 if hit and hit[1]:parts.append(hit[1])
parts.append(profile['style']);prompt=',\n\n'.join(parts);negative=profile['negative']
remote_script=r'''import json,os,urllib.request,time,hashlib,pathlib
key=os.environ["RUNNINGHUB_API_KEY"];base="https://www.runninghub.ai/openapi/v2";wid="2091826879766933505";prompt=__PROMPT__;negative=__NEGATIVE__
node=[{"nodeId":"4","fieldName":"text","fieldValue":"jt_liulistyle_v1, "+prompt},{"nodeId":"5","fieldName":"text","fieldValue":negative},{"nodeId":"7","fieldName":"lora_name","fieldValue":"08_liuli_style_v1_step600.safetensors"},{"nodeId":"7","fieldName":"strength_model","fieldValue":0.7},{"nodeId":"8","fieldName":"lora_name","fieldValue":"08_liuli_style_v1_step600.safetensors"},{"nodeId":"8","fieldName":"strength_model","fieldValue":0.6},{"nodeId":"6","fieldName":"width","fieldValue":512},{"nodeId":"6","fieldName":"height","fieldValue":768},{"nodeId":"6","fieldName":"batch_size","fieldValue":1},{"nodeId":"10","fieldName":"seed","fieldValue":24681358},{"nodeId":"20","fieldName":"index","fieldValue":0}]
body={"addMetadata":False,"nodeInfoList":node,"instanceType":"default","usePersonalQueue":"false"};req=urllib.request.Request(base+"/run/workflow/"+wid,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
with urllib.request.urlopen(req,timeout=90) as r:submitted=json.load(r)
print("SUBMIT",json.dumps({k:submitted.get(k) for k in ("taskId","status","errorCode","errorMessage")}));tid=submitted.get("taskId");assert tid,submitted
deadline=time.time()+1200;last=None;results=[]
while time.time()<deadline:
 req=urllib.request.Request(base+"/query",data=json.dumps({"taskId":tid}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
 with urllib.request.urlopen(req,timeout=40) as r:data=json.load(r)
 state=(data.get("status"),data.get("errorCode"),data.get("errorMessage"))
 if state!=last:print("STATE",json.dumps(state));last=state
 if data.get("status")=="FAILED":raise RuntimeError(json.dumps(data))
 if data.get("status")=="SUCCESS" and data.get("results"):results=data["results"];break
 time.sleep(5)
assert results,"timeout/no results";url=next((x.get("url") or x.get("fileUrl") for x in results if x.get("url") or x.get("fileUrl")),None);assert url
with urllib.request.urlopen(url,timeout=240) as r:blob=r.read()
out=pathlib.Path("/tmp/liuli_step600_runninghub_smoke.png");out.write_bytes(blob);print("RESULT",json.dumps({"task_id":tid,"url":url,"bytes":len(blob),"sha256":hashlib.sha256(blob).hexdigest(),"path":str(out)}))
'''.replace('__PROMPT__',repr(prompt)).replace('__NEGATIVE__',repr(negative))
ssh=paramiko.SSHClient();ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy());ssh.connect(CREDS['host'],port=CREDS['port'],username=CREDS['user'],password=CREDS['password'],timeout=30,allow_agent=False,look_for_keys=False)
payload=base64.b64encode(remote_script.encode()).decode();cmd="set -a; . /home/admin/comfy-panel/panel.env; set +a; python3 -c \"import base64;exec(base64.b64decode('"+payload+"'))\"";_,stdout,stderr=ssh.exec_command(cmd,timeout=1300);out=stdout.read().decode('utf8','replace');err=stderr.read().decode('utf8','replace');code=stdout.channel.recv_exit_status();print(out);print(err[:1000]);assert code==0
line=next(x for x in out.splitlines() if x.startswith('RESULT '));meta=json.loads(line[7:]);sftp=ssh.open_sftp();local=pathlib.Path.home()/r'AppData/Local/Temp/liuli_step600_runninghub_smoke.png';sftp.get(meta['path'],str(local));sftp.remove(meta['path']);sftp.close();ssh.close();print('RUNNINGHUB_HANMANGA_REAL_OK',local,meta['task_id'])
