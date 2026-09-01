import base64,json,paramiko,pathlib
BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel');CREDS=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
remote_script=r'''import json,urllib.request,urllib.error,subprocess,time,hashlib,pathlib
pid=subprocess.check_output(['systemctl','show','-p','MainPID','--value','comfy-panel'],text=True).strip()
env=open('/proc/'+pid+'/environ','rb').read().split(b'\0')
key=next((x.split(b'=',1)[1].decode() for x in env if x.startswith(b'RUNNINGHUB_API_KEY=')),'');assert key
base='https://www.runninghub.ai/openapi/v2';wid='2091826879766933505'
node=[
 {'nodeId':'4','fieldName':'text','fieldValue':'jt_nffstyle_v1, adult woman, solo, elegant half-body portrait, long dark hair, refined expressive eyes, black fitted evening dress, one hand near hair, tasteful cinematic interior, soft window light, coherent detailed hands'},
 {'nodeId':'5','fieldName':'text','fieldValue':'worst quality, low quality, blurry, child, underage, bad anatomy, bad hands, extra fingers, missing fingers, text, watermark, logo, signature'},
 {'nodeId':'7','fieldName':'lora_name','fieldValue':'06_nff_style_v1_step2000.safetensors'},
 {'nodeId':'7','fieldName':'strength_model','fieldValue':0.7},
 {'nodeId':'8','fieldName':'lora_name','fieldValue':'06_nff_style_v1_step2000.safetensors'},
 {'nodeId':'8','fieldName':'strength_model','fieldValue':0.6},
 {'nodeId':'6','fieldName':'width','fieldValue':512},{'nodeId':'6','fieldName':'height','fieldValue':768},{'nodeId':'6','fieldName':'batch_size','fieldValue':1},{'nodeId':'10','fieldName':'seed','fieldValue':24681357},{'nodeId':'20','fieldName':'index','fieldValue':0},
]
body={'addMetadata':False,'nodeInfoList':node,'instanceType':'default','usePersonalQueue':'false'}
req=urllib.request.Request(base+'/run/workflow/'+wid,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
with urllib.request.urlopen(req,timeout=90) as r:resp=json.load(r)
print('SUBMIT',json.dumps({k:resp.get(k) for k in ('taskId','status','errorCode','errorMessage')}));tid=resp.get('taskId');assert tid,resp
deadline=time.time()+1200;last=None;results=[]
while time.time()<deadline:
 q=urllib.request.Request(base+'/query',data=json.dumps({'taskId':tid}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with urllib.request.urlopen(q,timeout=40) as r:d=json.load(r)
 state=(d.get('status'),d.get('errorCode'),d.get('errorMessage'))
 if state!=last:print('STATE',json.dumps(state));last=state
 if d.get('status')=='FAILED':raise RuntimeError(json.dumps(d))
 if d.get('status')=='SUCCESS' and d.get('results'):results=d['results'];break
 time.sleep(5)
assert results,'timeout/no results';url=next(x.get('url') for x in results if x.get('url'))
with urllib.request.urlopen(url,timeout=240) as r:data=r.read()
out=pathlib.Path('/tmp/nff_step2000_runninghub_smoke.png');out.write_bytes(data)
print('RESULT',json.dumps({'task_id':tid,'url':url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'path':str(out)}))
'''
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy());client.connect(CREDS['host'],port=CREDS['port'],username=CREDS['user'],password=CREDS['password'],timeout=30,allow_agent=False,look_for_keys=False)
payload=base64.b64encode(remote_script.encode()).decode();cmd=f"python3 -c \"import base64;exec(base64.b64decode('{payload}'))\"";stdin,out,err=client.exec_command(cmd,timeout=1300);stdout=out.read().decode('utf8','replace');stderr=err.read().decode('utf8','replace');code=out.channel.recv_exit_status();print(stdout);print(stderr[:1000]);assert code==0
# Pull artifact locally for visual validation.
line=next(x for x in stdout.splitlines() if x.startswith('RESULT '));meta=json.loads(line[7:]);sftp=client.open_sftp();local=pathlib.Path.home()/'AppData/Local/Temp/nff_step2000_runninghub_smoke.png';sftp.get(meta['path'],str(local));sftp.remove(meta['path']);sftp.close();client.close();print('RUNNINGHUB_NFF_REAL_OK',local,meta['task_id'])
