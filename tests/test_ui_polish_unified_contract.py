from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
VIDEO_SOURCE=(ROOT/"sources"/"video_business.js").read_text(encoding="utf8")
VIDEO_BUILDER=(ROOT/"build_video_workbench.py").read_text(encoding="utf8")
DEPLOY=(ROOT/"tools"/"deploy_ui_branch.py").read_text(encoding="utf8")
MAIN=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
SKETCH=(ROOT/"static"/"original_sketch.html").read_text(encoding="utf8")
GRAPHIC=(ROOT/"static"/"original_graphic.html").read_text(encoding="utf8")
VIDEO=(ROOT/"static"/"video.html").read_text(encoding="utf8")
PAGES=[MAIN,SKETCH,GRAPHIC,VIDEO]
checks={
 # Fixed header + independently scrollable body; outer panel clips all media.
 "library flex shell":all(x in MAIN for x in ['.library-panel{','display:flex','flex-direction:column','overflow:hidden','isolation:isolate']),
 "library header outside scroll":all(x in MAIN for x in ['class="library-header"','class="library-scroll"','id="favList"','id="histList"']),
 "library scroll only body":'.library-scroll{' in MAIN and 'flex:1' in MAIN and 'overflow-y:auto' in MAIN,
 "library header not sticky":'.overlay-head{position:sticky' not in MAIN,
 "favorite cards clip images":'.library-scroll .job{overflow:hidden' in MAIN and '.library-scroll .job img{position:static' in MAIN,
 # Two distinct liquid treatments, active only while each button is running.
 "main liquid buttons":all(x in MAIN for x in ['liquid-button cloud','liquid-button local','liquid-label-base','liquid-label-fill','liquid-fill']),
 "liquid state helpers":all(x in MAIN for x in ['setLiquidLoading','setLiquidProgress','is-loading','--liquid-progress']),
 "liquid backend distinction":all(x in MAIN for x in ['--liquid-color:#536cff','--liquid-color:#3c9b82']),
 "cloud idle button exposes fill":'.liquid-button{--liquid-color:#536cff' in MAIN and 'background:#fff;color:#4057e8' in MAIN and '.liquid-button.cloud{border-color:#aeb9ff' in MAIN and '--liquid-level:calc(100% - var(--liquid-progress))' in MAIN and '.liquid-button.is-loading{--liquid-level:5%' not in MAIN,
 "liquid respects reduced motion":'prefers-reduced-motion:reduce' in MAIN and '.liquid-fill{will-change:auto}' in MAIN,
 "original liquid buttons":all(all(x in p for x in ['liquid-button cloud','liquid-button local','setLiquidLoading']) for p in [SKETCH,GRAPHIC]),
 # Import generated options-mode prompt into editable manual fields.
 "main prompt import button":'id="importGeneratedPrompt"' in MAIN and '导入并编辑' in MAIN,
 "main prompt import logic":all(x in MAIN for x in ['importGeneratedPromptToManual','manualPositive.value=buildCorePrompt()','manualNegative.value=cfg().negative',"promptMode.value='manual'"]),
 "library opens at top":all(x in MAIN for x in ["favOverlay.querySelector('.library-scroll').scrollTop=0","histOverlay.querySelector('.library-scroll').scrollTop=0"]),
 "original libraries open at top":all(all(x in p for x in ["cloudFavOverlay.querySelector('.library-scroll').scrollTop=0","cloudHistOverlay.querySelector('.library-scroll').scrollTop=0"]) for p in [SKETCH,GRAPHIC]),
 "video libraries open at top":all(x in VIDEO for x in ["favOverlay.querySelector('.library-scroll').scrollTop=0","histOverlay.querySelector('.library-scroll').scrollTop=0"]),
 "all overlay close targets current shell":all("closest('.library-overlay')" in p and "closest('.overlay')" not in p for p in PAGES),
 "original prompt import":all(all(x in p for x in ['id="importGeneratedPrompt"','importGeneratedPromptToManual','manualPositive']) for p in [SKETCH,GRAPHIC]),
 # Unified visual shell across all public creator pages.
 "all pages workbench shell":all(all(x in p for x in ['class="app-shell"','class="topbar"','class="brand-mark"','class="studio-grid"']) for p in PAGES),
 "all pages same nav":all(all(x in p for x in ['JT 灵感工作台','创作台','原始铅绘','原始古风','视频']) for p in PAGES),
 "all pages preview pane":all('class="preview-pane"' in p for p in PAGES),
 "all pages shared palette":all(all(x in p for x in ['--brand:#536cff','--canvas:#f6f7fb']) for p in PAGES),
 "original pages use creation workbench headings":all('<h1>创作设置</h1>' in p and '.original-content{display:none!important}' in p for p in [SKETCH,GRAPHIC]) and 'ORIGINAL SKETCH' in SKETCH and 'ORIGINAL GRAPHIC' in GRAPHIC,
 "mobile top tools keep readable labels":all('.topbar-action{font-size:0' not in p for p in PAGES),
 "original mobile action targets":all('.original-content .lock,.original-content .reroll{width:44px!important;height:44px!important}' in p for p in [SKETCH,GRAPHIC]),
 "idle generation buttons have visible borders":all(all(x in p for x in ['#aeb9ff','#a3d0c5']) for p in [MAIN,SKETCH,GRAPHIC]),
 "video preview empty state":all(x in VIDEO for x in ['<h2>视频预览</h2>','id="videoEmpty"','生成后，视频将在这里播放','id="taskPanel"']),
 "video workflow error is actionable":all(x in VIDEO for x in ['config-loading','config-error','retryWorkflows','视频配置加载失败',"btn=document.getElementById('genBtn')",'btn.disabled=true']),
 # Existing functional contracts remain on original/video pages.
 "original configs retained":'const POOLS' in SKETCH and 'const POOLS' in GRAPHIC and "const CLOUD_STYLE_ID='sketch'" in SKETCH and "const CLOUD_STYLE_ID='graphic'" in GRAPHIC,
 "video functions retained":all(x in VIDEO for x in ['/api/video-generate','id="genBtn"','id="wfSwitch"']),
 "video builder uses immutable business source":'sources"/"video_business.js' in VIDEO_BUILDER and 'P.read_text' not in VIDEO_BUILDER and all(x in VIDEO_SOURCE for x in ['/api/video-generate','/api/upload','const tasks=new Map()','/api/favorites']),
 "deployment includes all five entry files":all(f"'{name}'" in DEPLOY for name in ['promptgen.html','index.html','original_sketch.html','original_graphic.html','video.html']) and "pre-ui-polish" in DEPLOY,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
