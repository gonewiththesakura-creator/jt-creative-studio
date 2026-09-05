"""Exact panel style_only local ComfyUI smoke (one image)."""
from __future__ import annotations
import importlib.util,json,time,urllib.request
from pathlib import Path
ROOT=Path(r'D:/LAN-Share/lora/_work/comfy_panel')
spec=importlib.util.spec_from_file_location('panel_server',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
preset=m.resolve_style_preset('cold','style_only')
api=m.build_api('anima02','adult man age 35, short black hair, brown eyes, charcoal long coat, rainy city street, full body',768,1024,1,0,424242,{'LORA1':m.local_lora_name(preset['LORA1']),'LORA2':m.local_lora_name(preset['LORA2'])},preset['trigger'],False,'child, teenager, text, watermark, signature, malformed anatomy, blurry','cold_style_panel_smoke/style_only',lora_strengths=preset['strengths'])
assert api['70']['inputs']['strength_model']==0.6 and api['71']['inputs']['strength_model']==0.0
assert api['70']['inputs']['lora_name']==api['71']['inputs']['lora_name']=='Anima_JT\\05_style3_v2_step1600.safetensors'
def req(path,payload=None,timeout=90):
 data=None if payload is None else json.dumps(payload).encode();r=urllib.request.Request('http://127.0.0.1:8188'+path,data=data,headers={'Content-Type':'application/json'} if data else {})
 with urllib.request.urlopen(r,timeout=timeout) as x:return json.load(x)
q=req('/queue');assert not q.get('queue_running') and not q.get('queue_pending'),q
r=req('/prompt',{'prompt':api});pid=r['prompt_id'];print('SUBMITTED',pid,flush=True)
end=time.time()+900
while time.time()<end:
 time.sleep(3);h=req('/history/'+pid,timeout=30)
 if pid not in h:continue
 e=h[pid];status=(e.get('status') or {}).get('status_str')
 if status=='error':raise RuntimeError(json.dumps(e.get('status'),ensure_ascii=False)[:2000])
 if status=='success':
  images=[im for out in (e.get('outputs') or {}).values() for im in out.get('images',[])]
  assert len(images)==1,images;im=images[0];path=Path(r'D:/ComfyUI_Mie/ComfyUI/output')/im.get('subfolder','')/im['filename'];assert path.exists(),path
  result={'prompt_id':pid,'status':'success','output':str(path),'bytes':path.stat().st_size,'node70':api['70']['inputs'],'node71':api['71']['inputs']}
  (ROOT/'audit/cold_style_ab/panel_style_only_smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True);break
else:raise TimeoutError('smoke timeout')
