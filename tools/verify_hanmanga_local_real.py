import hashlib,importlib.util,json,pathlib,time,urllib.parse,urllib.request
from PIL import Image,ImageStat
ROOT=pathlib.Path(r'D:/LAN-Share/lora/_work/comfy_panel')
spec=importlib.util.spec_from_file_location('liulilocal',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
profile=json.loads((ROOT/'sources/hanmanga_profile.source.json').read_text(encoding='utf8'));preset=m.STYLE_PRESETS['hanmanga'];seed=24681358
parts=[profile['prefix'],profile['head']]
for key,label in profile['defaultSelections'].items():
 rows=profile['pools'][key];hit=next((row for row in rows if row[0]==label),None)
 if hit and hit[1]:parts.append(hit[1])
parts.append(profile['style']);prompt=',\n\n'.join(parts);negative=profile['negative']
api=m.build_api('anima02',prompt,512,768,1,0,seed,loras={k:m.local_lora_name(preset[k]) for k in ('LORA1','LORA2')},trigger=preset['trigger'],translate=False,negative_prompt=negative,prefix='comfy_panel/liuli_real_smoke')
assert api['70']['inputs']['lora_name']=='Anima_JT\\08_liuli_style_v1_step600.safetensors'
assert api['71']['inputs']['lora_name']=='Anima_JT\\08_liuli_style_v1_step600.safetensors'
assert api['4']['inputs']['text'].lower().count('jt_liulistyle_v1')==1
req=urllib.request.Request('http://127.0.0.1:8188/prompt',data=json.dumps({'prompt':api}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=60) as response:submitted=json.load(response)
assert not submitted.get('node_errors'),submitted;pid=submitted['prompt_id'];print('SUBMITTED',pid)
started=time.time();entry=None;last=None
while time.time()-started<900:
 with urllib.request.urlopen('http://127.0.0.1:8188/history/'+pid,timeout=30) as response:history=json.load(response)
 if pid in history:
  entry=history[pid];status=entry.get('status',{});state=(status.get('status_str'),status.get('completed'))
  if state!=last:print('STATUS',state);last=state
  if status.get('completed') or status.get('status_str')=='success':break
  if status.get('status_str')=='error':raise RuntimeError(json.dumps(status,ensure_ascii=False))
 time.sleep(2)
assert entry and (entry.get('status',{}).get('completed') or entry.get('status',{}).get('status_str')=='success')
images=[]
for output in entry.get('outputs',{}).values():images+=output.get('images',[])
assert images;im=images[0];query=urllib.parse.urlencode({'filename':im['filename'],'subfolder':im.get('subfolder',''),'type':im.get('type','output')})
with urllib.request.urlopen('http://127.0.0.1:8188/view?'+query,timeout=180) as response:data=response.read()
out=pathlib.Path.home()/r'AppData/Local/Temp/liuli_step600_local_smoke.png';out.write_bytes(data)
with Image.open(out) as image:
 image.load();stats=ImageStat.Stat(image.convert('RGB'));meta={'format':image.format,'size':image.size,'bytes':len(data),'stddev':[round(x,2) for x in stats.stddev],'sha256':hashlib.sha256(data).hexdigest(),'prompt_id':pid,'elapsed':round(time.time()-started,1)}
assert meta['format']=='PNG' and tuple(meta['size'])==(512,768) and max(meta['stddev'])>20 and len(data)>50000,meta
print('RESULT',json.dumps(meta,ensure_ascii=False));print('LOCAL_HANMANGA_REAL_OK',out)
