import json,urllib.request,websocket,itertools,time,base64,os
x=json.load(urllib.request.urlopen('http://127.0.0.1:9232/json/list'))
t=next(i for i in x if i['type']=='page')
w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=60)
seq=itertools.count(1);exceptions=[]

def call(method,params=None):
 i=next(seq);w.send(json.dumps({'id':i,'method':method,'params':params or {}}))
 while True:
  r=json.loads(w.recv())
  if r.get('method')=='Runtime.exceptionThrown':exceptions.append(r)
  if r.get('id')==i:return r

def ev(expr):
 r=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
 if r.get('result',{}).get('exceptionDetails'):raise RuntimeError(r)
 return r.get('result',{}).get('result',{}).get('value')

def viewport(width,height):
 call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<=480,'screenWidth':width,'screenHeight':height})

def go(page,ready,width=1200,height=820):
 viewport(width,height)
 ev(f"location.href='http://127.0.0.1:8766/{page}?e2e='+Date.now()")
 for _ in range(90):
  try:
   if ev("document.readyState==='complete'&&"+ready):break
  except Exception:pass
  time.sleep(.35)
 else:raise RuntimeError('not ready '+page)
 exceptions.clear();time.sleep(.2)

def shot(name):
 r=call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
 p=os.path.expandvars(f'$LOCALAPPDATA/Temp/polish_{name}.png')
 open(p,'wb').write(base64.b64decode(r['result']['data']))
 return p

def layout_check(page,ready,width,height,name):
 go(page,ready,width,height)
 d=ev("(()=>{const nav=document.querySelector('.topnav-link.active'),buttons=[...document.querySelectorAll('.creation-footer button')],scroll=document.querySelector('.creation-scroll'),footer=document.querySelector('.creation-footer');if(scroll&&scroll.scrollHeight>scroll.clientHeight)scroll.scrollTop=scroll.scrollHeight;const candidates=[...scroll.children].filter(x=>getComputedStyle(x).display!=='none'),last=candidates.at(-1),lr=last?.getBoundingClientRect(),fr=footer?.getBoundingClientRect();return{doc:document.documentElement.scrollWidth,view:document.documentElement.clientWidth,shell:!!document.querySelector('.app-shell'),preview:!!document.querySelector('.preview-pane'),active:nav?.innerText||'',buttonHeights:buttons.map(x=>Math.round(x.getBoundingClientRect().height)),grid:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns,lastBottom:lr?.bottom||0,footerTop:fr?.top||9999,contentClearsFooter:!lr||!fr||lr.bottom<=fr.top+1}})()")
 print('LAYOUT',name,d);assert d['shell'] and d['preview'] and d['doc']<=d['view']+1 and all(h>=44 for h in d['buttonHeights']) and d['contentClearsFooter']
 ev("document.querySelector('.creation-scroll').scrollTop=0;window.scrollTo(0,0)");time.sleep(.1)
 return shot(name)

# Main: exact options -> manual import.
go('promptgen.html',"typeof importGeneratedPromptToManual==='function'")
imp=ev("(()=>{const expected=buildCorePrompt();importGeneratedPrompt.click();manualPositive.value+=', user edit';return{manual:promptMode.value==='manual',positive:manualPositive.value===expected+', user edit',negative:manualNegative.value===cfg().negative,visible:manualPromptPanel.style.display==='block'}})()")
print('IMPORT',imp);assert all(imp.values())

# Different idle colors, slow fill state, and reset.
liq=ev("(()=>{const idle={cloudBg:getComputedStyle(genCloudBtn).backgroundColor,localBg:getComputedStyle(genLocalBtn).backgroundColor,cloudLevel:getComputedStyle(genCloudBtn).getPropertyValue('--liquid-level').trim(),localLevel:getComputedStyle(genLocalBtn).getPropertyValue('--liquid-level').trim()};setLiquidLoading(genCloudBtn,true);setLiquidLoading(genLocalBtn,true);const loading={cloud:genCloudBtn.classList.contains('is-loading'),local:genLocalBtn.classList.contains('is-loading'),cloudColor:getComputedStyle(genCloudBtn).getPropertyValue('--liquid-color').trim(),localColor:getComputedStyle(genLocalBtn).getPropertyValue('--liquid-color').trim(),cloudLevel:getComputedStyle(genCloudBtn).getPropertyValue('--liquid-level').trim(),localLevel:getComputedStyle(genLocalBtn).getPropertyValue('--liquid-level').trim(),cloudBusy:genCloudBtn.getAttribute('aria-busy'),localBusy:genLocalBtn.getAttribute('aria-busy')};setLiquidLoading(genCloudBtn,false);setLiquidLoading(genLocalBtn,false);const reset={cloud:genCloudBtn.classList.contains('is-loading'),local:genLocalBtn.classList.contains('is-loading'),cloudBusy:genCloudBtn.getAttribute('aria-busy'),localBusy:genLocalBtn.getAttribute('aria-busy')};return{idle,loading,reset}})()")
print('LIQUID',liq);assert liq['idle']['cloudBg']=='rgb(255, 255, 255)' and liq['idle']['localBg']=='rgb(255, 255, 255)';assert liq['loading']['cloud'] and liq['loading']['local'] and liq['loading']['cloudColor']!=liq['loading']['localColor'] and liq['loading']['cloudLevel']=='5%' and liq['loading']['localLevel']=='5%' and liq['loading']['cloudBusy']=='true' and liq['loading']['localBusy']=='true';assert not liq['reset']['cloud'] and not liq['reset']['local'] and liq['reset']['cloudBusy']=='false' and liq['reset']['localBusy']=='false'

