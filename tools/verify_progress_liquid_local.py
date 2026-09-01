import json,urllib.request,websocket,itertools,time,base64,os
x=json.load(urllib.request.urlopen('http://127.0.0.1:9235/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);errors=[]
def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  r=json.loads(w.recv())
  if r.get('method')=='Runtime.exceptionThrown':errors.append(r)
  if r.get('id')==i:return r
def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True});
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
call('Runtime.enable');call('Page.enable')
for _ in range(80):
 try:
  if ev("document.readyState==='complete'&&typeof setLiquidProgress==='function'"):break
 except:pass
 time.sleep(.2)
errors.clear()
# Numeric fill follows exact progress and never auto-completes.
states=ev("(()=>{const b=genLocalBtn;setLiquidLoading(b,true);return [3,27,63,90,96,100].map(p=>{setLiquidProgress(b,p);return{p,css:b.style.getPropertyValue('--liquid-progress'),label:b.querySelector('.liquid-percent').innerText,level:getComputedStyle(b).getPropertyValue('--liquid-level').trim()}})})()")
print('LIQUID_STATES',states)
for state in states:
 assert state['css']==f"{state['p']}%" and state['label']==f"{state['p']}%"
assert [x['level'] for x in states]==['calc(100% - 3%)','calc(100% - 27%)','calc(100% - 63%)','calc(100% - 90%)','calc(100% - 96%)','calc(100% - 100%)']
# One failure is retried, progress remains monotonic, terminal success returns.
res=ev("(async()=>{const seq=[{status:'running',progress_pct:27,provider_status:'LOCAL_RUNNING'},new Error('network'),{status:'running',progress_pct:63,provider_status:'LOCAL_RUNNING'},{status:'running',progress_pct:96,provider_status:'RESULT_DOWNLOADING',transfer_index:3,transfer_total:4},{status:'done',progress_pct:100,provider_status:'LOCAL_DONE',images:[]}];let i=0;const oldFetch=window.fetch,oldSetTimeout=window.setTimeout,updates=[];window.fetch=async()=>{const v=seq[i++];if(v instanceof Error)throw v;return{ok:true,json:async()=>v}};window.setTimeout=(fn)=>{fn();return 0};try{const j=await pollJobResilient('test',(next,broken,retry)=>updates.push(broken?{broken,retry}:{progress:next.progress_pct,status:next.provider_status}));return{updates,j}}finally{window.fetch=oldFetch;window.setTimeout=oldSetTimeout}})()")
print('POLL_RETRY',res);assert res['j']['status']=='done';assert res['updates'][1]=={'broken':True,'retry':1};assert [x['progress'] for x in res['updates'] if 'progress' in x]==[27,63,96,100]
# Snapshot at an intermediate value for visual review.
ev("setLiquidLoading(genCloudBtn,true);setLiquidProgress(genCloudBtn,63);setLiquidLoading(genLocalBtn,true);setLiquidProgress(genLocalBtn,27)")
r=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});p=os.path.expandvars('$LOCALAPPDATA/Temp/progress_liquid_review.png');open(p,'wb').write(base64.b64decode(r['result']['data']));print('SCREENSHOT',p)
print('EXCEPTIONS',len(errors));assert not errors
print('PROGRESS_LIQUID_BROWSER_OK');w.close()
