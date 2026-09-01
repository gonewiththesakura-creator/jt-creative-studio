import base64,gzip,json,os,time,urllib.request,urllib.error,itertools,websocket
PORT=9237;BASE='http://127.0.0.1:8771'
tabs=json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'));tab=next(x for x in tabs if x['type']=='page');ws=websocket.create_connection(tab['webSocketDebuggerUrl'],timeout=60);ids=itertools.count(1);exceptions=[]
def call(method,params=None):
 i=next(ids);ws.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  msg=json.loads(ws.recv())
  if msg.get('method')=='Runtime.exceptionThrown':exceptions.append(msg)
  if msg.get('id')==i:return msg
def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
def go(path,ready):
 ev(f"location.href={json.dumps(BASE+path+'?e2e='+str(time.time_ns()))}")
 for _ in range(120):
  try:
   if ev("document.readyState==='complete'&&("+ready+")"):return
  except Exception:pass
  time.sleep(.15)
 raise RuntimeError(path+' not ready')
def shot(name,width,height):
 call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600,'screenWidth':width,'screenHeight':height})
 time.sleep(.25);raw=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['result']['data'];p=os.path.expandvars(f'$LOCALAPPDATA/Temp/{name}.png');open(p,'wb').write(base64.b64decode(raw));return p
