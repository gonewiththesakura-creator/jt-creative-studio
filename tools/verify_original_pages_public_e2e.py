import json,urllib.request,urllib.parse,websocket,itertools,time
PORT=9227
x=json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'));t=next(i for i in x if i['type']=='page')
w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=40);seq=itertools.count(1)
def ev(e):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True,'awaitPromise':True}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:
   if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
   return r.get('result',{}).get('result',{}).get('value')
def wait():
 for _ in range(90):
  try:
   if ev("document.readyState==='complete' && typeof cloudGenerateNow==='function' && !!document.getElementById('grid') && document.querySelectorAll('#grid .item').length>0"):return
  except Exception:pass
  time.sleep(1)
 raise RuntimeError('page not ready')
def inspect_and_capture(expected_style,expected_trigger,expected_items,has_sequence):
 wait();before=ev("({style:CLOUD_STYLE_ID,trigger:CLOUD_TRIGGER,items:document.querySelectorAll('#grid .item').length,mode:currentMode,prompt:buildPositive(),seed:+cloudSeed.value,batchNote:cloudBatchNote.textContent,sequence:CLOUD_HAS_SEQUENCE})")
 print('BEFORE',json.dumps(before,ensure_ascii=False)[:3000]);assert before['style']==expected_style and before['trigger']==expected_trigger and before['items']==expected_items and before['sequence']==has_sequence
 # Real original controls: one-item change works; normal randomization keeps
 # locks. The source page's explicit "重抽全部" intentionally ignores locks.
 behavior=ev("(()=>{const key=Object.keys(POOLS)[0];const old=state[key][1];state[key]=POOLS[key][(POOLS[key].findIndex(x=>x[1]===old)+1)%POOLS[key].length];const changed=state[key][1]!==old;locked[key]=true;const fixed=state[key][1];randomize(false);const lockPreserved=state[key][1]===fixed;currentMode='character';render();return {changed,lockPreserved,mode:currentMode,visible:document.querySelectorAll('#grid .item').length}})()")
 print('BEHAVIOR',behavior);assert behavior['changed'] and behavior['lockPreserved'] and behavior['mode']=='character'
 # Capture actual request without provider credit.
 cap=ev(f"(async()=>{{cloudSeedMode.value='fixed';cloudSeed.value='246813579';cloudBatch.value='3';cloudHd.value='1';if(CLOUD_HAS_SEQUENCE)cloudSequence.value='off';cloudUpdateBatch();const expected=cloudStripStyleTokens(buildPositive());const old=window.fetch;let captured=null;window.fetch=async(u,o)=>{{if(String(u).includes('/api/generate')){{captured=JSON.parse(o.body);return new Response(JSON.stringify({{job_id:'capture'}}),{{status:200,headers:{{'Content-Type':'application/json'}}}})}}if(String(u).includes('/api/job/capture'))return new Response(JSON.stringify({{status:'done',elapsed:0,seed:246813579,prompt_mode:'options',width:768,height:1024,batch:3,images:[]}}),{{status:200,headers:{{'Content-Type':'application/json'}}}});return old(u,o)}};try{{await cloudGenerateNow()}}finally{{window.fetch=old}}return {{captured,expected}}}})()")
 print('CAPTURE',json.dumps(cap,ensure_ascii=False)[:5000]);b=cap['captured'];assert b['prompt']==cap['expected'] and expected_trigger not in b['prompt'] and b['negative_prompt']==ev('NEGATIVE') and b['style_id']==expected_style and b['seed']==246813579 and b['batch']==3 and b['hd']==1 and b['selection_snapshot']['source_page']=='original_'+expected_style and b['sequence_mode']=='off'
 if has_sequence:
  st=ev("cloudSequence.value='4';cloudBatch.value='4';cloudUpdateBatch();({batch:+cloudBatch.value,disabled:cloudBatch.disabled,note:cloudBatchNote.textContent})");print('STAGED',st);assert st['batch']==1 and st['disabled'] and '4个云任务' in st['note']
 return True
inspect_and_capture('sketch','jt_style1_v1',16,True)
# Navigate same tab to graphic.
ev("location.href='http://8.210.125.65:8189/original-graphic?rev=e2e-v1'")
wait();inspect_and_capture('graphic','jt_style2_v1',11,False)
print('ORIGINAL_PAGES_PUBLIC_BROWSER_E2E_OK');w.close()
