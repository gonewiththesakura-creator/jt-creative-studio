import json,subprocess,time,sys
base='http://8.210.125.65:8189'
styles=[('cold','jt_style3_v2'),('sketch','jt_inkwash_v1'),('graphic','jt_softpaint_v1')]
records=[]
def call(args,timeout=60):
 r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if r.returncode: raise RuntimeError(r.stderr)
 return r.stdout
for style,trigger in styles:
 snap={'style':style,'mode':'original','state':{},'locked':{},'width':512,'height':768,'batch':1,'hd':0}
 payload={'workflow':'anima02','prompt':'masterpiece, best quality, 1girl, solo, clearly adult woman, simple portrait, plain background','width':512,'height':768,'batch':1,'hd':0,'style_id':style,'mode':'original','selection_snapshot':snap,
          # malicious values prove server ignores browser-provided LoRA/trigger
          'trigger':'WRONG_BROWSER_TRIGGER','loras':{'LORA1':'WRONG.safetensors','LORA2':'WRONG2.safetensors'}}
 raw=call(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)]); resp=json.loads(raw); jid=resp['job_id'];print('SUBMIT',style,jid,flush=True)
 for i in range(80):
  try:j=json.loads(call(['curl','-sS','--max-time','20',base+'/api/job/'+jid],30))
  except Exception as e: print(' poll retry',e,flush=True);time.sleep(2);continue
  print(' ',j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
  if j['status']!='running':break
  time.sleep(3)
 if j['status']!='done':raise SystemExit(style+' FAILED '+json.dumps(j,ensure_ascii=False))
 records.append(j);print('DONE',style,j['rh_task_id'],j['elapsed'],len(j['images']),flush=True)
# collect remote jobs.json evidence via API job does not expose secrets; use SSH helper later. Here verify style/mode/snapshot.
for j,(style,trig) in zip(records,styles):
 assert j['style_id']==style and j['mode']=='original' and j['selection_snapshot']['style']==style
print('RESULTS',json.dumps([{k:j.get(k) for k in ['id','style_id','mode','rh_task_id','elapsed','status']} for j in records],ensure_ascii=False),flush=True)
