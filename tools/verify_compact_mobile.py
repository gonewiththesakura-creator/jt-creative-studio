import json,urllib.request,websocket,itertools,time
x=json.load(urllib.request.urlopen('http://127.0.0.1:9228/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1)
def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:return r
def ev(e):
 r=call('Runtime.evaluate',{'expression':e,'returnByValue':True,'awaitPromise':True});
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':2.75,'mobile':True,'screenWidth':393,'screenHeight':852})
ev("location.href='http://8.210.125.65:8189/promptgen?compact=mobile-e2e-v1'")
for _ in range(90):
 try:
  if ev("document.readyState==='complete'&&typeof render==='function'&&document.querySelectorAll('.drawer').length===5"):break
 except:pass
 time.sleep(1)
# Initial state: five closed category drawers, no inner selectors visible.
initial=ev("({title:document.querySelector('h1').innerText,drawers:document.querySelectorAll('.drawer').length,open:document.querySelectorAll('.drawer.open').length,visiblePickers:[...document.querySelectorAll('.picker')].filter(x=>x.getBoundingClientRect().height>0).length,smallTexts:[...document.querySelectorAll('.note,.picker-note,.drawer-summary')].filter(x=>x.getBoundingClientRect().height>0).map(x=>x.innerText),floating:[...document.querySelectorAll('.floating')].map(x=>({text:x.innerText,pos:getComputedStyle(x).position}))})")
print('INITIAL',initial);assert initial['title']=='三画风生图' and initial['drawers']==5 and initial['open']==0 and initial['visiblePickers']==0 and initial['smallTexts']==[] and all(x['pos']=='static' for x in initial['floating'])
# Click 身体 once: direct selectors must be visible, with no selected-value
# summary and no second expand arrow/button.
body=ev("(()=>{let d=[...document.querySelectorAll('.drawer')].find(x=>x.querySelector('.drawer-head span').innerText==='身体');d.querySelector('.drawer-head').click();d=[...document.querySelectorAll('.drawer')].find(x=>x.querySelector('.drawer-head span').innerText==='身体');const cards=[...d.querySelectorAll('.item')];return{open:d.classList.contains('open'),cards:cards.length,visiblePickers:cards.filter(x=>x.querySelector('.picker').getBoundingClientRect().height>0).length,values:d.querySelectorAll('.value').length,expandButtons:d.querySelectorAll('.expand').length,labels:cards.map(x=>x.querySelector('.item-name').innerText),selected:cards.map(x=>[...x.querySelector('.picker').selectedOptions].map(o=>o.text))}})()")
print('BODY',body);assert body['open'] and body['cards']>0 and body['visiblePickers']==body['cards'] and body['values']==0 and body['expandButtons']==0
# Change the first body selector directly and make sure prompt updates without
# another click level.
change=ev("(()=>{const d=[...document.querySelectorAll('.drawer')].find(x=>x.querySelector('.drawer-head span').innerText==='身体');const s=d.querySelector('.picker');const before=promptText.value;s.selectedIndex=Math.min(1,s.options.length-1);s.dispatchEvent(new Event('change',{bubbles:true}));return{changed:promptText.value!==before,selected:s.options[s.selectedIndex].text}})()")
print('CHANGE',change);assert change['changed']
# Capture screenshot for durable mobile-layout evidence.
res=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});import base64,os
out=os.path.expandvars(r'$LOCALAPPDATA/Temp/compact_mobile.png');open(out,'wb').write(base64.b64decode(res['result']['data']));print('SCREENSHOT',out)
print('PUBLIC_MOBILE_TWO_STEP_DRAWER_OK');w.close()
