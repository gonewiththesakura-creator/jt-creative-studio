import json,urllib.request,websocket,itertools,time,subprocess,os
from pathlib import Path
from PIL import Image
PORT=9228;SEED=161803398
x=json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1)
def ev(e):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True,'awaitPromise':True}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:
   if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
   return r.get('result',{}).get('result',{}).get('value')
ev("location.href='http://8.210.125.65:8189/original-graphic?dual=actual-pair-v1'")
for _ in range(90):
 try:
  if ev("document.readyState==='complete'&&typeof cloudGenerateNow==='function'&&document.querySelectorAll('#grid .item').length>0"):break
 except:pass
 time.sleep(1)
# First options, same exact controls for both buttons. Start both without waiting.
start=ev(f"""(()=>{{currentMode='original';Object.keys(POOLS).forEach(k=>state[k]=POOLS[k][0]);locked={{}};render();cloudSeedMode.value='fixed';cloudSeed.value='{SEED}';cloudBatch.value='1';cloudHd.value='0';cloudUpdateBatch();window.__pairJobs=[];const old=window.fetch;if(!window.__pairWrapped){{window.fetch=async(u,o)=>{{const r=await old(u,o);if(String(u).includes('/api/generate')){{try{{const j=await r.clone().json();if(j.job_id)window.__pairJobs.push(j.job_id)}}catch(e){{}}}}return r}};window.__pairWrapped=true}}cloudGenerateNow('cloud');cloudGenerateNow('local');return {{prompt:cloudStripStyleTokens(buildPositive()),seed:+cloudSeed.value,buttons:[cloudGenerateCloud.innerText,cloudGenerateLocal.innerText]}}}})()""")
print('START',json.dumps(start,ensure_ascii=False),flush=True)
ids=[]
for _ in range(90):
 ids=ev('window.__pairJobs') or []
 if len(ids)>=2:break
 time.sleep(1)
if len(ids)!=2:raise SystemExit('did not capture two job ids: '+repr(ids))
print('IDS',ids,flush=True)
jobs={}
for _ in range(500):
 for jid in ids:
  if jid not in jobs or jobs[jid].get('status') not in ('done','error'):
   with urllib.request.urlopen('http://8.210.125.65:8189/api/job/'+jid,timeout=60) as r:jobs[jid]=json.load(r)
 if all(j.get('status') in ('done','error') for j in jobs.values()):break
 time.sleep(3)
print('JOBS',json.dumps({i:{k:j.get(k) for k in ['status','generation_backend','seed','batch','hd','width','height','elapsed','rh_task_id','prompt_ids','error']} for i,j in jobs.items()},ensure_ascii=False),flush=True)
assert all(j['status']=='done' for j in jobs.values());assert {j['generation_backend'] for j in jobs.values()}=={'cloud','local'};assert all(j['seed']==SEED and len(j.get('images',[]))==1 for j in jobs.values())
outdir=Path(os.path.expandvars(r'$LOCALAPPDATA/Temp/dual_pair'));outdir.mkdir(exist_ok=True)
for jid,j in jobs.items():
 backend=j['generation_backend'];im=j['images'][0];url=im['url'];url='http://8.210.125.65:8189'+url if url.startswith('/') else url;dest=outdir/f'{backend}.png';rr=subprocess.run(['curl','-4','-fL','--max-time','300','-sS','-o',str(dest),url],capture_output=True,text=True);assert rr.returncode==0,rr.stderr
 x=Image.open(dest);print('PNG',backend,x.size,dest.stat().st_size,sorted(x.info.keys()),flush=True);assert x.size==(768,1024)
(outdir/'result.json').write_text(json.dumps({'start':start,'jobs':jobs},ensure_ascii=False,indent=2),encoding='utf8');print('PUBLIC_CLOUD_LOCAL_ACTUAL_PAIR_OK',outdir,flush=True);w.close()
