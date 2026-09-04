import base64,itertools,json,pathlib,time,urllib.request,websocket
PORT=9241;BASE='http://127.0.0.1:8773';OUT=pathlib.Path.home()/r'AppData/Local/Temp';OUT.mkdir(parents=True,exist_ok=True)
tab=next(x for x in json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list')) if x['type']=='page');ws=websocket.create_connection(tab['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);exceptions=[]
def call(method,params=None):
 i=next(seq);ws.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  r=json.loads(ws.recv())
  if r.get('method')=='Runtime.exceptionThrown':exceptions.append(r)
  if r.get('id')==i:return r
def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True});assert not r.get('result',{}).get('exceptionDetails'),r;return r['result']['result'].get('value')
def viewport(w,h):call('Emulation.setDeviceMetricsOverride',{'width':w,'height':h,'deviceScaleFactor':1,'mobile':w<=480,'screenWidth':w,'screenHeight':h})
def nav(route,ready):
 ev(f"location.href={json.dumps(BASE+route+'?e2e='+str(time.time_ns()))}")
 for _ in range(120):
  try:
   if ev("document.readyState==='complete'&&("+ready+")"):exceptions.clear();time.sleep(.2);return
  except:pass
  time.sleep(.25)
 raise RuntimeError(route)
def shot(name):
 p=OUT/name;p.write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['result']['data']));return str(p)

# Hanimanga complete UI/profile behavior.
viewport(1200,820);nav('/',"typeof generate==='function'")
han=ev("""(()=>{document.querySelector('[data-style=hanmanga]').click();const c=STYLE_CONFIGS.hanmanga;return{styles:[...document.querySelectorAll('[data-style]')].map(x=>x.dataset.style),currentStyle,currentMode,categories:Object.keys(c.pools).length,rows:Object.values(c.pools).reduce((n,a)=>n+a.length,0),trigger:c.trigger,lora1:c.lora1,lora2:c.lora2,backendAlias:'backendStyleId'in c,drawers:[...document.querySelectorAll('[data-drawer]')].map(x=>x.classList.contains('open')),defaults:Object.fromEntries(Object.entries(c.defaultSelections).map(([k,label])=>[k,selectedItems(k).map(x=>x[0])])),prompt:buildPrompt().slice(0,180),multi:c.multi}})()""")
assert han['styles']==['cold','sketch','graphic','hanmanga','nff'] and han['currentStyle']=='hanmanga' and han['currentMode']=='original'
assert han['categories']==32 and han['rows']==382 and han['trigger']=='jt_liulistyle_v1' and han['lora1']==han['lora2']=='08_liuli_style_v1_step600.safetensors' and not han['backendAlias'] and not any(han['drawers'])
assert han['prompt'].lower().count('jt_liulistyle_v1')==1
# Open body drawer; exercise lock and multi-select without changing other styles.
interaction=ev("""(()=>{const before=JSON.stringify(STYLE_CONFIGS.sketch.pools);document.querySelector('[data-drawer=body] .drawer-head').click();const first=document.querySelector('[data-drawer=body] .item');const lock=first.querySelector('.lock');lock.click();const locked=Object.values(lockedByStyle.hanmanga).some(Boolean);const multi=[...document.querySelectorAll('[data-drawer=body] select[multiple]')][0];if(multi){[...multi.options].forEach((o,i)=>o.selected=i===1||i===2);multi.dispatchEvent(new Event('change',{bubbles:true}))}return{open:document.querySelector('[data-drawer=body]').classList.contains('open'),locked,multiValues:multi?selectedItems([...Object.keys(STYLE_CONFIGS.hanmanga.pools)].find(k=>STYLE_CONFIGS.hanmanga.multi.includes(k)&&STYLE_CONFIGS.hanmanga.labels[k]===multi.closest('.item').querySelector('.item-name').textContent)).map(x=>x[0]):[],sketchUntouched:before===JSON.stringify(STYLE_CONFIGS.sketch.pools)}})()""")
assert interaction['open'] and interaction['locked'] and interaction['sketchUntouched'],interaction
# Intercept two backend submissions and assert exact trusted style id + visible parameters.
payloads=ev("""(async()=>{const oldFetch=window.fetch,sent=[],jobs={};window.fetch=async(input,opt={})=>{const url=String(input);if(url==='/api/generate'){const body=JSON.parse(opt.body);sent.push(body);const id='fixture-'+body.generation_backend;jobs[id]={id,status:'done',provider_status:body.generation_backend==='local'?'LOCAL_DONE':'DONE',progress_pct:100,elapsed:1,seed:body.seed,generation_backend:body.generation_backend,images:[{url:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='}]};return{ok:true,json:async()=>({job_id:id})}}if(url.startsWith('/api/job/'))return{ok:true,json:async()=>jobs[url.split('/').pop()]};return oldFetch(input,opt)};seedMode.value='fixed';genSeed.value='24681357';genW.value='640';genH.value='960';genBatch.value='2';genHd.value='1';await generate('cloud');await generate('local');window.fetch=oldFetch;return sent})()""")
assert len(payloads)==2 and {x['generation_backend'] for x in payloads}=={'cloud','local'}
for body in payloads:
 assert body['style_id']=='hanmanga' and body['width']==640 and body['height']==960 and body['batch']==2 and body['hd']==1 and body['seed']==24681357
 assert body['selection_snapshot']['style']=='hanmanga'
