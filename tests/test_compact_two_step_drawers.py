from pathlib import Path
import sys,re
ROOT = Path(__file__).resolve().parents[1]
BUILDER=(ROOT/"build_unified_three_styles.py").read_text(encoding="utf8")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
checks={
 "compact title":'<h1>创作设置</h1>' in HTML and 'JT 灵感工作台' in HTML,
 "no top intro":'选择画风与原创/角色模式，再按分类抽屉调整身体、服装、姿势和背景' not in HTML,
 "no style technical note":'固定使用已训练触发词与已上传 LoRA' not in HTML,
 "no batch technical note":'普通出图：1个云任务，批量节点一次出N张' not in HTML,
 "no manual technical note":'手动模式会直接使用下面输入的正向/负向提示词' not in HTML,
 "no per-item picker notes":'picker-note' not in HTML and '不选择即为“无”' not in HTML and '可多选；不选择即为“无”' not in HTML,
 "no item selected-value summary":'<div class="value">${selectedItems(k)' not in BUILDER,
 "no item expand buttons":'class="expand"' not in BUILDER and 'expandedKeys' not in BUILDER,
 "drawers remain collapsed initially":'openDrawers=new Set()' in HTML and '.drawer-body{display:none' in HTML,
 "one click opens category":'openDrawers.has(d.id)?openDrawers.delete(d.id):openDrawers.add(d.id)' in HTML,
 "selects immediately visible inside open drawer":'.drawer.open .drawer-body{display:grid' in HTML and '.picker-wrap{display:block' in HTML,
 "direct selector always rendered":'<div class="picker-wrap"><select class="picker"' in BUILDER,
 "reroll lock retained":'class="reroll"' in BUILDER and 'class="lock"' in BUILDER,
 "drawer head no selected count":'项已选' not in BUILDER and '默认无' not in BUILDER,
 "favorite opens relevant category only":'openDrawers=new Set(Object.keys(state()).filter' in BUILDER and 'expandedKeys' not in BUILDER,
 "mobile floating controls do not cover drawers":'@media(max-width:700px)' in HTML and '.floating{position:static' in HTML,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
