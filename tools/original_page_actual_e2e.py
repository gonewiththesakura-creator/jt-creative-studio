import json,urllib.request,websocket,itertools,time,sys,subprocess,os
PORT=9227
PAGE=sys.argv[1]; SEED=int(sys.argv[2]); OUT=sys.argv[3]
x=json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'));t=next(i for i in x if i['type']=='page')
w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1)
def ev(e,awaitp=True):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True,'awaitPromise':awaitp}}))
 while True:
  r=json.loads(w.recv())
  if r.get('id')==i:
   if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
   return r.get('result',{}).get('result',{}).get('value')
ev(f"location.href='http://8.210.125.65:8189/{PAGE}?actual=e2e-v2'")
for _ in range(90):
 try:
  if ev("document.readyState==='complete' && typeof cloudGenerateNow==='function' && document.querySelectorAll('#grid .item').length>0"):break
 except Exception:pass
 time.sleep(1)
else:raise SystemExit('page not ready')
# Use deterministic first option in every original pool, original-character mode,
# one native image, HD off. This is a smoke test, not a style-quality sample.
setup=f"""(()=>{{
currentMode='original';Object.keys(POOLS).forEach(k=>state[k]=POOLS[k][0]);locked={{}};render();
cloudSeedMode.value='fixed';cloudSeed.value='{SEED}';cloudBatch.value='1';cloudHd.value='0';if(CLOUD_HAS_SEQUENCE)cloudSequence.value='off';cloudUpdateBatch();
window.__actualJob=null;window.__actualError=null;const old=window.fetch;if(!window.__e2eWrapped){{window.fetch=async(u,o)=>{{const r=await old(u,o);if(String(u).includes('/api/generate')){{try{{window.__actualJob=await r.clone().json()}}catch(e){{window.__actualError=String(e)}}}}return r}};window.__e2eWrapped=true}}
cloudGenerateNow();return {{style:CLOUD_STYLE_ID,trigger:CLOUD_TRIGGER,prompt:cloudStripStyleTokens(buildPositive()),seed:+cloudSeed.value}};
}})()"""
start=ev(setup);print('BROWSER_STARTED',json.dumps(start,ensure_ascii=False),flush=True)
# The browser has executed the real submit path; capture its returned job id.
job_resp=None
for _ in range(60):
 job_resp=ev("window.__actualJob")
 if job_resp:break
 err=ev("window.__actualError");
 if err:raise SystemExit(err)
 time.sleep(1)
if not job_resp or not job_resp.get('job_id'):
 print('PAGE_STATUS',ev('cloudStatus.textContent'));raise SystemExit('no job id')
jid=job_resp['job_id'];print('JOB_ID',jid,flush=True)
# Poll the actual panel job independently of the browser rendering loop.
job=None
for _ in range(400):
 with urllib.request.urlopen('http://8.210.125.65:8189/api/job/'+jid,timeout=60) as r:job=json.load(r)
 if job.get('status') in ('done','error'):break
 time.sleep(3)
if job.get('status')!='done' or len(job.get('images',[]))!=1:
 print('JOB_FAIL',json.dumps(job,ensure_ascii=False)[:5000]);raise SystemExit('job did not yield exactly one image')
print('JOB',json.dumps({k:job.get(k) for k in ['id','status','style_id','mode','seed','seed_mode','batch','hd','width','height','rh_task_id','elapsed','prompt_mode','sequence_mode']},ensure_ascii=False),flush=True)
assert job['seed']==SEED and job['style_id']==start['style'] and job['selection_snapshot']['source_page']=='original_'+start['style']
# Favorite through the same public endpoint, then verify reproducibility fields.
req=urllib.request.Request('http://8.210.125.65:8189/api/favorites',data=json.dumps({'job_id':jid,'image_index':0}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=240) as r:fav=json.load(r)
print('FAVORITE',json.dumps({k:fav.get(k) for k in ['id','job_id','seed','seed_mode','prompt_mode']},ensure_ascii=False),flush=True)
assert fav.get('seed')==SEED and fav.get('selection_snapshot',{}).get('source_page')=='original_'+job['style_id']
# Download this single smoke artifact and validate PNG.
url=job['images'][0]['url'];dest=os.path.expandvars(OUT);rr=subprocess.run(['curl','-4','-fL','--max-time','240','-sS','-o',dest,url],capture_output=True,text=True)
if rr.returncode:raise SystemExit(rr.stderr)
with open(dest,'rb') as f:magic=f.read(8)
assert magic==b'\x89PNG\r\n\x1a\n'
from PIL import Image
im=Image.open(dest);print('PNG',im.size,os.path.getsize(dest),dest,flush=True)
open(dest+'.result.json','w',encoding='utf8').write(json.dumps({'page':PAGE,'job':job,'favorite':fav,'browser':start},ensure_ascii=False,indent=2))
w.close()
