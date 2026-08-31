import importlib.util,json,time,tempfile,shutil
from pathlib import Path
P=Path(r"D:/LAN-Share/lora/_work/comfy_panel/server.py");spec=importlib.util.spec_from_file_location('direct_local',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
# Isolate smoke output/job records from the real panel data.
root=Path(tempfile.mkdtemp(prefix='dual-local-smoke-'));m.JOBS_DIR=root
job={"id":"localdirect","workflow":"anima02","prompt":"adult woman, solo, simple portrait, white background","negative_prompt":"bad hands, text, watermark","prompt_mode":"manual","width":512,"height":512,"batch":1,"hd":0,"seed":42424242,"seed_mode":"fixed","loras":{"LORA1":"01_style1_step900.safetensors","LORA2":"01_style1_step900.safetensors"},"lora_strengths":{"LORA1":0.7,"LORA2":0.6},"trigger":"jt_style1_v1","translate":False,"status":"running","progress":0,"progress_pct":0,"images":[],"prompt_ids":[],"error":None,"elapsed":None,"created":time.time(),"style_id":"sketch","mode":"original","sequence_mode":"off","generation_backend":"local","selection_snapshot":{}}
t=time.time();m.local_run_image(job,root/'localdirect',m.WORKFLOWS['anima02']);print('elapsed',round(time.time()-t,1),'pid',job['prompt_ids'],'images',job['images'])
from PIL import Image
for x in job['images']:
 p=root/'localdirect'/x['file'];im=Image.open(p);print(p,im.size,p.stat().st_size,im.getextrema());assert im.size==(512,512) and p.stat().st_size>10000
print('DIRECT_LOCAL_COMFY_E2E_OK',root)
