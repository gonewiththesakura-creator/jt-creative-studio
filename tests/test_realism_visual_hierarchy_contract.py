from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML=(ROOT/'static'/'realism.html').read_text(encoding='utf-8')
BUILDER=(ROOT/'build_realism_workbench.py').read_text(encoding='utf-8')
checks={
 'core operate region exists':all(x in HTML for x in ['id="operateControls"','核心操作']),
 'required media and primary text routed to operate':all(x in HTML for x in ['isCoreOperateControl(mapping)?operateControls','target.appendChild(renderControl']),
 'exactly two configure drawers':HTML.count('<section class="config-drawer"')==2 and all(x in HTML for x in ['常用设置','高级与输出']),
 'drawer headings visible before oversized bodies':HTML.find('id="commonDrawer"')<HTML.find('id="advancedDrawer"') and 'config-stack' in HTML,
 'result preview capped':all(x in HTML for x in ['max-height:54vh','object-fit:contain']),
 'result actions adjacent':all(x in HTML for x in ['result-actions','收藏结果与全部参数','下载原图']),
 'mobile footer never overlays controls':'@media(max-width:820px)' in HTML and '.creation-footer{position:static' in HTML,
 'mobile active nav is kept visible':all(x in HTML for x in ['ensureActiveNavVisible','nav.scrollLeft','addEventListener(\'resize\'']),
 'builder owns layout':all(x in BUILDER for x in ['operateControls','isCoreOperateControl','max-height:54vh']),
}
for k,v in checks.items():print(k,v)
raise SystemExit(0 if all(checks.values()) else 1)
