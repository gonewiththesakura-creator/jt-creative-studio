import json,subprocess,time
from pathlib import Path
base='http://8.210.125.65:8189'
payload={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, simple portrait, muted blue background","width":512,"height":768,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}
records=[]
for run in range(2):
 raw=subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)],text=True)
 resp=json.loads(raw)
 if 'job_id' not in resp: raise SystemExit('SUBMIT FAILED '+raw)
 jid=resp['job_id']; print('submitted',run+2,jid,flush=True)
 deadline=time.time()+300
 while time.time()<deadline:
  jobs=json.loads(subprocess.check_output(['curl','-sS','--max-time','20',base+'/api/jobs'],text=True))
  j=next(x for x in jobs if x['id']==jid)
  print(' ',j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
  if j['status']!='running': break
  time.sleep(10)
 if j['status']!='done': raise SystemExit('FAILED '+json.dumps(j,ensure_ascii=False))
 im=j['images'][0]
 for kind,url in [('preview',im['url'].replace('/api/image/','/api/preview/')),('original',im['url'])]:
  out=f'C:/Users/JT/AppData/Local/Temp/{jid}_{kind}.bin'
  rr=subprocess.run(['curl','-sS','-w','%{http_code} %{time_total}','--max-time','60',base+url,'-o',out],capture_output=True,text=True)
  p=Path(out); magic=p.read_bytes()[:8]; print(' ',kind,rr.stdout,p.stat().st_size,magic,flush=True);p.unlink()
 records.append({k:j.get(k) for k in ['id','elapsed','submit_started','provider_started','provider_finished','download_started','download_finished','images']})
print('RESULTS',json.dumps(records,ensure_ascii=False),flush=True)
