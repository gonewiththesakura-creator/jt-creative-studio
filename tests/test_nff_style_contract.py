from pathlib import Path
import json,re,sys

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
BUILDER=(ROOT/"build_unified_three_styles.py").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
LOCAL_MODEL=Path(r"D:/ComfyUI_Mie/ComfyUI/models/loras/Anima_JT/06_nff_style_v1_step2000.safetensors")
match=re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=",HTML,re.S)
styles=json.loads(match.group(1)) if match else {}
nff=styles.get("nff") or {};sketch=styles.get("sketch") or {}
checks={
 "four style buttons":all(x in HTML for x in ['data-style="cold"','data-style="sketch"','data-style="graphic"','data-style="nff"']),
 "nff exact trigger":nff.get('trigger')=='jt_nffstyle_v1' and 'jt_nffstyle_v1' in SERVER,
 "nff exact dual step2000":nff.get('lora1')=='06_nff_style_v1_step2000.safetensors' and nff.get('lora2')=='06_nff_style_v1_step2000.safetensors' and SERVER.count('06_nff_style_v1_step2000.safetensors')>=2,
 "nff never uses step1600":'06_nff_style_v1_step1600.safetensors' not in nff.get('lora1','')+nff.get('lora2',''),
 "nff pools equal sketch":bool(nff) and nff.get('pools')==sketch.get('pools') and nff.get('labels')==sketch.get('labels'),
 "nff uses sketch quality and adult head":bool(nff) and nff.get('prefix')==sketch.get('prefix') and nff.get('head')==sketch.get('head'),
 "nff has non sketch negative":bool(nff.get('negative')) and nff.get('negative')!=sketch.get('negative'),
 "nff independent style description":bool(nff.get('style')) and nff.get('style')!=sketch.get('style') and 'jt_style1_v1' not in nff.get('style',''),
 "nff not staged sketch":'currentStyle===\'sketch\'' in HTML and "currentStyle==='nff'" not in re.search(r'function updateBatchSemantics\(\).*?\}',HTML,re.S).group(0) if re.search(r'function updateBatchSemantics\(\).*?\}',HTML,re.S) else False,
 "server trusted nff preset":all(x in SERVER for x in ['"nff": {','"trigger": "jt_nffstyle_v1"','"LORA1": "06_nff_style_v1_step2000.safetensors"','"LORA2": "06_nff_style_v1_step2000.safetensors"']),
 "server rejects browser lora override":'loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}' in SERVER,
 "snapshot restores nff":'STYLE_CONFIGS[snapshot.style]' in HTML and "currentStyle=STYLE_CONFIGS[snapshot.style]?snapshot.style:'cold'" in HTML,
 "builder owns nff":all(x in BUILDER for x in ['"nff":{','jt_nffstyle_v1','06_nff_style_v1_step2000.safetensors']),
 "local nff file exists":LOCAL_MODEL.exists() and LOCAL_MODEL.stat().st_size>1024,
}
for name,value in checks.items():print(name,value)
sys.exit(0 if all(checks.values()) else 1)
