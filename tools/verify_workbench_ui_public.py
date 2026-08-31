import json,urllib.request,websocket,itertools,time,base64,os
x=json.load(urllib.request.urlopen('http://127.0.0.1:9231/json/list'));t=next(i for i in x if i['type']=='page');w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);exceptions=[]
def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('method')=='Runtime.exceptionThrown':exceptions.append(r)
  if r.get('id')==i:return r
def ev(e):
 r=call('Runtime.evaluate',{'expression':e,'returnByValue':True,'awaitPromise':True});
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')
call('Runtime.enable');call('Page.enable')
for _ in range(90):
 try:
  if ev("document.readyState==='complete'&&typeof generate==='function'&&document.querySelectorAll('.drawer').length===5"):break
 except:pass
 time.sleep(1)
exceptions.clear()
# Desktop public layout + real API-backed overlays.
call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':960,'deviceScaleFactor':1,'mobile':False,'screenWidth':1440,'screenHeight':960});time.sleep(1)
d=ev("({title:document.title,cols:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns,brand:document.querySelector('.brand').innerText,nav:[...document.querySelectorAll('.topnav-link')].map(x=>x.innerText),empty:previewEmpty.innerText,drawers:document.querySelectorAll('.drawer').length,cloud:genCloudBtn.innerText,local:genLocalBtn.innerText})")
print('DESKTOP_PUBLIC',d);assert d['cols'].split()[0].endswith('px') and d['drawers']==5 and 'JT 灵感工作台' in d['brand'] and '视频' in d['nav']
# Overlays must use real public APIs without unhandled errors.
ev("(async()=>{histOpen.click();await new Promise(r=>setTimeout(r,1000));return true})()");assert ev("histOverlay.classList.contains('open')");ev("histOverlay.querySelector('.close').click()")
ev("(async()=>{favOpen.click();await new Promise(r=>setTimeout(r,1000));return true})()");assert ev("favOverlay.classList.contains('open')");ev("favOverlay.querySelector('.close').click()")
# Mobile public layout.
call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':2.75,'mobile':True,'screenWidth':393,'screenHeight':852});time.sleep(1)
m=ev("({bodyWidth:document.body.scrollWidth,viewport:innerWidth,creation:document.querySelector('.creation-pane').getBoundingClientRect().toJSON(),preview:document.querySelector('.preview-pane').getBoundingClientRect().toJSON(),nav:getComputedStyle(document.querySelector('.topnav')).overflowX,buttons:[genCloudBtn.getBoundingClientRect().height,genLocalBtn.getBoundingClientRect().height]})")
print('MOBILE_PUBLIC',m);assert m['bodyWidth']<=m['viewport']+1 and m['creation']['top']<m['preview']['top'] and min(m['buttons'])>=44
for name in ['desktop','mobile']:
 if name=='desktop':call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':960,'deviceScaleFactor':1,'mobile':False,'screenWidth':1440,'screenHeight':960})
 else:call('Emulation.setDeviceMetricsOverride',{'width':393,'height':852,'deviceScaleFactor':2.75,'mobile':True,'screenWidth':393,'screenHeight':852})
 time.sleep(.5);r=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});p=os.path.expandvars(f'$LOCALAPPDATA/Temp/workbench_public_{name}.png');open(p,'wb').write(base64.b64decode(r['result']['data']));print(p)
print('EXCEPTIONS',len(exceptions));assert not exceptions
print('PUBLIC_WORKBENCH_E2E_OK');w.close()
