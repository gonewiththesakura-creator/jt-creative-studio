from __future__ import annotations
import json,time
from pathlib import Path
from PIL import Image
import torch
from transformers import AutoProcessor,AutoModelForImageTextToText
MODEL=Path(r'D:/ComfyUI_Mie/ComfyUI/models/prompt_generator/Qwen3-VL-4B-Instruct')
OUT=Path(r'D:/LAN-Share/lora/_work/comfy_panel/audit/private_realism_workflows/local_vlm_results.json')
CASES=[
 ('source',Path(r'D:/LAN-Share/lora/_work/prepared/style3_style/holdout/3_102.png')),
 ('krea2',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_krea2_result.png')),
 ('2511',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_2511.png')),
 ('multisample',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_multisample.png')),
 ('qwen_zi',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_qwen_zi.png')),
 ('4k_text',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_4k_text.png')),
 ('3in1',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_3in1.png')),
 ('zi_flowmatch',Path(r'C:/Users/JT/AppData/Local/Temp/private_realism_results/realism_zi_flowmatch_extracted/image_00009.png')),
]
PROMPT='''你是严格的AI图像交付质检员。仅按可见像素判断。请用中文JSON回答，字段为：valid_complete(boolean)、photorealism(0-5)、composition_coherent(boolean)、face_severe_defect(boolean)、hands_severe_defect(boolean)、visible_text_or_watermark(boolean)、text_location(string)、quality_notes(string)。务必检查右侧、四角、背景、衣物和物体上的任何英文/中文/Logo/水印；模糊但像文字也设visible_text_or_watermark=true。若人物手被遮挡但未明显畸形，不算严重。不要推断身份或年龄。'''
print('loading',flush=True);t=time.time();model=AutoModelForImageTextToText.from_pretrained(str(MODEL),torch_dtype=torch.float16,device_map='cuda',attn_implementation='eager',low_cpu_mem_usage=True);processor=AutoProcessor.from_pretrained(str(MODEL));print('loaded',round(time.time()-t,1),flush=True)
results={}
for key,path in CASES:
 im=Image.open(path).convert('RGB');im.thumbnail((1536,1536),Image.Resampling.LANCZOS)
 msg=[{'role':'user','content':[{'type':'image'},{'type':'text','text':PROMPT}]}];text=processor.apply_chat_template(msg,tokenize=False,add_generation_prompt=True);inputs=processor(text=[text],images=[im],return_tensors='pt').to('cuda');started=time.time()
 with torch.no_grad():out=model.generate(**inputs,max_new_tokens=500,do_sample=False)
 answer=processor.batch_decode(out[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)[0].strip();results[key]={'file':str(path),'seconds':round(time.time()-started,2),'answer':answer};OUT.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print('DONE',key,answer[:240].replace('\n',' '),flush=True)
print('COMPLETE',OUT,flush=True)
