from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf-8")
BUILDER=(ROOT/"build_unified_three_styles.py").read_text(encoding="utf-8")
SERVER=(ROOT/"server.py").read_text(encoding="utf-8")
checks={
 "sketch process selector": all(x in HTML for x in ['id="sketchProcess"','value="off"','value="3"','value="4"']),
 "selector only for sketch": "currentStyle==='sketch'" in HTML and 'sketchProcessRow' in HTML,
 "request carries sequence mode": 'sequence_mode:' in HTML,
 "snapshot keeps sequence mode": 'sequence_mode:' in HTML and 'sketchProcess.value' in HTML,
 "results show stage label": 'stage_label' in HTML,
 "server defines four stages": 'SKETCH_SEQUENCE_STAGES' in SERVER and all(x in SERVER for x in ['rough','refined','monochrome','colored']),
 "server has sequence runner": 'def rh_run_sketch_sequence' in SERVER,
 "server reuses one seed": 'sequence_seed' in SERVER,
 "server has 3 and 4 stage paths": 'sketch3' in SERVER and 'sketch4' in SERVER,
 "server records multiple task ids": 'rh_task_ids' in SERVER,
 "server exposes stage state": 'stage_status' in SERVER and 'stage_label' in SERVER,
 "sequence limited to sketch": 'style_id != "sketch"' in SERVER,
 "builder is durable source": all(x in BUILDER for x in ['sketchProcess','sequence_mode','stage_label']),
}
for k,v in checks.items(): print(k,v)
sys.exit(0 if all(checks.values()) else 1)
