import json,urllib.request,websocket,itertools,time,base64,os
x=json.load(urllib.request.urlopen('http://127.0.0.1:9230/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);console=[]
def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('method') in ('Runtime.consoleAPICalled','Runtime.exceptionThrown'):console.append(r)
  if r.get('id')==i:return r
def ev(e):
 r=call('Runtime.evaluate',{'expression':e,'returnByValue':True,'awaitPromise':True});
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
call('Runtime.enable');call('Page.enable')
# Reload the current generated artifact so no interaction state from a prior
# E2E run leaks into the initial-state assertions.
ev("location.href='http://127.0.0.1:8765/promptgen.html?e2e='+Date.now()")
for _ in range(60):
 try:
  if ev("document.readyState==='complete'&&typeof render==='function'&&document.querySelectorAll('.drawer').length===5"):break
 except:pass
 time.sleep(1)
# Ignore navigation/context-destruction events from loading the fresh page;
# only interaction-stage exceptions below count as product regressions.
console.clear()
# desktop
call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':960,'deviceScaleFactor':1,'mobile':False,'screenWidth':1440,'screenHeight':960})
time.sleep(1)
desktop=ev("({shell:!!document.querySelector('.app-shell'),cols:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns,topbar:document.querySelector('.topbar').getBoundingClientRect().height,left:document.querySelector('.creation-pane').getBoundingClientRect().toJSON(),right:document.querySelector('.preview-pane').getBoundingClientRect().toJSON(),empty:document.querySelector('#previewEmpty').innerText,tabs:[...document.querySelectorAll('[data-result-tab]')].map(x=>({t:x.innerText,a:x.classList.contains('active')})),drawers:document.querySelectorAll('.drawer').length,open:document.querySelectorAll('.drawer.open').length})")
print('DESKTOP',desktop);assert desktop['shell'] and desktop['left']['right']<desktop['right']['right'] and desktop['right']['width']>desktop['left']['width'] and desktop['open']==0
png=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});dp=os.path.expandvars(r'$LOCALAPPDATA/Temp/workbench_desktop.png');open(dp,'wb').write(base64.b64decode(png['result']['data']))
# interactions: drawer direct, prompt mode, tabs, overlays
inter=ev("(()=>{let d=[...document.querySelectorAll('.drawer')].find(x=>x.querySelector('.drawer-head').innerText.includes('身体'));d.querySelector('.drawer-head').click();d=[...document.querySelectorAll('.drawer')].find(x=>x.querySelector('.drawer-head').innerText.includes('身体'));const direct=d.classList.contains('open')&&d.querySelectorAll('.picker').length===d.querySelectorAll('.item').length&&d.querySelectorAll('.expand,.value').length===0;document.querySelector('input[value=manual]').click();const manual=manualPromptPanel.style.display==='block';document.querySelector('[data-result-tab=local]').click();const local=document.querySelector('[data-result-panel=local]').classList.contains('active');favOpen.click();const fav=favOverlay.classList.contains('open');favOverlay.querySelector('.close').click();return{direct,manual,local,fav}})()")
print('INTERACTIONS',inter);assert all(inter.values())
# mobile
call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':2.75,'mobile':True,'screenWidth':393,'screenHeight':852});time.sleep(1)
mobile=ev("({cols:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns,navOverflow:getComputedStyle(document.querySelector('.topnav')).overflowX,creation:document.querySelector('.creation-pane').getBoundingClientRect().toJSON(),preview:document.querySelector('.preview-pane').getBoundingClientRect().toJSON(),bodyWidth:document.body.scrollWidth,viewport:innerWidth,buttons:[genCloudBtn.getBoundingClientRect().height,genLocalBtn.getBoundingClientRect().height]})")
print('MOBILE',mobile);assert mobile['creation']['top']<mobile['preview']['top'] and mobile['bodyWidth']<=mobile['viewport']+1 and min(mobile['buttons'])>=44
png=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});mp=os.path.expandvars(r'$LOCALAPPDATA/Temp/workbench_mobile.png');open(mp,'wb').write(base64.b64decode(png['result']['data']))
# Filter harmless failed API fetches only if user opens overlays on static server; JS exceptions are not harmless.
exceptions=[x for x in console if x.get('method')=='Runtime.exceptionThrown'];print('EXCEPTIONS',len(exceptions));assert not exceptions
print('WORKBENCH_BROWSER_E2E_OK',dp,mp);w.close()
