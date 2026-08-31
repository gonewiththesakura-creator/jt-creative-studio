import json,subprocess,time,statistics
base='http://8.210.125.65:8189'
payload={"workflow":"anima02","prompt":"1girl, solo, clearly adult woman, simple portrait, muted gray-blue background","width":512,"height":768,"batch":1,"hd":0,"loras":{"LORA1":"05_style3_v2_step1600.safetensors","LORA2":"04_style3_step800.safetensors"},"trigger":"jt_style3_v2"}
recs=[]
def get(url,timeout=20):
 for a in range(4):
  r=subprocess.run(['curl','-sS','--max-time',str(timeout),url],capture_output=True,text=True)
  try:
   if r.returncode==0:return json.loads(r.stdout)
  except:pass
  time.sleep(a+1)
 raise RuntimeError('GET failed '+url)
for n in range(3):
 for a in range(4):
  r=subprocess.run(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)],capture_output=True,text=True)
  try:resp=json.loads(r.stdout)
  except:resp={}
  if 'job_id' in resp:break
  print('submit retry',resp,r.stderr,flush=True);time.sleep(3)
 jid=resp['job_id']; print('SUBMIT',n+1,jid,flush=True)
 for i in range(60):
  j=get(base+'/api/job/'+jid);print(' ',j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
  if j['status']!='running':break
  time.sleep(3)
 if j['status']!='done':raise SystemExit('FAIL '+json.dumps(j,ensure_ascii=False))
 im=j['images'][0]
 # HEAD/read first bytes from direct result
 rr=subprocess.run(['curl','-4','-sS','-w','%{http_code} %{time_total} %{size_download}','--range','0-31','--max-time','30',im['url'],'-o',f'C:/Users/JT/AppData/Local/Temp/s{n}.bin'],capture_output=True,text=True)
 print(' RESULT elapsed',j['elapsed'],'provider',round(j['provider_finished']-j['provider_started'],1),'url',rr.stdout,'remote',im.get('remote'),flush=True)
 recs.append(j)
# Verify compact history and inclusion
hist=get(base+'/api/jobs');print('HISTORY bytes',len(json.dumps(hist,ensure_ascii=False).encode()),'count',len(hist));print('contains',[r['id'] in [x['id'] for x in hist] for r in recs]);print('SUMMARY',[x['elapsed'] for x in recs],flush=True)