# Synthetic cards isolate the exact library scroll geometry.
lib=ev("(()=>{favOverlay.classList.add('open');favList.innerHTML=Array.from({length:8},(_,i)=>`<div class='job'><img style='height:220px;width:100%;object-fit:cover' src='data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"300\" height=\"220\"><rect width=\"300\" height=\"220\" fill=\"%23dde2ee\"/></svg>'></div>`).join('');const panel=favOverlay.querySelector('.library-panel'),head=favOverlay.querySelector('.library-header'),scroll=favOverlay.querySelector('.library-scroll');const before=head.getBoundingClientRect().toJSON();scroll.scrollTop=600;const after=head.getBoundingClientRect().toJSON(),sr=scroll.getBoundingClientRect().toJSON(),hit=document.elementFromPoint(after.left+30,after.top+30);return{panelOverflow:getComputedStyle(panel).overflow,scrollOverflow:getComputedStyle(scroll).overflowY,headTopBefore:before.top,headTopAfter:after.top,headBottom:after.bottom,scrollTopEdge:sr.top,headerOwnsHit:head.contains(hit),scrollTop:scroll.scrollTop}})()")
print('LIBRARY_GEOMETRY',lib);assert lib['panelOverflow']=='hidden' and lib['scrollOverflow']=='auto' and abs(lib['headTopBefore']-lib['headTopAfter'])<1 and abs(lib['scrollTopEdge']-lib['headBottom'])<1 and lib['headerOwnsHit']
# Close with the real button, then reopen through the real button: scroll must reset.
reset=ev("(async()=>{const scroll=favOverlay.querySelector('.library-scroll');favOverlay.querySelector('.close').click();const closed=!favOverlay.classList.contains('open');scroll.scrollTop=500;document.getElementById('favOpen').click();await new Promise(r=>setTimeout(r,30));const top=scroll.scrollTop;favOverlay.querySelector('.close').click();return{closed,top,closedAgain:!favOverlay.classList.contains('open')}})()")
print('LIBRARY_RESET',reset);assert reset=={'closed':True,'top':0,'closedAgain':True}

# Formal screenshots have no synthetic overlay content.
main_desktop=layout_check('promptgen.html',"typeof importGeneratedPromptToManual==='function'",1200,820,'main_desktop')
main_mobile=layout_check('promptgen.html',"typeof importGeneratedPromptToManual==='function'",393,852,'main_mobile')

pages=[('original_sketch.html','原始铅绘'),('original_graphic.html','原始古风')]
shots=[main_desktop,main_mobile]
for page,active in pages:
 go(page,"typeof importGeneratedPromptToManual==='function'")
 d=ev("({shell:!!document.querySelector('.app-shell'),preview:!!document.querySelector('.preview-pane'),nav:[...document.querySelectorAll('.topnav-link')].map(x=>({t:x.innerText,a:x.classList.contains('active')})),buttons:[cloudGenerateCloud.innerText,cloudGenerateLocal.innerText]})")
 print(page,d);assert d['shell'] and d['preview'] and any(x['t']==active and x['a'] for x in d['nav'])
 assert ev("(()=>{const p=cloudStripStyleTokens(buildPositive());importGeneratedPrompt.click();manualPositive.value+=', user edit';return cloudPromptMode.value==='manual'&&manualPositive.value===p+', user edit'&&manualNegative.value===NEGATIVE})()")
 base=page.replace('.html','')
 shots.append(layout_check(page,"typeof importGeneratedPromptToManual==='function'",1200,820,base+'_desktop'))
 shots.append(layout_check(page,"typeof importGeneratedPromptToManual==='function'",393,852,base+'_mobile'))

# Video shell, original business functions, current overlay close target.
go('video.html',"typeof generate==='function'")
v=ev("({shell:!!document.querySelector('.app-shell'),preview:!!document.querySelector('.preview-pane'),active:[...document.querySelectorAll('.topnav-link.active')].map(x=>x.innerText),functions:[typeof init,typeof uploadMedia,typeof generate],button:genBtn.innerText})")
print('VIDEO',v);assert v['shell'] and v['preview'] and v['active']==['视频'] and all(x=='function' for x in v['functions'])
video_overlay=ev("(()=>{favOverlay.classList.add('open');const s=favOverlay.querySelector('.library-scroll');s.scrollTop=100;favOverlay.querySelector('.close').click();const closed=!favOverlay.classList.contains('open');s.scrollTop=100;document.getElementById('favOpen').click();const top=s.scrollTop;favOverlay.querySelector('.close').click();return{closed,top}})()")
print('VIDEO_OVERLAY',video_overlay);assert video_overlay=={'closed':True,'top':0}
shots.append(layout_check('video.html',"typeof generate==='function'",1200,820,'video_desktop'))
shots.append(layout_check('video.html',"typeof generate==='function'",393,852,'video_mobile'))

print('EXCEPTIONS',len(exceptions));assert not exceptions
print('POLISH_BROWSER_E2E_OK',json.dumps(shots,ensure_ascii=False));w.close()
