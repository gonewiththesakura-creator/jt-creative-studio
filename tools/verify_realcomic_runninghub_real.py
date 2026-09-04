import base64,hashlib,json,paramiko,pathlib
from PIL import Image,ImageStat

BASE=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel')
SOURCE=pathlib.Path.home()/r'AppData/Local/Temp/liuli_step600_local_smoke.png'
CREDS=json.loads((BASE/'tools'/'creds.json').read_text(encoding='utf8'))
assert SOURCE.exists() and SOURCE.stat().st_size>50000
remote_input='/tmp/realcomic_liuli_input.png';remote_output='/tmp/realcomic_liuli_result.bin'
remote_script=r'''import json,os,urllib.request,time,hashlib,pathlib,uuid
key=os.environ["RUNNINGHUB_API_KEY"];source=pathlib.Path("/tmp/realcomic_liuli_input.png");assert source.exists()
boundary="----rh"+uuid.uuid4().hex
def field(name,value):return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
def filepart(name,filename,ctype):return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
blob=source.read_bytes();body=b"".join([field("apiKey",key),field("fileType","input"),filepart("file",source.name,"image/png"),blob,b"\r\n",f"--{boundary}--\r\n".encode()])
req=urllib.request.Request("https://www.runninghub.cn/task/openapi/upload",data=body,headers={"Content-Type":f"multipart/form-data; boundary={boundary}","Authorization":"Bearer "+key})
with urllib.request.urlopen(req,timeout=120) as response:uploaded=json.load(response)
assert uploaded.get("code")==0,uploaded;remote_name=(uploaded.get("data") or {}).get("fileName");assert remote_name,uploaded
print("UPLOAD",json.dumps({"ok":True,"file_name_suffix":pathlib.PurePosixPath(remote_name).suffix,"input_bytes":len(blob)}))
app_id="2025090022289973249";nodes=[{"nodeId":"504","fieldName":"image","fieldValue":remote_name},{"nodeId":"491","fieldName":"text","fieldValue":"保留原图构图和汉服服装，转换为自然真实的成年女性，去除水印和文字"}]
req=urllib.request.Request("https://www.runninghub.ai/openapi/v2/run/ai-app/"+app_id,data=json.dumps({"nodeInfoList":nodes}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
with urllib.request.urlopen(req,timeout=120) as response:submitted=json.load(response)
print("SUBMIT",json.dumps({k:submitted.get(k) for k in ("taskId","status","errorCode","errorMessage")},ensure_ascii=False));task_id=submitted.get("taskId");assert task_id,submitted
deadline=time.time()+1800;last=None;results=[]
while time.time()<deadline:
 req=urllib.request.Request("https://www.runninghub.ai/openapi/v2/query",data=json.dumps({"taskId":task_id}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
 with urllib.request.urlopen(req,timeout=45) as response:data=json.load(response)
 state=(data.get("status"),data.get("errorCode"),data.get("errorMessage"))
 if state!=last:print("STATE",json.dumps(state,ensure_ascii=False));last=state
 if data.get("status")=="FAILED":raise RuntimeError(json.dumps(data,ensure_ascii=False))
 if data.get("status")=="SUCCESS" and data.get("results"):results=data["results"];break
 time.sleep(6)
assert results,"timeout/no results";url=next((item.get("url") or item.get("fileUrl") for item in results if item.get("url") or item.get("fileUrl")),None);assert url,results
with urllib.request.urlopen(url,timeout=300) as response:result=response.read();ctype=response.headers.get("Content-Type")
out=pathlib.Path("/tmp/realcomic_liuli_result.bin");out.write_bytes(result)
print("RESULT",json.dumps({"task_id":task_id,"url":url,"bytes":len(result),"sha256":hashlib.sha256(result).hexdigest(),"content_type":ctype,"path":str(out)},ensure_ascii=False))
'''
def connect():
 client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy());client.connect(CREDS['host'],port=CREDS['port'],username=CREDS['user'],password=CREDS['password'],timeout=30,allow_agent=False,look_for_keys=False);return client
source_data=SOURCE.read_bytes();expected_sha=hashlib.sha256(source_data).hexdigest()
# Upload in independently reconnectable 64 KiB chunks. A prior one-shot SFTP
# channel was reset at exactly 256 KiB and left a partial file.
for offset in range(0,len(source_data),64*1024):
 chunk=source_data[offset:offset+64*1024]
 for attempt in range(5):
  try:
   client=connect();sftp=client.open_sftp();mode='wb' if offset==0 else 'ab'
   with sftp.open(remote_input,mode) as handle:handle.write(chunk)
   sftp.close();client.close();break
  except Exception:
   try:client.close()
   except Exception:pass
   if attempt==4:raise
client=connect();_,stdout,stderr=client.exec_command("python3 -c \"import hashlib;print(hashlib.sha256(open('/tmp/realcomic_liuli_input.png','rb').read()).hexdigest())\"",timeout=60);code=stdout.channel.recv_exit_status();remote_sha=stdout.read().decode().strip();assert code==0 and remote_sha==expected_sha,(remote_sha,expected_sha)
payload=base64.b64encode(remote_script.encode()).decode();command="set -a; . /home/admin/comfy-panel/panel.env; set +a; python3 -c \"import base64;exec(base64.b64decode('"+payload+"'))\""
_,stdout,stderr=client.exec_command(command,timeout=1900);out=stdout.read().decode('utf8','replace');err=stderr.read().decode('utf8','replace');code=stdout.channel.recv_exit_status();print(out);print(err[:1500]);assert code==0
line=next(x for x in out.splitlines() if x.startswith('RESULT '));meta=json.loads(line[7:]);url=meta['url'];suffix=pathlib.PurePosixPath(pathlib.PurePosixPath(url.split('?',1)[0]).name).suffix.lower();suffix=suffix if suffix in ('.png','.jpg','.jpeg','.webp') else '.png';local=pathlib.Path.home()/('AppData/Local/Temp/realcomic_liuli_result'+suffix)
sftp=client.open_sftp();sftp.get(meta['path'],str(local));
for remote in (remote_input,meta['path']):
 try:sftp.remove(remote)
 except OSError:pass
sftp.close();client.close()
with Image.open(local) as image:
 image.load();stats=ImageStat.Stat(image.convert('RGB'));verified={'format':image.format,'size':image.size,'bytes':local.stat().st_size,'stddev':[round(x,2) for x in stats.stddev],'sha256':hashlib.sha256(local.read_bytes()).hexdigest()}
assert verified['format'] in ('PNG','JPEG','WEBP') and min(verified['size'])>=256 and max(verified['stddev'])>20 and verified['bytes']>50000,verified
print('VERIFIED',json.dumps(verified,ensure_ascii=False));print('REALCOMIC_RUNNINGHUB_REAL_OK',local,meta['task_id'])
