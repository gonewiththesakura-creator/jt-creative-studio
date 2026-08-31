from pathlib import Path
import hashlib,json,subprocess,tempfile,sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
ATT=Path(r"C:/Users/JT/AppData/Local/hermes/attachments")
CASES={
 "sketch":{
  "source":ATT/"sketch_anime_dual_mode_generator (1).html",
  "built":ROOT/"static"/"original_sketch.html",
  "sha":"bede47b8608b80a1211646ea75cdf27dadb4df11fe085ab753fa25e65c496e49",
  "rows":230,"categories":17,"style":"sketch","trigger":"jt_style1_v1","path":"/original-sketch"},
 "graphic":{
  "source":ATT/"graphic_anime_style2_dual_mode_generator (1).html",
  "built":ROOT/"static"/"original_graphic.html",
  "sha":"3f7b52578f8321e6cf993912818813920e396dae83fcf97651ee4872a73dcba5",
  "rows":66,"categories":12,"style":"graphic","trigger":"jt_style2_v1","path":"/original-graphic"},
}
def config(path,name):
 s=path.read_text(encoding='utf8');a=s.index('const DEFAULT_PREFIX');b=s.index('let state',a);block=s[a:b]
 tmp=Path(tempfile.gettempdir())/f'orig_contract_{name}.js';tmp.write_text(block+'\nconsole.log(JSON.stringify({DEFAULT_PREFIX,FIXED_HEAD,FIXED_STYLE,NEGATIVE,POOLS,LABELS,ORDER}));',encoding='utf8')
 r=subprocess.run(['node',str(tmp)],capture_output=True,text=True,encoding='utf8');assert r.returncode==0,r.stderr
 return json.loads(r.stdout)
checks={}
for name,c in CASES.items():
 checks[f'{name} source hash']=c['source'].exists() and hashlib.sha256(c['source'].read_bytes()).hexdigest()==c['sha']
 checks[f'{name} built page exists']=c['built'].exists()
 if c['built'].exists():
  src=config(c['source'],name+'s');out=config(c['built'],name+'b');html=c['built'].read_text(encoding='utf8')
  checks[f'{name} exact original config preserved']=src==out
  checks[f'{name} exact pool counts']=len(out['POOLS'])==c['categories'] and sum(map(len,out['POOLS'].values()))==c['rows']
  checks[f'{name} fixed backend identity']=f"const CLOUD_STYLE_ID='{c['style']}'" in html and f"const CLOUD_TRIGGER='{c['trigger']}'" in html
  checks[f'{name} generation controls']=all(x in html for x in ['id="cloudW"','id="cloudH"','id="cloudBatch"','id="cloudHd"','id="cloudSeedMode"','id="cloudSeed"','id="cloudGenerateCloud"','id="cloudGenerateLocal"'])
  checks[f'{name} current api request']=all(x in html for x in ["'/api/generate'","negative_prompt:NEGATIVE","prompt_mode:'options'","seed_mode:cloudSeedMode.value",f"style_id:CLOUD_STYLE_ID"])
  checks[f'{name} native batch explanation']='1个云任务，批量节点一次出N张' in html
  checks[f'{name} history favorites']=all(x in html for x in ['/api/jobs','/api/favorites','收藏图片、提示词和种子','套用提示词、选项和种子'])
  checks[f'{name} structured snapshot']=all(x in html for x in ['source_page:CLOUD_PAGE_ID','state:JSON.parse(JSON.stringify(state))','locked:JSON.parse(JSON.stringify(locked))','seed:+cloudSeed.value'])
  checks[f'{name} back home']='href="/promptgen"' in html
checks['sketch staged controls']=CASES['sketch']['built'].exists() and all(x in CASES['sketch']['built'].read_text(encoding='utf8') for x in ['id="cloudSequence"','每阶段1张，共提交3/4个云任务'])
home=(ROOT/'static'/'promptgen.html').read_text(encoding='utf8');server=(ROOT/'server.py').read_text(encoding='utf8')
checks['home original links']=all(x in home for x in ['href="/original-sketch"','原始铅绘','href="/original-graphic"','原始古风'])
checks['server original routes']=all(x in server for x in ['"/original-sketch": "original_sketch.html"','"/original-graphic": "original_graphic.html"'])
for k,v in checks.items():print(k,v)
sys.exit(0 if checks and all(checks.values()) else 1)
