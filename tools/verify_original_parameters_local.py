import base64,itertools,json,pathlib,time,urllib.request,websocket
PORT=9239;BASE='http://127.0.0.1:8772';OUT=pathlib.Path.home()/r'AppData/Local/Temp';OUT.mkdir(parents=True,exist_ok=True)
tab=next(x for x in json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list')) if x['type']=='page');ws=websocket.create_connection(tab['webSocketDebuggerUrl'],timeout=60);seq=itertools.count(1);exceptions=[]
def call(method,params=None):
 i=next(seq);ws.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  r=json.loads(ws.recv())
  if r.get('method')=='Runtime.exceptionThrown':exceptions.append(r)
  if r.get('id')==i:return r
def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True});assert not r.get('result',{}).get('exceptionDetails'),r;return r['result']['result'].get('value')
def view(w,h):call('Emulation.setDeviceMetricsOverride',{'width':w,'height':h,'deviceScaleFactor':1,'mobile':w<=480,'screenWidth':w,'screenHeight':h})
def nav(route):
 ev(f"location.href={json.dumps(BASE+route+'?t='+str(time.time_ns()))}")
 for _ in range(120):
  try:
   if ev("document.readyState==='complete'&&typeof cloudGenerateNow==='function'"):return
  except:pass
  time.sleep(.25)
 raise RuntimeError(route)
def shot(name):
 data=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['result']['data'];p=OUT/name;p.write_bytes(base64.b64decode(data));return str(p)
ids=['cloudW','cloudH','cloudBatch','cloudHd','cloudSeedMode','cloudSeed']
for route,name in [('/original-sketch','sketch'),('/original-graphic','graphic')]:
 view(1200,820);nav(route)
 desktop=ev("""(()=>{const ids=%s;return {heading:[...document.querySelectorAll('h2')].map(x=>x.innerText).find(x=>x==='生成参数')||'',controls:ids.map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect(),s=getComputedStyle(e);return{id,value:e.value,display:s.display,visibility:s.visibility,rect:[r.x,r.y,r.width,r.height],hiddenAncestor:!!e.closest('.original-content')}}),labels:[...document.querySelectorAll('#cloudPanel label')].map(x=>x.childNodes[0]?.textContent?.trim()),panelRect:(()=>{const r=cloudPanel.getBoundingClientRect();return[r.x,r.y,r.width,r.height]})()}})()"""%json.dumps(ids))
 assert desktop['heading']=='生成参数' and all(c['display']!='none' and c['visibility']=='visible' and c['rect'][2]>=100 and c['rect'][3]>=36 and not c['hiddenAncestor'] for c in desktop['controls']),desktop
 assert desktop['labels'][:6]==['宽度','高度','批量','高清','种子模式','种子值'],desktop
 ev("window.__sent=[];window.submitGenerateResilient=async body=>{window.__sent.push(body);return{job_id:'fixture'}};window.pollJobResilient=async()=>({status:'error',error:'fixture stop'});cloudW.value='896';cloudH.value='1152';cloudBatch.value='3';cloudHd.value='2';cloudSeedMode.value='fixed';cloudSeed.value='24681357'")
 ev("cloudGenerateNow('cloud')")
 payload=ev("window.__sent[0]")
 assert {k:payload[k] for k in ['width','height','batch','hd','seed','seed_mode']}=={'width':896,'height':1152,'batch':3,'hd':2,'seed':24681357,'seed_mode':'fixed'},payload
 desk=shot(f'original_{name}_params_desktop.png')
 view(393,852);ev('window.scrollTo(0,document.documentElement.scrollHeight)');time.sleep(.3)
 mobile=ev("""(()=>{const ids=%s,footer=document.querySelector('.creation-footer').getBoundingClientRect();return{overflow:document.documentElement.scrollWidth-innerWidth,footerTop:footer.top,footerBottom:footer.bottom,viewport:innerHeight,controls:ids.map(id=>{const r=document.getElementById(id).getBoundingClientRect();return{id,top:r.top,bottom:r.bottom,width:r.width,height:r.height,aboveDock:r.bottom<=footer.top+1}}),scrollY,scrollHeight:document.documentElement.scrollHeight}})()"""%json.dumps(ids))
 assert mobile['overflow']<=1 and all(c['width']>=100 and c['height']>=36 and c['aboveDock'] for c in mobile['controls']),mobile
 mob=shot(f'original_{name}_params_mobile.png')
 print(name,{'desktop':desktop,'payload':{k:payload[k] for k in ['width','height','batch','hd','seed','seed_mode']},'mobile':mobile,'screens':[desk,mob]})
assert not exceptions,exceptions
print('ORIGINAL_PARAMETERS_BROWSER_E2E_OK')
