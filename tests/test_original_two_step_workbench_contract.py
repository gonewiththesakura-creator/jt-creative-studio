from pathlib import Path
import json,re,sys
from _style_config_contract import load_style_configs
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
BUILDER=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
styles=load_style_configs(ROOT)
checks={
 'same creation workbench hierarchy':all(x in HTML for x in ['<h1>创作设置</h1>','class="section-label">人物模式','id="drawers"','id="randomAll"','id="clearAll"']),
 'all option categories start hidden':'openDrawers=new Set()' in HTML and '.drawer-body{display:none' in HTML,
 'one category click reveals selectors':"openDrawers.has(d.id)?openDrawers.delete(d.id):openDrawers.add(d.id)" in HTML and '.drawer.open .drawer-body' in HTML,
 'two step direct picker':'class="picker"' in HTML and 'class="picker-wrap"' in HTML,
 'random and lock retained':all(x in HTML for x in ['class="reroll"','class="lock"']),
 'favorites restore only relevant drawers':'openDrawers=new Set(Object.keys(state()).filter' in HTML,
 'exact original configs embedded':sum(map(len,styles['original_sketch']['pools'].values()))==230 and sum(map(len,styles['original_graphic']['pools'].values()))==66,
 'builder owns unified profiles':all(x in BUILDER for x in ['"original_sketch":{','"original_graphic":{','RAW_SOURCE_POOLS']),
 'mobile controls remain accessible':all(x in HTML for x in ['.drawer-head{min-height:48px}','.item-actions button{width:44px;height:44px}']),
 'mobile generation dock is in document flow':'.creation-footer {position:static' in HTML,
 'mobile generation dock stays one row':'@media(max-width:480px)' in HTML and '.generation-actions{grid-template-columns:repeat(2,minmax(0,1fr));' in HTML and 'id="apiDrawerOpen"' in HTML,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
