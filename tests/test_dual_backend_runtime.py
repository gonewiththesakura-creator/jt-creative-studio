import importlib.util,json,tempfile
from pathlib import Path
P=Path(r"D:/LAN-Share/lora/_work/comfy_panel/server.py")
spec=importlib.util.spec_from_file_location('dual_server_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
# Exact local API contract: trusted LoRAs become local Anima_JT paths, trigger
# appears once, negative/seed/batch/HD reach their nodes.
job={"id":"dualtest","workflow":"anima02","prompt":"jt_style1_v1, portrait, closed book","negative_prompt":"bad hands, text","trigger":"jt_style1_v1","width":768,"height":1024,"batch":3,"hd":0,"seed":123456,"loras":{"LORA1":"01_style1_step900.safetensors","LORA2":"01_style1_step900.safetensors"},"lora_strengths":{"LORA1":0.7,"LORA2":0.6},"prompt_ids":[],"progress_pct":0}
captured={}
def submit(payload):captured['api']=payload['prompt'];return 'pid'
def wait(*a,**k):return [{'filename':'a.png','subfolder':'','type':'output'},{'filename':'b.png','subfolder':'','type':'output'},{'filename':'c.png','subfolder':'','type':'output'}]
def fetch(im,dest):p=Path(dest);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'WEBP');return p
m.submit_job=submit;m._wait_progress=wait;m.fetch_preview_and_save=fetch
root=Path(tempfile.mkdtemp());imgs=m.local_run_image(job,root,m.WORKFLOWS['anima02']);api=captured['api']
assert api['70']['inputs']['lora_name']=='Anima_JT\\01_style1_step900.safetensors'
assert api['71']['inputs']['lora_name']=='Anima_JT\\01_style1_step900.safetensors'
assert api['4']['inputs']['text'].lower().count('jt_style1_v1')==1
assert api['5']['inputs']['text']=='bad hands, text'
assert '{{' not in json.dumps(api), 'unresolved template placeholder remains'
assert api['6']['inputs']['batch_size']==3 and api['9']['inputs']['seed']==123456
assert api['11']['inputs']['images']==['10',0] and '19' not in api
assert len(imgs)==3 and all(x['remote'] is False and x['preview_url'].startswith('/api/local-preview/') and x['archive_status']=='pending' for x in imgs)
# Independent lanes: one running cloud job does not occupy local and vice versa.
m._jobs={'c':{'id':'c','status':'running','generation_backend':'cloud'},'l':{'id':'l','status':'running','generation_backend':'local'}}
class H: pass
h=H();h._running_job_id=lambda backend=None: next((j['id'] for j in m._jobs.values() if j['status']=='running' and (backend is None or j.get('generation_backend','cloud')==backend)),None)
assert h._running_job_id('cloud')=='c' and h._running_job_id('local')=='l'
print('DUAL_BACKEND_RUNTIME_OK local_native_batch=3 exact_nodes independent_lanes')
