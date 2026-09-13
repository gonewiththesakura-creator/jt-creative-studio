from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
BUILDER=(ROOT/"build_unified_three_styles.py").read_text(encoding="utf8")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
checks={
 "mobile generation dock is fixed":'position:fixed;left:12px;right:12px;bottom:calc(8px + env(safe-area-inset-bottom))' in HTML and 'padding-bottom:calc(220px + env(safe-area-inset-bottom))' in HTML,
 "mobile generation dock stays one row":'.generation-actions{grid-template-columns:repeat(2,minmax(0,1fr));' in HTML and 'id="apiDrawerOpen"' in HTML,
 "workbench shell":all(x in HTML for x in ['class="app-shell"','class="topbar"','class="studio-grid"']),
 "brand and primary nav":all(x in HTML for x in ['class="brand-mark"','JT 灵感工作台','class="topnav-link active"','创作台']),
 "original styles unified and video nav":all(x in HTML for x in ['data-style="original_sketch"','原始铅绘','data-style="original_graphic"','原始古风','href="/video"','视频']) and 'href="/original-sketch"' not in HTML,
 "topbar library actions":all(x in HTML for x in ['id="favOpen"','id="histOpen"','class="topbar-action"']),
 "left configure pane":all(x in HTML for x in ['class="creation-pane"','class="creation-scroll"','创作设置']),
 "persistent generation footer":'class="creation-footer"' in HTML and '.creation-footer{' in HTML,
 "right preview pane":all(x in HTML for x in ['class="preview-pane"','class="preview-stage"','id="stylePreview"','效果预览']),
 "backend result tabs":all(x in HTML for x in ['class="result-tabs"','data-result-tab="cloud"','data-result-tab="local"','云端结果','本地结果']),
 "backend result panels":all(x in HTML for x in ['id="genCloudResult"','id="genLocalResult"','data-result-panel="cloud"','data-result-panel="local"']),
 "all generation controls retained":all(x in HTML for x in ['id="genW"','id="genH"','id="genBatch"','id="genHd"','id="seedMode"','id="genSeed"']) and 'id="sketchProcess"' not in HTML,
 "prompt modes retained":all(x in HTML for x in ['id="promptMode"','id="manualPositive"','id="manualNegative"','id="promptText"']),
 "style and mode controls retained":all(x in HTML for x in ['data-style="cold"','data-style="sketch"','data-style="graphic"','data-mode="original"','data-mode="character"']),
 "five two-step drawers retained":all(x in HTML for x in ['"id":"character"','"id":"body"','"id":"outfit"','"id":"pose"','"id":"background"','.picker-wrap{display:block']),
 "dual generation retained":all(x in HTML for x in ['id="genCloudBtn"','id="genLocalBtn"',"generate('cloud')","generate('local')"]),
 "preview tab interaction":'setResultTab' in HTML and 'data-result-tab' in HTML,
 "result activates preview":'setResultTab(j.generation_backend' in HTML,
 "desktop two columns":'grid-template-columns:minmax(360px,460px) minmax(0,1fr)' in HTML,
 "mobile single column":'@media(max-width:820px)' in HTML and 'grid-template-columns:1fr' in HTML,
 "mobile nav scrolls":'.topnav{display:flex' in HTML and 'overflow-x:auto' in HTML,
 "mobile hit targets":'@media(max-width:820px)' in HTML and '.item-actions button{width:44px;height:44px}' in HTML,
 "mobile random actions hit targets":'.actions .primary{min-height:44px' in HTML,
 "no old floating buttons":'class="floating favorites"' not in HTML and 'class="floating history"' not in HTML,
 "reference palette":all(x in HTML for x in ['--brand:#536cff','--canvas:#f6f7fb','--surface:#ffffff','--text:#20222a']),
 "reduced motion":'@media(prefers-reduced-motion:reduce)' in HTML,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
