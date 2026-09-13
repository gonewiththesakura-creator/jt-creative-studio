import http.client,importlib.util,json,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('new_style_http',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp());m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m._jobs={};m.save_jobs=lambda:None;m.run_job=lambda job:None
srv=m.BoundedHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=srv.serve_forever,daemon=True).start();cookie='jt_session='+m._encode_session_cookie('new-style-session-1234567890')
def post(style):
 payload={'workflow':'anima02','prompt':'adult portrait','negative_prompt':'text, watermark','prompt_mode':'manual','width':768,'height':1024,'batch':1,'hd':0,'seed':321,'seed_mode':'fixed','style_id':style,'style_variant':'default','mode':'original','generation_backend':'local','client_request_id':'new-'+style,'loras':{'LORA1':'attacker.safetensors'},'trigger':'attacker','lora_strengths':{'LORA1':99}}
 c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=10);raw=json.dumps(payload).encode();c.request('POST','/api/generate',raw,{'Content-Type':'application/json','Cookie':cookie});r=c.getresponse();data=json.loads(r.read());status=r.status;c.close();return status,data
try:
 expected={'style221':('zxqelun','11_style221_v1_step400.safetensors'),'style222':('zxqavri','10_style222_v1_step400.safetensors')}
 for style,(trigger,lora) in expected.items():
  status,data=post(style);assert status==200,(style,status,data);job=m._jobs[data['job_id']];assert job['trigger']==trigger;assert job['loras']=={'LORA1':lora,'LORA2':lora};assert job['lora_strengths']=={'LORA1':0.4,'LORA2':0.0};job['status']='done'
 print('NEW_STYLE_HTTP_OK')
finally:srv.shutdown();srvland=srv.server_close()
