from pathlib import Path
import json,sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
CONFIG=json.loads((ROOT/"config.json").read_text(encoding="utf8"))
BUILDER=ROOT/"build_realism_workbench.py"; PAGE=ROOT/"static"/"realism.html"; LEGACY=ROOT/"static"/"realcomic.html"
html=PAGE.read_text(encoding="utf8");script=BUILDER.read_text(encoding="utf8");legacy=LEGACY.read_text(encoding="utf8")
w=next((x for x in CONFIG['workflows'] if x.get('id')=='realcomic'),{})
pages=[ROOT/"static"/x for x in ['index.html','promptgen.html','original_sketch.html','original_graphic.html','video.html']]
checks={
 'trusted ai app config':w.get('kind')=='ai_app' and w.get('backend')=='runninghub' and w.get('rh_ai_app_id')=='2025090022289973249',
 'exact public input mapping':w.get('rh_media',{}).get('source_image',{}).get('node')=='504' and w.get('rh_params',{}).get('requirements',{}).get('node')=='491',
 'empty optional instruction':w.get('params_defaults',{}).get('requirements')=='',
 'server v2 ai app adapter':all(x in SERVER for x in ['def rh_submit_ai_app','/run/ai-app/','def rh_build_ai_app_node_info','def rh_run_ai_app']),
 'server strict app routes':all(x in SERVER for x in ['/api/realcomic-upload','/api/ai-app-generate','kind") != "ai_app"']),
 'server fixed webapp id':"rh_ai_app_id" in SERVER and 'body.get("webappId")' not in SERVER,
 'server idempotency and cloud lane':all(x in SERVER for x in ['client_request_id','existing_job_for_request','_submit_locks["cloud"]']),
 'ai app rejects empty request id':'client_request_id is required' in SERVER.split('if path == "/api/ai-app-generate"',1)[1].split('if path == "/api/upload"',1)[0],
 'legacy route redirects':all(x in SERVER for x in ['if path == "/realcomic"','Location", "/realism?workflow=realcomic"']) and '/realism?workflow=realcomic' in legacy,
 'unified page one image optional text':all(x in html for x in ['renderImageControl','renderTextControl']) and w.get('name')=='快速真人化（原漫画转真人）',
 'unified app uses dedicated adapters':all(x in html for x in ["current.kind==='ai_app'","/api/realcomic-upload","/api/ai-app-generate"]),
 'unified async lifecycle':all(x in html for x in ['/api/job/','client_request_id','sessionStorage','restoreTasks']),
 'unified history favorites':all(x in html for x in ['/api/jobs?scope=realism','/api/favorites','realcomic']),
 'all navigation has one route':all(p.exists() and 'href="/realism"' in p.read_text(encoding='utf8') and 'href="/realcomic"' not in p.read_text(encoding='utf8') for p in pages),
 'mobile and accessibility':all(x in html for x in ['@media(max-width:820px)','min-height:44px','aria-live','aria-busy']),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
