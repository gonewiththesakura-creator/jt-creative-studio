import json,urllib.request,websocket,itertools,time,base64,os
PORT=9236;BASE='http://8.210.125.65:8189'
x=json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);errors=[]
def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  r=json.loads(w.recv())
  if r.get('method')=='Runtime.exceptionThrown':errors.append(r)
  if r.get('id')==i:return r
def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
def go(path,ready):
 ev(f"location.href={json.dumps(BASE+path+'?progress='+str(time.time_ns()))}")
 for _ in range(120):
  try:
   if ev("document.readyState==='complete'&&"+ready):break
  except:pass
  time.sleep(.25)
 else:raise RuntimeError(path+' not ready')
 errors.clear()
call('Runtime.enable');call('Page.enable')
for path,ready,button in [('/',"typeof setLiquidProgress==='function'",'genLocalBtn'),('/original-sketch',"typeof setLiquidProgress==='function'",'cloudGenerateLocal'),('/original-graphic',"typeof setLiquidProgress==='function'",'cloudGenerateLocal')]:
 go(path,ready)
 states=ev(f"(()=>{{const b={button};setLiquidLoading(b,true);return[3,27,63,96,100].map(p=>{{setLiquidProgress(b,p);return[p,b.style.getPropertyValue('--liquid-progress'),b.querySelector('.liquid-percent').innerText,getComputedStyle(b).getPropertyValue('--liquid-level').trim()]}})}})()")
 print('PUBLIC_LIQUID',path,states);assert all(x[1]==str(x[0])+'%' and x[2]==str(x[0])+'%' for x in states)
# Simulate one real fetch failure and recovery on the deployed main page.
go('/',"typeof pollJobResilient==='function'")
retry=ev("(async()=>{const seq=[{status:'running',progress_pct:27,provider_status:'LOCAL_RUNNING'},new Error('network'),{status:'running',progress_pct:96,provider_status:'RESULT_DOWNLOADING',transfer_index:3,transfer_total:4},{status:'done',progress_pct:100,provider_status:'LOCAL_DONE',images:[]}];let i=0;const oldFetch=fetch,oldTimer=setTimeout,updates=[];window.fetch=async()=>{const v=seq[i++];if(v instanceof Error)throw v;return{ok:true,json:async()=>v}};window.setTimeout=fn=>{fn();return 0};try{const j=await pollJobResilient('test',(next,broken,r)=>updates.push(broken?{broken,retry:r}:{progress:next.progress_pct}));return{j,updates}}finally{window.fetch=oldFetch;window.setTimeout=oldTimer}})()")
print('PUBLIC_RETRY',retry);assert retry['j']['status']=='done' and retry['updates'][1]=={'broken':True,'retry':1}
# New API fields and old completed result compatibility.
fields=ev("(async()=>{const r=await fetch('/api/job/e81c4b4ae826');const j=await r.json();return{ok:r.ok,status:j.status,images:j.images.length,hasPromptIds:Array.isArray(j.prompt_ids),fields:['transfer_index','transfer_total','transfer_started','transfer_finished'].every(k=>Object.prototype.hasOwnProperty.call(j,k)),firstImage:j.images[0]}})()")
print('PUBLIC_FIELDS',fields);assert fields['ok'] and fields['status']=='done' and fields['images']==4 and fields['hasPromptIds'] and fields['fields']
# Intermediate deployed screenshot for final review.
ev("setLiquidLoading(genCloudBtn,true);setLiquidProgress(genCloudBtn,63);setLiquidLoading(genLocalBtn,true);setLiquidProgress(genLocalBtn,27);document.querySelector('.creation-scroll').scrollTop=document.querySelector('.creation-scroll').scrollHeight")
call('Emulation.setDeviceMetricsOverride',{'width':1200,'height':820,'deviceScaleFactor':1,'mobile':False,'screenWidth':1200,'screenHeight':820});time.sleep(.5);r=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});p=os.path.expandvars('$LOCALAPPDATA/Temp/progress_public_review.png');open(p,'wb').write(base64.b64decode(r['result']['data']));print('SCREENSHOT',p)
print('EXCEPTIONS',len(errors));assert not errors
print('PUBLIC_PROGRESS_UI_OK');w.close()
