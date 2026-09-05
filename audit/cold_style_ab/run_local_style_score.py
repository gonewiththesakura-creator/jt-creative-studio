"""Blind multi-image style scoring for A/B/C at fixed seeds."""
from __future__ import annotations
import json,time
from pathlib import Path
from PIL import Image
import torch
from transformers import AutoProcessor,AutoModelForImageTextToText
MODEL=Path(r'D:/ComfyUI_Mie/ComfyUI/models/prompt_generator/Qwen3-VL-4B-Instruct')
ROOT=Path(r'D:/LAN-Share/lora/_work/comfy_panel/audit/cold_style_ab')
manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
items={(x['scene'],x['blind_label'],x['seed']):Path(x['absolute_path']) for x in manifest['items']}
reference=Image.open(ROOT/'contact_sheets'/'training_holdout_reference.png').convert('RGB');reference.thumbnail((1000,1000),Image.Resampling.LANCZOS)
print('loading',flush=True);t=time.time();model=AutoModelForImageTextToText.from_pretrained(str(MODEL),torch_dtype=torch.float16,device_map='cuda',attn_implementation='eager',low_cpu_mem_usage=True);processor=AutoProcessor.from_pretrained(str(MODEL));print('loaded',round(time.time()-t,1),flush=True)
results={}
for seed in manifest['seeds']:
 images=[reference]
 content=[{'type':'text','text':'图1是六张目标训练包风格参考。'} ,{'type':'image'}]
 for index,label in enumerate(['A','B','C'],start=2):
  im=Image.open(items[('different_adult_woman',label,seed)]).convert('RGB');im.thumbnail((768,1024),Image.Resampling.LANCZOS);images.append(im)
  content.extend([{'type':'text','text':f'图{index}是候选{label}。'},{'type':'image'}])
 content.append({'type':'text','text':'''你是严格的扩散LoRA盲评员，不知道A/B/C模型映射。只评价风格，不评价或奖励身份。逐一给A/B/C以下0-10分：细线稿与边缘、低饱和冷色、平涂和柔和阴影、冷淡漫画气质、人物背景统一度、手脸技术质量。银白发、蓝眼、蓝花、痣、脸型等身份特征不得作为风格加分；提示词服从偏差和手脸错误应扣分。最后给总分、排序，并说明领先是否稳定到足以选择；如差异小于1分写“无稳定优势”。简洁中文。'''})
 messages=[{'role':'user','content':content}];text=processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True);inputs=processor(text=[text],images=images,return_tensors='pt').to('cuda');started=time.time()
 with torch.no_grad():out=model.generate(**inputs,max_new_tokens=1000,do_sample=False)
 answer=processor.batch_decode(out[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)[0].strip();results[str(seed)]={'seconds':round(time.time()-started,2),'answer':answer};(ROOT/'local_vlm_style_scores.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print('DONE',seed,answer[:240].replace('\n',' '),flush=True)
print('COMPLETE',flush=True)
