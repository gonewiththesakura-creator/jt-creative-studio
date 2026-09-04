from pathlib import Path
import json,sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
CONFIG=json.loads((ROOT/"config.json").read_text(encoding="utf8"))
BUILDER=(ROOT/"build_realcomic_workbench.py")
PAGE=ROOT/"static"/"realcomic.html"
html=PAGE.read_text(encoding="utf8") if PAGE.exists() else ''
script=BUILDER.read_text(encoding="utf8") if BUILDER.exists() else ''
w=next((x for x in CONFIG['workflows'] if x.get('id')=='realcomic'),{})
pages=[ROOT/"static"/x for x in ['index.html','promptgen.html','original_sketch.html','original_graphic.html','video.html']]
checks={
 'trusted ai app config':w.get('kind')=='ai_app' and w.get('backend')=='runninghub' and w.get('rh_ai_app_id')=='2025090022289973249',
 'exact public input mapping':w.get('rh_media',{}).get('source_image')=={'node':'504','field':'image','type':'image','label':'二次元图','required':True} and w.get('rh_params',{}).get('requirements',{}).get('node')=='491' and w.get('rh_params',{}).get('requirements',{}).get('field')=='text',
 'default optional instruction':w.get('params_defaults',{}).get('requirements')=='去除水印',
 'server v2 ai app adapter':all(x in SERVER for x in ['def rh_submit_ai_app','/run/ai-app/','def rh_build_ai_app_node_info','def rh_run_ai_app']),
 'server strict app routes':all(x in SERVER for x in ['/api/realcomic-upload','/api/ai-app-generate','kind") != "ai_app"']),
 'server fixed webapp id':"rh_ai_app_id" in SERVER and 'body.get("webappId")' not in SERVER,
 'server idempotency and cloud lane':all(x in SERVER for x in ['client_request_id','existing_job_for_request','_submit_locks["cloud"]']),
 'realcomic route':all(x in SERVER for x in ['"/realcomic"','"realcomic.html"']),
 'realcomic durable builder and page':BUILDER.exists() and PAGE.exists() and 'P.read_text' not in script,
 'one image plus optional text UI':all(x in html for x in ['id="sourceFile"','accept="image/png,image/jpeg,image/webp"','id="requirements"','二次元图','别的要求']),
 'empty optional requirement by default':'<textarea id="requirements" placeholder=' in html and '<textarea id="requirements">去除水印</textarea>' not in html,
 'generate disabled until upload':'id="realcomicGenerate" aria-busy="false" disabled' in html and 'updateGenerateAvailability' in html,
 'only cloud execution':html.count('id="realcomicGenerate"')==1 and '本地生成' not in html,
 'async lifecycle and restoration':all(x in html for x in ['/api/realcomic-upload','/api/ai-app-generate','/api/job/','client_request_id','sessionStorage','任务恢复']),
 'result history favorite download':all(x in html for x in ['/api/jobs','/api/favorites','下载原图','收藏','历史']),
 'actionable errors include job id':all(x in html for x in ['任务号','running_job','job_id']),
 'provider attribution':all(x in html for x in ['第三方 RunningHub AI 应用','Anime to Live-Action V6 Speed']),
 'all navigation includes route':all(p.exists() and 'href="/realcomic"' in p.read_text(encoding='utf8') for p in pages) and 'href="/realcomic"' in html,
 'mobile and accessibility':all(x in html for x in ['@media(max-width:820px)','min-height:44px','aria-live','aria-busy','loading="lazy"','decoding="async"']),
 'mobile result clears fixed dock':'.studio-grid{padding-bottom:calc(118px + env(safe-area-inset-bottom))}' in html,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
