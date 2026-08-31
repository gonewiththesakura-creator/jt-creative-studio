import json,urllib.request,websocket,itertools,time
x=json.load(urllib.request.urlopen('http://127.0.0.1:9226/json/list'));t=next(i for i in x if i['type']=='page')
w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=30);seq=itertools.count(1)
def ev(e):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True,'awaitPromise':True}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:
   if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
   return r.get('result',{}).get('result',{}).get('value')
for _ in range(60):
 if ev("document.readyState==='complete' && typeof generate==='function' && !!document.getElementById('genSeed')"):break
 time.sleep(1)
# Verify initial state and exact public mapping.
print('initial',ev("({style:currentStyle,promptMode:promptMode.value,seedMode:seedMode.value,seed:genSeed.value,batchNote:batchNote.textContent,batchDisabled:genBatch.disabled,triggers:Object.fromEntries(Object.entries(STYLE_CONFIGS).map(([k,v])=>[k,v.trigger]))})"))
# Capture the request body without spending credits.
cap=ev("(async()=>{promptMode.value='manual';updatePromptModeUI();manualPositive.value='jt_style1_v1, manual portrait, holding a book';manualNegative.value='bad hands, text';seedMode.value='fixed';genSeed.value='123456789';genBatch.value='4';sketchProcess.value='off';updateBatchSemantics();const old=window.fetch;let captured=null;window.fetch=async(u,o)=>{if(String(u).includes('/api/generate')){captured=JSON.parse(o.body);return new Response(JSON.stringify({job_id:'capture'}),{status:200,headers:{'Content-Type':'application/json'}})}if(String(u).includes('/api/job/capture'))return new Response(JSON.stringify({status:'done',elapsed:0,seed:123456789,prompt_mode:'manual',images:[]}),{status:200,headers:{'Content-Type':'application/json'}});return old(u,o)};try{await generate()}finally{window.fetch=old}return {captured,batchNote:batchNote.textContent,batchDisabled:genBatch.disabled,manualDisplay:manualPromptPanel.style.display};})()")
print('ordinary capture',json.dumps(cap,ensure_ascii=False));b=cap['captured'];assert b['prompt']=='jt_style1_v1, manual portrait, holding a book' and b['negative_prompt']=='bad hands, text' and b['prompt_mode']=='manual' and b['seed']==123456789 and b['seed_mode']=='fixed' and b['batch']==4 and b['sequence_mode']=='off'
# Staged semantics: front-end forces batch one and keeps seed.
stage=ev("sketchProcess.value='4';genBatch.value='4';updateBatchSemantics();({batch:+genBatch.value,disabled:genBatch.disabled,note:batchNote.textContent})")
print('staged',stage);assert stage['batch']==1 and stage['disabled'] and '4个云任务' in stage['note']
print('PUBLIC_BROWSER_MANUAL_SEED_BATCH_OK');w.close()