call('Runtime.enable');call('Page.enable')
# Main motion: a backend target of 100 must visibly interpolate through intermediate frames.
go('/',"typeof setLiquidProgress==='function'&&!!document.querySelector('[data-style=nff]')")
motion=ev("(async()=>{const b=genLocalBtn;setLiquidLoading(b,true);setLiquidProgress(b,0,true);const samples=[];setLiquidProgress(b,100);for(let i=0;i<12;i++){await new Promise(r=>setTimeout(r,150));samples.push(Number.parseFloat(b.style.getPropertyValue('--liquid-progress')))}return{samples,target:Number(b.dataset.progressTarget),labels:[...b.querySelectorAll('.liquid-percent')].map(x=>x.innerText),fill:getComputedStyle(b.querySelector('.liquid-fill')).transform}})()")
print('MOTION',motion);s=motion['samples'];assert motion['target']==100 and len(set(round(x,1) for x in s))>=6 and all(a<=b+.001 for a,b in zip(s,s[1:])) and 0<s[0]<100 and s[-1]>98
# Targets never regress even if a stale poll arrives.
monotonic=ev("(()=>{const b=genCloudBtn;setLiquidLoading(b,true);setLiquidProgress(b,63,true);setLiquidProgress(b,27,true);return{shown:Number.parseFloat(b.style.getPropertyValue('--liquid-progress')),target:Number(b.dataset.progressTarget)}})()")
print('MONOTONIC',monotonic);assert monotonic=={'shown':63,'target':63}
# NFF UI/pool/prompt contract in the actual browser.
nff=ev("(()=>{document.querySelector('[data-style=nff]').click();const before={style:currentStyle,pools:Object.keys(cfg().pools).length,trigger:cfg().trigger,lora1:cfg().lora1,lora2:cfg().lora2,sketchEqual:JSON.stringify(cfg().pools)===JSON.stringify(STYLE_CONFIGS.sketch.pools),sequenceVisible:getComputedStyle(sketchProcessRow).display,drawers:[...document.querySelectorAll('.drawer')].map(x=>x.classList.contains('open'))};document.querySelector('.drawer-head').click();return{...before,firstPicker:!!document.querySelector('.drawer.open .picker'),prompt:buildPrompt().slice(0,80)}})()")
print('NFF',nff);assert nff['style']=='nff' and nff['pools']==32 and nff['trigger']=='jt_nffstyle_v1' and nff['lora1']==nff['lora2']=='06_nff_style_v1_step2000.safetensors' and nff['sketchEqual'] and nff['sequenceVisible']=='none' and not any(nff['drawers']) and nff['firstPicker'] and nff['prompt'].startswith('jt_nffstyle_v1')
# Completed-job recovery uses session job id and removes it after rendering.
recover=ev("(async()=>{const oldFetch=fetch,calls=[];window.fetch=async input=>{const url=String(input);calls.push(url);if(url.includes('/api/job/recover-local'))return{ok:true,json:async()=>({id:'recover-local',status:'done',generation_backend:'local',elapsed:1,seed:7,prompt_mode:'options',images:[{preview_url:'data:image/gif;base64,R0lGODlhAQABAAAAACw=',url:'#'}]})};throw new Error('unexpected '+url)};sessionStorage.setItem(activeJobKey('local'),'recover-local');try{await resumeActiveJobs();return{key:sessionStorage.getItem(activeJobKey('local')),images:genLocalResult.querySelectorAll('img').length,status:genLocalStatus.innerText,calls}}finally{window.fetch=oldFetch}})()")
print('RECOVER',recover);assert recover['key'] is None and recover['images']>=1 and '恢复完成' in recover['status'] and recover['calls']==['/api/job/recover-local']
# Layout screenshots and no overflow.
call('Emulation.setDeviceMetricsOverride',{'width':1200,'height':820,'deviceScaleFactor':1,'mobile':False,'screenWidth':1200,'screenHeight':820});time.sleep(.2)
main_layout=ev("(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('.liquid-button')].map(x=>x.getBoundingClientRect().height),styleCount:document.querySelectorAll('[data-style]').length}))()")
main_desktop=shot('nff_motion_main_desktop',1200,820)
call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':1,'mobile':True,'screenWidth':393,'screenHeight':852});time.sleep(.2)
main_mobile_layout=ev("(()=>{const footer=document.querySelector('.creation-footer').getBoundingClientRect();return{width:innerWidth,doc:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('.liquid-button')].map(x=>x.getBoundingClientRect().height),footerBottom:Math.round(footer.bottom),viewport:innerHeight,position:getComputedStyle(document.querySelector('.creation-footer')).position}})()")
main_mobile=shot('nff_motion_main_mobile',393,852)
print('MAIN_LAYOUT',main_layout,main_mobile_layout);assert main_layout['styleCount']==4 and main_layout['doc']<=main_layout['width'] and main_mobile_layout['doc']<=main_mobile_layout['width'] and min(main_mobile_layout['buttons'])>=44 and main_mobile_layout['position']=='fixed' and main_mobile_layout['footerBottom']<=main_mobile_layout['viewport']
# Original pages: closed by default, one click exposes direct select, legacy grid empty.
original_shots=[]
for path,label in [('/original-sketch','sketch'),('/original-graphic','graphic')]:
 call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':1,'mobile':True,'screenWidth':393,'screenHeight':852});time.sleep(.2)
 go(path,"typeof renderOriginalWorkbench==='function'&&document.querySelectorAll('.original-drawer').length>0")
 state=ev("(()=>{const before={closed:[...document.querySelectorAll('.original-drawer')].every(x=>!x.classList.contains('open')),legacyChildren:grid.children.length,heading:document.querySelector('.original-heading h1').innerText};document.querySelector('.original-drawer-head').click();const footer=document.querySelector('.creation-footer').getBoundingClientRect();return{...before,pickers:document.querySelectorAll('.original-drawer.open .original-picker').length,valueSummaries:document.querySelectorAll('.original-value-summary').length,overflow:document.documentElement.scrollWidth-innerWidth,footerPosition:getComputedStyle(document.querySelector('.creation-footer')).position,footerBottom:Math.round(footer.bottom),viewport:innerHeight}})()")
 print('ORIGINAL',path,state);assert state['closed'] and state['legacyChildren']==0 and state['heading']=='创作设置' and state['pickers']>0 and state['valueSummaries']==0 and state['overflow']==0 and state['footerPosition']=='fixed' and state['footerBottom']<=state['viewport']
 original_shots.append(shot('nff_motion_original_'+label+'_mobile',393,852))
 original_shots.append(shot('nff_motion_original_'+label+'_desktop',1200,820))
# HTTP gzip and ETag/304.
req=urllib.request.Request(BASE+'/',headers={'Accept-Encoding':'gzip'});resp=urllib.request.urlopen(req,timeout=20);compressed=resp.read();etag=resp.headers['ETag'];assert resp.headers.get('Content-Encoding')=='gzip' and b'JT ' in gzip.decompress(compressed);print('GZIP',len(compressed),len(gzip.decompress(compressed)),etag)
try:urllib.request.urlopen(urllib.request.Request(BASE+'/',headers={'If-None-Match':etag}),timeout=20);raise AssertionError('expected 304')
except urllib.error.HTTPError as e:assert e.code==304;print('ETAG_304',e.code)
print('SCREENSHOTS',main_desktop,main_mobile,original_shots)
print('EXCEPTIONS',len(exceptions));assert not exceptions
print('FEATURE_BROWSER_E2E_OK');ws.close()
