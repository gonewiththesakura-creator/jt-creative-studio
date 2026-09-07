from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
BUILDER=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
checks={
 'staged selector removed':all(x not in HTML for x in ['id="sketchProcess"','铅绘分步','3步：','4步：']),
 'builder no staged selector':all(x not in BUILDER for x in ['id="sketchProcess"','sketchProcess.value','sketchProcess.onchange']),
 'browser sends one pass':"const sequence_mode='off'" in HTML and "sequence_mode:'off'" in HTML,
 'server forces one pass':'sequence_mode = "off"' in SERVER,
 'runtime no staged dispatch':all(x not in SERVER for x in ['rh_run_sketch_sequence(job, jobdir, w)','local_run_sketch_sequence(job, jobdir, w)']),
 'legacy history safety retained':'RETIRED_SEQUENCE_MODES' in SERVER and '服务重启中断多阶段任务' in SERVER,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