# Manual prompt and snapshot restoration.
manual=ev("""(()=>{importGeneratedPrompt.click();manualPositive.value+=' custom edit';const snap=snapshotSelections();currentStyle='cold';prepareStyle('cold');applySnapshot(snap);return{mode:promptMode.value,positive:manualPositive.value,style:currentStyle,seed:+genSeed.value,drawers:[...openDrawers]}})()""")
assert manual['mode']=='manual' and manual['positive'].endswith(' custom edit') and manual['style']=='hanmanga' and manual['seed']==24681357
han_desktop=shot('liuli_hanmanga_desktop.png');viewport(393,852);ev('window.scrollTo(0,0)');time.sleep(.2);han_mobile_layout=ev("(()=>({overflow:document.documentElement.scrollWidth-innerWidth,buttonHeight:genCloudBtn.getBoundingClientRect().height,styleButtons:document.querySelectorAll('[data-style]').length,footer:getComputedStyle(document.querySelector('.creation-footer')).position}))()")
assert han_mobile_layout['overflow']<=1 and han_mobile_layout['buttonHeight']>=44 and han_mobile_layout['styleButtons']==5 and han_mobile_layout['footer']=='fixed';han_mobile=shot('liuli_hanmanga_mobile.png')
print('HANMANGA_BROWSER',han,interaction,{'payloads':[{k:x[k] for k in ['style_id','generation_backend','width','height','batch','hd','seed']} for x in payloads],'manual':manual,'mobile':han_mobile_layout})

# Realcomic complete no-credit flow with one transient submit failure and recovery.
viewport(1200,820);nav('/realcomic',"typeof acceptFile==='function'")
real=ev("""(async()=>{const oldFetch=window.fetch,calls=[],submits=[],jobs={};let submitAttempt=0,polls=0;window.fetch=async(input,opt={})=>{const url=String(input);calls.push(url);if(url==='/api/realcomic-upload')return{ok:true,json:async()=>({fileName:'api/browser-fixture.png',filename:'fixture.png',mediaType:'image/png'})};if(url==='/api/ai-app-generate'){submits.push(JSON.parse(opt.body));submitAttempt++;if(submitAttempt===1)throw new TypeError('transient');jobs['fixture-real']={id:'fixture-real',workflow:'realcomic',status:'running',provider_status:'RUNNING',progress_pct:12,elapsed:null,images:[]};return{ok:true,json:async()=>({job_id:'fixture-real'})}};if(url==='/api/job/fixture-real'){polls++;if(polls>1)jobs['fixture-real']={...jobs['fixture-real'],status:'done',provider_status:'DONE',progress_pct:100,elapsed:2,images:[{url:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='}]};return{ok:true,json:async()=>jobs['fixture-real']}};if(url==='/api/jobs')return{ok:true,json:async()=>[jobs['fixture-real']]};if(url==='/api/favorites')return{ok:true,json:async()=>[]};return oldFetch(input,opt)};const bytes=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='),c=>c.charCodeAt(0));const file=new File([bytes],'fixture.png',{type:'image/png'});await acceptFile(file);requirements.value='保留构图并去除文字';realcomicGenerate.click();for(let i=0;i<80&&!document.querySelector('.task-spin.done');i++)await new Promise(r=>setTimeout(r,100));const task=document.querySelector('.task-card');await history();await favorites();window.fetch=oldFetch;return{calls,submits,submitAttempt,polls,uploadedFileName,uploadText:uploadState.textContent,taskCount:tasks.size,taskMeta:task?.querySelector('.task-meta')?.textContent,resultImages:task?.querySelectorAll('.task-result img').length,downloadLinks:task?.querySelectorAll('.task-result a').length,favoriteButtons:task?.querySelectorAll('.favorite').length,history:histList.innerText,favorites:favList.innerText,active:sessionStorage.getItem(ACTIVE_KEY),cloudButtons:document.querySelectorAll('#realcomicGenerate').length,hasLocal:document.body.innerText.includes('本地生成')}})()""")
assert real['submitAttempt']==2 and len(real['submits'])==2 and real['submits'][0]['client_request_id']==real['submits'][1]['client_request_id']
body=real['submits'][1];assert body['workflow']=='realcomic' and body['media']=={'source_image':'api/browser-fixture.png'} and body['params']=={'requirements':'保留构图并去除文字'}
assert real['resultImages']==1 and real['downloadLinks']==1 and real['favoriteButtons']==1 and real['active'] is None and real['cloudButtons']==1 and not real['hasLocal']
assert 'fixture-real' in real['taskMeta'] and 'fixture-real' in real['history']
real_desktop=shot('realcomic_workbench_desktop.png');viewport(393,852);ev('window.scrollTo(0,0)');time.sleep(.2);real_mobile_layout=ev("(()=>({overflow:document.documentElement.scrollWidth-innerWidth,generateHeight:realcomicGenerate.getBoundingClientRect().height,footer:getComputedStyle(document.querySelector('.creation-footer')).position,dropWidth:sourceDrop.getBoundingClientRect().width,nav:[...document.querySelectorAll('.topnav-link')].map(x=>x.innerText)}))()")
assert real_mobile_layout['overflow']<=1 and real_mobile_layout['generateHeight']>=44 and real_mobile_layout['footer']=='fixed' and real_mobile_layout['dropWidth']>300;real_mobile=shot('realcomic_workbench_mobile.png')
print('REALCOMIC_BROWSER',real,real_mobile_layout)
assert not exceptions,exceptions
print('SCREENSHOTS',[han_desktop,han_mobile,real_desktop,real_mobile])
print('LIULI_REALCOMIC_BROWSER_E2E_OK')
