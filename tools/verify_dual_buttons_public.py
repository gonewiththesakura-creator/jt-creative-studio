import json,urllib.request,websocket,itertools,time
x=json.load(urllib.request.urlopen('http://127.0.0.1:9228/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1)
def ev(e):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True,'awaitPromise':True}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:
   if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
   return r.get('result',{}).get('result',{}).get('value')
def wait(kind):
 for _ in range(90):
  try:
   if kind=='main':ready=ev("document.readyState==='complete'&&typeof generate==='function'&&!!document.getElementById('genCloudBtn')")
   else:ready=ev("document.readyState==='complete'&&typeof cloudGenerateNow==='function'&&!!document.getElementById('cloudGenerateCloud')")
   if ready:return
  except:pass
  time.sleep(1)
 raise RuntimeError('not ready')
def capture_original(path):
 ev(f"location.href='http://8.210.125.65:8189/{path}?dual=capture'");wait('orig')
 r=ev("(async()=>{currentMode='original';Object.keys(POOLS).forEach(k=>state[k]=POOLS[k][0]);render();cloudSeedMode.value='fixed';cloudSeed.value='135791357';cloudBatch.value='1';cloudHd.value='0';if(CLOUD_HAS_SEQUENCE)cloudSequence.value='off';cloudUpdateBatch();const old=window.fetch;let caps=[];window.fetch=async(u,o)=>{if(String(u).includes('/api/generate')){const b=JSON.parse(o.body);caps.push(b);return new Response(JSON.stringify({job_id:'cap'+caps.length}),{status:200,headers:{'Content-Type':'application/json'}})}if(String(u).includes('/api/job/cap'))return new Response(JSON.stringify({status:'done',elapsed:0,seed:135791357,prompt_mode:'options',generation_backend:String(u).endsWith('1')?'cloud':'local',width:768,height:1024,batch:1,images:[]}),{status:200,headers:{'Content-Type':'application/json'}});return old(u,o)};try{await Promise.all([cloudGenerateNow('cloud'),cloudGenerateNow('local')])}finally{window.fetch=old}return {caps,buttons:[cloudGenerateCloud.innerText,cloudGenerateLocal.innerText],panes:[...document.querySelectorAll('[data-backend]')].map(x=>x.dataset.backend)};})()")
 print(path,json.dumps(r,ensure_ascii=False)[:5000]);assert {x['generation_backend'] for x in r['caps']}=={'cloud','local'} and len(r['caps'])==2 and r['panes']==['cloud','local']
def capture_main():
 ev("location.href='http://8.210.125.65:8189/promptgen?dual=capture'");wait('main')
 r=ev("(async()=>{seedMode.value='fixed';genSeed.value='135791357';genBatch.value='1';genHd.value='0';sketchProcess.value='off';updateBatchSemantics();const old=window.fetch;let caps=[];window.fetch=async(u,o)=>{if(String(u).includes('/api/generate')){const b=JSON.parse(o.body);caps.push(b);return new Response(JSON.stringify({job_id:'cap'+caps.length}),{status:200,headers:{'Content-Type':'application/json'}})}if(String(u).includes('/api/job/cap'))return new Response(JSON.stringify({status:'done',elapsed:0,seed:135791357,prompt_mode:'options',generation_backend:String(u).endsWith('1')?'cloud':'local',width:768,height:1024,batch:1,images:[]}),{status:200,headers:{'Content-Type':'application/json'}});return old(u,o)};try{await Promise.all([generate('cloud'),generate('local')])}finally{window.fetch=old}return {caps,buttons:[genCloudBtn.innerText,genLocalBtn.innerText],panes:[...document.querySelectorAll('[data-backend]')].map(x=>x.dataset.backend)};})()")
 print('main',json.dumps(r,ensure_ascii=False)[:5000]);assert {x['generation_backend'] for x in r['caps']}=={'cloud','local'} and len(r['caps'])==2 and r['panes']==['cloud','local']
capture_original('original-sketch');capture_original('original-graphic');capture_main();print('PUBLIC_DUAL_BUTTON_REQUESTS_OK');w.close()
