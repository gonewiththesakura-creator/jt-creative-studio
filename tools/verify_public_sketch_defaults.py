import json,urllib.request,websocket,itertools,time,sys
x=json.load(urllib.request.urlopen('http://127.0.0.1:9225/json/list'));t=next(i for i in x if i['type']=='page')
w=websocket.create_connection(t['webSocketDebuggerUrl'],timeout=30);seq=itertools.count(1)
def ev(e):
 i=next(seq);w.send(json.dumps({'id':i,'method':'Runtime.evaluate','params':{'expression':e,'returnByValue':True}}))
 while 1:
  r=json.loads(w.recv())
  if r.get('id')==i:return r.get('result',{}).get('result',{}).get('value')
for _ in range(60):
 if ev("document.readyState==='complete' && document.getElementById('promptText')?.value.length>100"):break
 time.sleep(1)
style=ev("currentStyle");mode=ev("currentMode");prompt=ev("document.getElementById('promptText').value");summary=ev("[...document.querySelectorAll('.drawer-summary')].map(x=>x.textContent)")
print('style',style,'mode',mode,'summaries',summary);print(prompt[:12000])
expected=['jt_style1_v1','adult reinterpretation of Nezuko Kamado','clearly age 20+','fully covered signature kimono styling','curvy adult woman, elegant hourglass silhouette','shy restrained expression, slightly stronger blush','looking back toward viewer over shoulder','holding a closed book','crouching close to camera, knees forming foreground, balanced dramatic perspective','slight high angle, close portrait, subtle foreshortening','quiet absent-minded pause, introspective sketchbook mood','very pale blush-pink marker wash behind character','mostly monochrome with muted navy-blue accents']
for s in expected:print('HAS',s,s in prompt)
banned=['jt_inkwash_v1','jt_softpaint_v1','jt_style1_v2','pussy','no panty','no cloths','no clothes','bare,nude']
for s in banned:print('BANNED_ABSENT',s,s.lower() not in prompt.lower())
assert style=='sketch' and mode=='character' and all(s in prompt for s in expected) and all(s.lower() not in prompt.lower() for s in banned)
print('PUBLIC_BROWSER_DEFAULT_PROMPT_OK');w.close()
