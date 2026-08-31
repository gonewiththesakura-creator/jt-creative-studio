import json,subprocess,time
base='http://8.210.125.65:8189'
payload={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, simple portrait, muted gray-blue background","width":512,"height":768,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}
recs=[]
for n in range(3):
 raw=subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)],text=True);resp=json.loads(raw);print('SUBMIT',n+1,resp,flush=True);jid=resp['job_id']
 for i in range(30):
  jobs=json.loads(subprocess.check_output(['curl','-sS','--retry','2','--max-time','30',base+'/api/jobs'],text=True));j=next(x for x in jobs if x['id']==jid);print(' ',i,j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
  if j['status']!='running':break
  time.sleep(5)
 if j['status']!='done':raise SystemExit('FAIL '+json.dumps(j,ensure_ascii=False))
 im=j['images'][0];print(' RESULT',j['elapsed'],im,flush=True)
 # Verify direct remote result URL is reachable and PNG
 r=subprocess.run(['curl','-4','-sS','-w','%{http_code} %{time_total} %{size_download}','--max-time','60',im['url'],'-o',f'C:/Users/JT/AppData/Local/Temp/rh{n}.png'],capture_output=True,text=True);print(' IMAGE',r.stdout,flush=True)
 recs.append(j)
print('SUMMARY',[(x['elapsed'],x['provider_finished']-x['provider_started']) for x in recs],flush=True)
