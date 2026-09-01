from pathlib import Path
import sys

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SKETCH=(ROOT/"static"/"original_sketch.html").read_text(encoding="utf8")
GRAPHIC=(ROOT/"static"/"original_graphic.html").read_text(encoding="utf8")
BUILDER=(ROOT/"build_original_style_pages.py").read_text(encoding="utf8")
PAGES=[SKETCH,GRAPHIC]
checks={
 "same creation workbench hierarchy":all(all(x in page for x in ['<h1>创作设置</h1>','class="section-label">人物模式','id="originalDrawers"','id="originalRandomAll"','id="originalClearAll"']) for page in PAGES),
 "all option categories start hidden":all('let originalOpenDrawers=new Set()' in page and '.original-drawer-body{display:none' in page for page in PAGES),
 "one category click reveals selectors":all("originalOpenDrawers.has(key)?originalOpenDrawers.delete(key):originalOpenDrawers.add(key)" in page and '.original-drawer.open .original-drawer-body{display:grid' in page for page in PAGES),
 "two step direct picker":all('class="original-picker"' in page and 'class="original-value-summary"' not in page and 'class="original-expand"' not in page for page in PAGES),
 "no legacy visible option grid":all('.original-content{display:none!important}' in page for page in PAGES),
 "random and lock retained":all('class="original-reroll"' in page and 'class="original-lock"' in page for page in PAGES),
 "favorites restore only relevant drawers":all('restoreOriginalOpenDrawers' in page and 'originalExpandedKeys' not in page for page in PAGES),
 "exact source configs stay embedded":all(x in SKETCH for x in ['const DEFAULT_PREFIX','const FIXED_HEAD','const FIXED_STYLE','const NEGATIVE','const POOLS','const LABELS','const ORDER']) and all(x in GRAPHIC for x in ['const DEFAULT_PREFIX','const FIXED_HEAD','const FIXED_STYLE','const NEGATIVE','const POOLS','const LABELS','const ORDER']),
 "builder owns new shell":all(x in BUILDER for x in ['ORIGINAL_WORKBENCH','originalOpenDrawers','original-picker','original-content{display:none!important}']),
 "mobile controls remain accessible":all('.original-drawer-head{width:100%;min-height:48px' in page and '.original-reroll,.original-lock{width:44px;height:44px' in page for page in PAGES),
 "mobile picker targets are 44px":all('.original-picker{display:block;width:100%;min-height:44px' in page for page in PAGES),
 "mobile generation dock is fixed":all('position:fixed;left:12px;right:12px;bottom:calc(8px + env(safe-area-inset-bottom))' in page and 'padding-bottom:calc(104px + env(safe-area-inset-bottom))' in page for page in PAGES),
 "mobile generation dock stays one row":all('@media(max-width:480px){.generation-actions{grid-template-columns:1fr 1fr}' in page for page in PAGES),
}
for name,value in checks.items():print(name,value)
sys.exit(0 if all(checks.values()) else 1)
