from pathlib import Path
import re, sys
root = Path(__file__).resolve().parents[1]
html=(root/'static'/'promptgen.html').read_text(encoding='utf8')
server=(root/'server.py').read_text(encoding='utf8')
checks={
 'LoRA controls hidden': 'id="genLora1"' not in html and 'id="genLora2"' not in html and 'id="genTrigger"' not in html,
 'HD selector visible': 'id="genHd"' in html and '>高清<' in html,
 'size batch remain': all(x in html for x in ['id="genW"','id="genH"','id="genBatch"']),
 'favorite button present': '收藏' in html,
 'apply button present': '套用提示词' in html,
 'favorite server endpoint': '/api/favorites' in server,
 'job stores selection snapshot': 'selection_snapshot' in server,
 'job api exposes selection snapshot': 'selection_snapshot' in server,
}
for k,v in checks.items(): print(k, v)
if all(checks.values()): sys.exit(0)
sys.exit(1)
