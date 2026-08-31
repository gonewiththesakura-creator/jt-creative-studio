import json,subprocess,time
base='http://8.210.125.65:8189'
styles=[
 ('cold','adult Makima, recognizable auburn braided hair, golden ringed eyes, composed authority figure'),
 ('sketch','adult 2B android, recognizable white bob hair, black visor, black combat dress'),
 ('graphic','adult Shenhe, recognizable elegant adeptus disciple, long white hair, pale cyan eyes'),
]
records=[]
def req(args,timeout=40):
 r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if r.returncode: raise RuntimeError(r.stderr)
 return json.loads(r.stdout)
for style,char_prompt in styles:
 snapshot={'style':style,'mode':'character','state':{'character_inspired':['角色测试',char_prompt]},'locked':{},'width':512,'height':768,'batch':1,'hd':0}
 payload={'workflow':'anima02','prompt':'masterpiece, best quality, clearly adult woman, '+char_prompt+', simple portrait, plain background','width':512,'height':768,'batch':1,'hd':0,'style_id':style,'mode':'character','selection_snapshot':snapshot}
 r=req(['curl','-sS','--max-time','30','-X','POST',base+'/api/generate','-H','Content-Type: application/json','--data',json.dumps(payload)]);jid=r['job_id'];print('SUBMIT',style,jid,flush=True)
 for i in range(80):
  try:j=req(['curl','-sS','--max-time','20',base+'/api/job/'+jid],30)
  except Exception as e: print(' retry',e,flush=True);time.sleep(2);continue
  print(' ',j['status'],j.get('provider_status'),j.get('progress_pct'),flush=True)
  if j['status']!='running':break
  time.sleep(3)
 if j['status']!='done':raise SystemExit(style+' FAIL '+json.dumps(j,ensure_ascii=False))
 assert j['style_id']==style and j['mode']=='character' and j['selection_snapshot']['mode']=='character'
 print('DONE',style,j['rh_task_id'],j['elapsed'],len(j['images']),flush=True);records.append(j)
print('RESULTS',json.dumps([{k:j.get(k) for k in ['id','style_id','mode','rh_task_id','elapsed','status']} for j in records],ensure_ascii=False),flush=True)
