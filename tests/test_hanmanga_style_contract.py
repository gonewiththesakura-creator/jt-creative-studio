from pathlib import Path
import json,re,sys

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
ATT=Path(r"C:/Users/JT/AppData/Local/hermes/attachments/JT灵感工作台_古漫画风版.html")
SOURCE=ROOT/"sources"/"hanmanga_profile.source.json"
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
BUILDER=(ROOT/"build_unified_three_styles.py").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
match=re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=",HTML,re.S)
styles=json.loads(match.group(1)) if match else {}
attached_match=re.search(r"<script>const STYLE_CONFIGS=(\{.*?\});const DRAWERS=",ATT.read_text(encoding="utf8"),re.S)
attached=json.loads(attached_match.group(1))["hanmanga"] if attached_match else {}
source=json.loads(SOURCE.read_text(encoding="utf8")) if SOURCE.exists() else {}
han=styles.get("hanmanga") or {}
checks={
 "immutable attachment profile extracted exactly":source==attached and len(source.get("pools",{}))==32 and sum(len(v) for v in source.get("pools",{}).values())==382,
 "five style buttons":all(x in HTML for x in ['data-style="cold"','data-style="sketch"','data-style="graphic"','data-style="hanmanga"','data-style="nff"']),
 "hanmanga trusted frontend metadata":han.get("trigger")=="jt_liulistyle_v1" and han.get("lora1")=="08_liuli_style_v1_step600.safetensors" and han.get("lora2")=="08_liuli_style_v1_step600.safetensors",
 "no sketch backend alias":bool(han) and "backendStyleId" not in han and "hanmangaNote" not in HTML,
 "special vocabulary and defaults preserved":han.get("pools")==source.get("pools") and han.get("labels")==source.get("labels") and han.get("defaultSelections")==source.get("defaultSelections") and han.get("defaultMode")=="original",
 "server trusted hanmanga preset":all(x in SERVER for x in ['"hanmanga": {','"trigger": "jt_liulistyle_v1"','"LORA1": "08_liuli_style_v1_step600.safetensors"','"LORA2": "08_liuli_style_v1_step600.safetensors"']),
 "browser cannot override lora":'loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}' in SERVER,
 "snapshot restores hanmanga":'STYLE_CONFIGS[snapshot.style]' in HTML and "currentStyle=STYLE_CONFIGS[snapshot.style]?snapshot.style:'cold'" in HTML,
 "builder owns immutable profile":'hanmanga_profile.source.json' in BUILDER and 'jt_liulistyle_v1' in BUILDER and '08_liuli_style_v1_step600.safetensors' in BUILDER,
 "existing mappings unchanged":styles.get('sketch',{}).get('trigger')=='jt_style1_v1' and styles.get('graphic',{}).get('trigger')=='jt_style2_v1' and styles.get('nff',{}).get('trigger')=='jt_nffstyle_v1',
 "local lora exists":(Path(r"D:/ComfyUI_Mie/ComfyUI/models/loras/Anima_JT/08_liuli_style_v1_step600.safetensors")).stat().st_size>1024,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
