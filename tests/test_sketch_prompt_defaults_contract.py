from pathlib import Path
import json,re,sys
from _style_config_contract import load_style_configs
ROOT = Path(__file__).resolve().parents[1]
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
checks={}
try:
 s=load_style_configs(ROOT)
except (AssertionError, OSError, ValueError):
 s={}
checks["external profiles found"]=bool(s)
if s:
 checks["ten corrected triggers"]={k:v['trigger'] for k,v in s.items()}=={'cold':'jt_style3_v2','sketch':'jt_style1_v1','original_sketch':'jt_style1_v1','graphic':'jt_style2_v1','original_graphic':'jt_style2_v1','hanmanga':'jt_liulistyle_v1','nff':'jt_nffstyle_v1','retro_manga_luxury':'jt_style321_v1','style221':'zxqelun','style222':'zxqavri'}
 checks["sketch has default mode character"]=s['sketch'].get('defaultMode')=='character'
 expected={
  'character_inspired':'祢豆子（成年再演绎）',
  'character':'丰满优雅型',
  'expression':'害羞微红',
  'interaction':'回头看镜头',
  'prop':'书本',
  'pose':'蹲姿贴近镜头',
  'camera':'轻微俯拍近景',
  'story':'发呆的空白瞬间',
  'background':'淡粉色马克笔底',
  'accent':'黑白 + 藏蓝',
 }
 defaults=s['sketch'].get('defaultSelections',{})
 checks["full sketch defaults mapped"]=all(defaults.get(k)==v for k,v in expected.items())
 checks["sketch default leaves extra outfit empty"]='special_outfit' not in defaults
 checks["sketch defaults do not contain explicit key"]=not any(x in str(defaults).lower() for x in ['pussy','nude','naked','no panty','no clothes','no cloths'])
checks["server corrected triggers"]=all(x in SERVER for x in ['"sketch": {\n        "trigger": "jt_style1_v1"','"graphic": {\n        "trigger": "jt_style2_v1"','"cold": {\n        "trigger": "jt_style3_v2"'])
checks["old incorrect triggers absent from generated data"]=all(x not in json.dumps(s,ensure_ascii=False) for x in ['jt_inkwash_v1','jt_softpaint_v1','jt_style1_v2','jt_style2_v2'])
checks["prepare applies configured defaults"]="defaultSelections" in HTML and "defaultMode" in HTML and "find(x=>x[0]===label)" in HTML
checks["initial style is sketch"]="let currentStyle='sketch'" in HTML
for k,v in checks.items():print(k,v)
sys.exit(0 if checks and all(checks.values()) else 1)
