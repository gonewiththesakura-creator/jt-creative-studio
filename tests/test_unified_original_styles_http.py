import http.client,http.server,importlib.util,json,threading,time
from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
spec=importlib.util.spec_from_file_location('unified_original_runtime',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m._jobs={};m.save_jobs=lambda:None;m.run_job=lambda job:None
srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);port=srv.server_address[1];threading.Thread(target=srv.serve_forever,daemon=True).start()
def post(style,seq='off'):
 body={'workflow':'anima02','prompt':'adult portrait','negative_prompt':'','style_id':style,'style_variant':'default','mode':'original','sequence_mode':seq,'generation_backend':'cloud','client_request_id':'test-'+style+'-'+seq,'loras':{'LORA1':'attacker.safetensors'},'trigger':'attacker'}
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);raw=json.dumps(body).encode();c.request('POST','/api/generate',raw,{'Content-Type':'application/json','Content-Length':str(len(raw))});r=c.getresponse();data=json.loads(r.read());c.close();return r.status,data
try:
 expected={
  'original_sketch':('jt_style1_v1','01_style1_step900.safetensors'),
  'original_graphic':('jt_style2_v1','02_style2_step900.safetensors'),
 }
 for style,(trigger,lora) in expected.items():
  status,data=post(style);assert status==200,(style,status,data);job=m._jobs[data['job_id']]
  assert job['trigger']==trigger and job['loras']=={'LORA1':lora,'LORA2':lora},job
  job['status']='done'
 status,data=post('original_sketch','sketch3');assert status==200,(status,data);assert m._jobs[data['job_id']]['sequence_mode']=='off';m._jobs[data['job_id']]['status']='done'
 status,data=post('original_graphic','sketch3');assert status==200,(status,data);assert m._jobs[data['job_id']]['sequence_mode']=='off'
 for path,target in [('/original-sketch','/?style=original_sketch'),('/original-graphic','/?style=original_graphic')]:
  c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);c.request('GET',path);r=c.getresponse();r.read();assert r.status==302 and r.getheader('Location')==target,(path,r.status,r.getheaders());c.close()
 print('UNIFIED_ORIGINAL_STYLE_HTTP_OK',{'jobs':len(m._jobs),'redirects':2})
finally:srv.shutdown();srv.server_close()
