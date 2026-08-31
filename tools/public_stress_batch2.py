import json,subprocess,time
from pathlib import Path
base='http://8.210.125.65:8189'
payload={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, silver bob hair, muted fashion portrait, simple pale background","width":768,"height":1024,"batch":2,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}
raw=subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)],text=True)
resp=json.loads(raw);print('submit',resp,flush=True);jid=resp['job_id']
for i in range(36):
 jobs=json.loads(subprocess.check_output(['curl','-sS','--max-time','20',base+'/api/jobs'],text=True));j=next(x for x in jobs if x['id']==jid)
 print(i,j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
 if j['status']!='running':break
 time.sleep(10)
if j['status']!='done':raise SystemExit('FAILED '+json.dumps(j,ensure_ascii=False))
print('DONE',json.dumps({k:j.get(k) for k in ['id','rh_task_id','elapsed','submit_started','provider_started','provider_finished','download_started','download_finished','images']},ensure_ascii=False),flush=True)
for im in j['images']:
 url=im['url'].replace('/api/image/','/api/preview/');out=f'C:/Users/JT/AppData/Local/Temp/{im["file"]}.jpg';r=subprocess.run(['curl','-sS','-w','%{http_code} %{time_total}','--max-time','30',base+url,'-o',out],capture_output=True,text=True);p=Path(out);print('PREVIEW',r.stdout,p.stat().st_size,p.read_bytes()[:3]);p.unlink()
