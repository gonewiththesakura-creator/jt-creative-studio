from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf-8")
SERVER=(ROOT/"server.py").read_text(encoding="utf-8")
checks={
 "three style buttons": all(x in HTML for x in ['data-style="cold"','data-style="sketch"','data-style="graphic"']),
 "two generation modes": all(x in HTML for x in ['data-mode="original"','data-mode="character"']),
 "current style gets character feature": 'character_inspired' in HTML and '角色' in HTML,
 "drawer categories": all(x in HTML for x in ['"id":"character"','"id":"body"','"id":"outfit"','"id":"pose"','"id":"background"']),
 "drawers collapsed by default": '.drawer-body{display:none' in HTML and '.drawer.open .drawer-body{display:grid' in HTML,
 "fixed mapping cold": all(x in HTML for x in ['05_style3_v2_step1600.safetensors','04_style3_step800.safetensors','jt_style3_v2']),
 "fixed mapping sketch": all(x in HTML for x in ['01_style1_step900.safetensors','jt_style1_v1']),
 "fixed mapping graphic": all(x in HTML for x in ['02_style2_step900.safetensors','jt_style2_v1']),
 "only style3 uses v2": 'jt_style2_v2' not in HTML and 'jt_style1_v2' not in HTML,
 "style hidden fields sent": all(x in HTML for x in ['style_id:currentStyle','mode:currentMode','generation_backend:backend','selection_snapshot:{...snapshotSelections(),generation_backend:backend}']),
 "favorites restore style and mode": all(x in HTML for x in ["currentStyle=snapshot.style||'cold'","currentMode=snapshot.mode||'original'"]),
 "server fixed style presets": all(x in SERVER for x in ['STYLE_PRESETS = {','"sketch": {','"graphic": {']),
 "server stores style and mode": all(x in SERVER for x in ['"style_id": style_id','"mode": mode']),
 "server ignores browser lora names for RH": 'loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}' in SERVER,
}
for k,v in checks.items(): print(k,v)
sys.exit(0 if all(checks.values()) else 1)
