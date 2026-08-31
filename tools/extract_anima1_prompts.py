from pathlib import Path
from PIL import Image
import json,hashlib,csv,re
ROOT=Path(r"D:/ComfyUI_Mie/ComfyUI/output/Anima_JT/1")
OUT=Path(r"D:/LAN-Share/lora/_work/comfy_panel/reports");OUT.mkdir(exist_ok=True)
rows=[];groups={}
for p in sorted(ROOT.glob('*.png')):
 im=Image.open(p);meta=im.info;g=json.loads(meta['prompt']);positive='';negative='';seed=steps=cfg=sampler=scheduler=denoise=None;models=[];loras=[];width=im.width;height=im.height
 for nid,n in g.items():
  cls=n.get('class_type');inp=n.get('inputs',{})
  if cls=='CLIPTextEncode' and isinstance(inp.get('text'),str):
   if not positive:positive=inp['text']
   elif not negative:negative=inp['text']
  elif cls=='KSampler':
   seed=inp.get('seed');steps=inp.get('steps');cfg=inp.get('cfg');sampler=inp.get('sampler_name');scheduler=inp.get('scheduler');denoise=inp.get('denoise')
  elif cls=='UNETLoader':models.append(inp.get('unet_name'))
  elif 'LoraLoader' in str(cls):loras.append(f"{inp.get('lora_name')}@{inp.get('strength_model')}")
 key=hashlib.sha256((positive+'\0'+negative+'\0'+json.dumps(models)+'\0'+json.dumps(loras)).encode()).hexdigest()[:12]
 row={'file':p.name,'group':key,'width':width,'height':height,'seed':seed,'steps':steps,'cfg':cfg,'sampler':sampler,'scheduler':scheduler,'denoise':denoise,'model':' | '.join(filter(None,models)),'loras':' | '.join(loras),'positive':positive,'negative':negative}
 rows.append(row);groups.setdefault(key,[]).append(row)
# CSV one row per image
csvp=OUT/'Anima_JT_1_34图提示词参数.csv'
with csvp.open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
# readable grouped report
md=['# Anima_JT/1：34张图提示词提取','',f'- 图片：{len(rows)}张',f'- 不同提示词/模型组合：{len(groups)}组','- 来源：PNG内部ComfyUI `prompt` 元数据（精确提取）','']
for i,(gid,rs) in enumerate(groups.items(),1):
 r=rs[0];nums=[re.search(r'_(\d+)_',x['file']).group(1) for x in rs]
 md += [f'## 组{i}（{gid}）',f'**图片编号：** {", ".join(nums)}',f'**文件数：** {len(rs)}',f'**尺寸：** {r["width"]}×{r["height"]}',f'**模型：** `{r["model"]}`',f'**LoRA：** `{r["loras"]}`',f'**参数：** steps={r["steps"]}, CFG={r["cfg"]}, sampler={r["sampler"]}, scheduler={r["scheduler"]}, denoise={r["denoise"]}',f'**各图seed：** '+', '.join(f'{x["file"]}:{x["seed"]}' for x in rs),'','### 正向提示词','```text',r['positive'],'```','','### 负向提示词','```text',r['negative'],'```','']
mdp=OUT/'Anima_JT_1_34图提示词分组.md';mdp.write_text('\n'.join(md),encoding='utf8')
# machine JSON
jsonp=OUT/'Anima_JT_1_34图提示词参数.json';jsonp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
print('images',len(rows),'groups',len(groups))
for i,(gid,rs) in enumerate(groups.items(),1):
 nums=[re.search(r'_(\d+)_',x['file']).group(1) for x in rs];r=rs[0]
 trig=re.findall(r'jt_[a-zA-Z0-9_]+',r['positive'])
 print(i,gid,nums,'triggers',trig,'lora',r['loras'])
print(mdp);print(csvp);print(jsonp)
