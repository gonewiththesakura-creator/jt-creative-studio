import base64,http.client,http.server,importlib.util,json,tempfile,threading
from pathlib import Path

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
spec=importlib.util.spec_from_file_location('realcomic_http',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp());m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m.FAVORITES_DIR=root/'favorites';m.FAVORITES_DIR.mkdir();m.FAVORITES_FILE=root/'favorites.json';m._jobs={};m._favorites={}
uploaded=[]
def fake_upload(data,filename,ctype,timeout=120):uploaded.append((filename,ctype,len(data)));return 'api/trusted-source.png'
m.rh_upload_file=fake_upload;m.run_job=lambda job:None
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();port=server.server_port

def post(path,payload):
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=10);body=json.dumps(payload).encode();c.request('POST',path,body,{'Content-Type':'application/json'});r=c.getresponse();data=json.loads(r.read() or b'{}');status=r.status;c.close();return status,data
try:
 status,data=post('/api/realcomic-upload',{'filename':'fake.png','data':base64.b64encode(b'not an image').decode()})
 assert status==400 and 'PNG' in data['error'] and not uploaded,(status,data,uploaded)
 png=bytes((137,80,78,71,13,10,26,10))+b'valid-fixture'
 status,data=post('/api/realcomic-upload',{'filename':'folder/fixture.png','data':base64.b64encode(png).decode()})
 assert status==200 and data['fileName']=='api/trusted-source.png' and uploaded==[('fixture.png','image/png',len(png))],(status,data,uploaded)
 payload={'workflow':'realcomic','media':{'source_image':'api/trusted-source.png','evil':'must-drop'},'params':{'requirements':'保留构图','evil':'must-drop'},'client_request_id':'same-realcomic','webappId':'attacker-app','nodeInfoList':[{'nodeId':'999','fieldName':'evil','fieldValue':'evil'}]}
 status,missing_id=post('/api/ai-app-generate',{**payload,'client_request_id':''});assert status==400 and 'client_request_id' in missing_id['error'],(status,missing_id)
 status,first=post('/api/ai-app-generate',payload);assert status==200 and first.get('job_id'),(status,first)
 jid=first['job_id'];job=m._jobs[jid]
 assert job['media']=={'source_image':'api/trusted-source.png'} and job['params']=={'requirements':'保留构图'}
 assert 'webappId' not in job and 'nodeInfoList' not in job
 status,second=post('/api/ai-app-generate',payload);assert status==200 and second=={'job_id':jid,'existing_job':jid,'deduplicated':True,'message':'same request already accepted'},(status,second)
 m._jobs[jid]['status']='done';m._jobs['busy-cloud']={'id':'busy-cloud','status':'running','generation_backend':'cloud'}
 status,busy=post('/api/ai-app-generate',{**payload,'client_request_id':'different'});assert status==429 and busy['running_job']=='busy-cloud',(status,busy)
 del m._jobs['busy-cloud'];m._jobs['busy-local']={'id':'busy-local','status':'running','generation_backend':'local'}
 status,parallel=post('/api/ai-app-generate',{**payload,'client_request_id':'parallel-cloud'});assert status==200 and parallel.get('job_id') not in (jid,'busy-local'),(status,parallel)
 print('REALCOMIC_HTTP_BOUNDARIES_OK',{'invalid_magic':400,'trusted_upload':uploaded[0], 'deduplicated':second['deduplicated'],'cloud_busy':busy['running_job'],'local_does_not_block_cloud':parallel['job_id']})
finally:
 server.shutdown();server.server_close();thread.join(timeout=3)
