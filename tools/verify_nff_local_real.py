import importlib.util,json,pathlib,time,urllib.request,hashlib
from PIL import Image,ImageStat
ROOT=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel');spec=importlib.util.spec_from_file_location('nffsmoke',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=m.STYLE_PRESETS['nff'];seed=24681357
prompt='adult woman, solo, elegant half-body portrait, long dark hair, refined expressive eyes, black fitted evening dress, one hand near hair, tasteful cinematic interior, soft window light, coherent detailed hands'
negative='worst quality, low quality, blurry, child, underage, bad anatomy, bad hands, extra fingers, missing fingers, text, watermark, logo, signature'
api=m.build_api('anima02',prompt,512,768,1,0,seed,loras={k:m.local_lora_name(p[k]) for k in ('LORA1','LORA2')},trigger=p['trigger'],translate=False,negative_prompt=negative,prefix='comfy_panel/nff_real_smoke')
req=urllib.request.Request('http://127.0.0.1:8188/prompt',data=json.dumps({'prompt':api}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=60) as r:resp=json.load(r)
assert not resp.get('node_errors'),resp;pid=resp['prompt_id'];print('SUBMITTED',pid)
start=time.time();seen=[];entry=None
while time.time()-start<900:
 with urllib.request.urlopen('http://127.0.0.1:8188/history/'+pid,timeout=30) as r:h=json.load(r)
 if pid in h:
  entry=h[pid];st=entry.get('status',{});sig=(st.get('status_str'),st.get('completed'))
  if not seen or sig!=seen[-1]:seen.append(sig);print('STATUS',sig)
  if st.get('completed') or st.get('status_str')=='success':break
  if st.get('status_str')=='error':raise RuntimeError(json.dumps(st,ensure_ascii=False))
 time.sleep(2)
assert entry and (entry.get('status',{}).get('completed') or entry.get('status',{}).get('status_str')=='success')
ims=[]
for out in entry.get('outputs',{}).values():ims += out.get('images',[])
assert ims,entry.keys();im=ims[0];q=urllib.parse.urlencode({'filename':im['filename'],'subfolder':im.get('subfolder',''),'type':im.get('type','output')})
with urllib.request.urlopen('http://127.0.0.1:8188/view?'+q,timeout=180) as r:data=r.read()
out=pathlib.Path.home()/'AppData/Local/Temp/nff_step2000_local_smoke.png';out.write_bytes(data)
with Image.open(out) as img:
 img.load();stats=ImageStat.Stat(img.convert('RGB'));info={'format':img.format,'size':img.size,'bytes':len(data),'stddev':[round(x,2) for x in stats.stddev],'sha256':hashlib.sha256(data).hexdigest()}
print('RESULT',json.dumps(info));assert info['format']=='PNG' and info['size']==(512,768) and max(info['stddev'])>20 and len(data)>50000
print('LOCAL_NFF_REAL_SMOKE_OK',out,'elapsed',round(time.time()-start,1))
