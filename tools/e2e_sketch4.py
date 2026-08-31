import json,subprocess,time
base='http://8.210.125.65:8189'
snapshot={'style':'sketch','mode':'original','state':{},'locked':{},'width':512,'height':768,'batch':1,'hd':0,'sequence_mode':'4'}
p={'workflow':'anima02','prompt':'masterpiece, best quality, clearly adult woman, short silver bob hair, calm expression, simple full-body standing pose, plain white sketchbook background','width':512,'height':768,'batch':1,'hd':0,'style_id':'sketch','mode':'original','sequence_mode':'sketch4','selection_snapshot':snapshot}
r=json.loads(subprocess.check_output(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(p)],text=True));jid=r['job_id'];print('JOB',jid,flush=True)
for i in range(160):
 try:j=json.loads(subprocess.check_output(['curl','-sS','--max-time','25',base+'/api/job/'+jid],text=True))
 except Exception as e: print('retry',e,flush=True);time.sleep(2);continue
 print(j['status'],j.get('provider_status'),j.get('progress_pct'),[(x['stage_id'],x['status']) for x in (j.get('stage_status') or [])],flush=True)
 if j['status']!='running':break
 time.sleep(3)
if j['status']!='done':raise SystemExit(json.dumps(j,ensure_ascii=False))
print('FINAL',json.dumps({k:j.get(k) for k in ['id','style_id','mode','sequence_mode','sequence_seed','rh_task_ids','stage_status','elapsed','images']},ensure_ascii=False)[:8000],flush=True)
open(r'C:/Users/JT/AppData/Local/Temp/seq4_job','w').write(jid)
