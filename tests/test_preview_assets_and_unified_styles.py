from pathlib import Path
import json,re,sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
DESKTOP=Path(r"C:/Users/JT/Desktop/22")
REALISM=(ROOT/'static/realism.html').read_text(encoding='utf8')
CREATOR=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
DEPLOY=(ROOT/'tools/deploy_realism_release.py').read_text(encoding='utf8')
match=re.search(r'const STYLE_CONFIGS=(.*?);const DRAWERS=',CREATOR,re.S)
styles=json.loads(match.group(1)) if match else {}
realism_assets={
 'realcomic':'realism-realcomic.webp',
 'realism_krea2':'realism-krea2.webp',
 'realism_2511':'realism-2511.webp',
 'realism_multisample':'realism-multisample.webp',
 'realism_qwen_zi':'realism-qwen-zi.webp',
 'realism_zi_flowmatch':'realism-zi-flowmatch.webp',
}
style_assets={
 'cold':'style-cold.webp','sketch':'style-sketch.webp','original_sketch':'style-original-sketch.webp',
 'graphic':'style-graphic.webp','original_graphic':'style-original-graphic.webp',
 'hanmanga':'style-hanmanga.webp','nff':'style-nff.webp',
}
checks={
 'all 13 source previews exist':len(list(DESKTOP.glob('*.png')))==13,
 'all generated preview assets exist':all((ROOT/'static/previews'/x).exists() for x in [*realism_assets.values(),*style_assets.values()]),
 'realism mapping embedded':all(re.search(rf'"{re.escape(k)}":"/static/previews/{re.escape(v)}\?v=[0-9a-f]{{12}}"',REALISM) for k,v in realism_assets.items()),
 'unmapped workflows stay empty':all(x in REALISM for x in ['没有提供预览图','WORKFLOW_PREVIEWS']) and all(k not in re.search(r'const WORKFLOW_PREVIEWS=(.*?);',REALISM,re.S).group(1) for k in ['realism_3in1','realism_4k_text']),
 'realism preview swaps and hides for tasks':all(x in REALISM for x in ['workflowPreview','updateWorkflowPreview','currentPreviewUrl','previewEmpty.classList.add(\'hidden\')']),
 'seven creator styles':set(styles)=={'cold','sketch','original_sketch','graphic','original_graphic','hanmanga','nff'},
 'style previews mapped':all(re.fullmatch(r'/static/previews/'+re.escape(v)+r'\?v=[0-9a-f]{12}',styles.get(k,{}).get('preview','')) for k,v in style_assets.items()),
 'original profiles preserve raw pools':styles.get('original_sketch',{}).get('pools')!=styles.get('sketch',{}).get('pools') and styles.get('original_graphic',{}).get('pools')!=styles.get('graphic',{}).get('pools'),
 'original trusted server aliases':all(x in SERVER for x in ['"original_sketch": {','"original_graphic": {','"trigger": "jt_style1_v1"','"trigger": "jt_style2_v1"']),
 'staged painting retired':'id="sketchProcess"' not in CREATOR and 'sequence_mode = "off"' in SERVER,
 'style preview swaps and hides for results':all(x in CREATOR for x in ['stylePreview','updateStylePreview','cfg().preview','previewEmpty.classList.add(\'hidden\')']),
 'top navigation consolidated':all(x not in CREATOR for x in ['href="/original-sketch"','href="/original-graphic"']) and all(x in CREATOR for x in ['href="/"','href="/realism"','href="/video"']),
 'legacy original URLs redirect':all(x in SERVER for x in ['path in ("/original-sketch", "/original-graphic")','"original_sketch" if path == "/original-sketch" else "original_graphic"']),
 'query style initializes selection':all(x in CREATOR for x in ['URLSearchParams(location.search)','styleParam','STYLE_CONFIGS[styleParam]']),
 'assets included in atomic release':'static/previews/' in DEPLOY,
 'preview MIME types':all(x in SERVER for x in ['def static_content_type','".webp": "image/webp"','".json": "application/json"']),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
