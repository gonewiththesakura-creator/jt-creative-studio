from pathlib import Path
import json,re,sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
SERVER=(ROOT/"server.py").read_text(encoding="utf8")
checks={}
m=re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=",HTML,re.S)
checks["embedded profiles found"]=bool(m)
if m:
 s=json.loads(m.group(1))
 checks["five corrected triggers"]={k:v['trigger'] for k,v in s.items()}=={'cold':'jt_style3_v2','sketch':'jt_style1_v1','graphic':'jt_style2_v1','hanmanga':'jt_liulistyle_v1','nff':'jt_nffstyle_v1'}
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
checks["old incorrect triggers absent from generated page"]=all(x not in HTML for x in ['jt_inkwash_v1','jt_softpaint_v1','jt_style1_v2','jt_style2_v2'])
checks["prepare applies configured defaults"]="defaultSelections" in HTML and "defaultMode" in HTML and "find(x=>x[0]===label)" in HTML
checks["initial style is sketch"]="let currentStyle='sketch'" in HTML
for k,v in checks.items():print(k,v)
sys.exit(0 if checks and all(checks.values()) else 1)
