from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
VIDEO_SOURCE=(ROOT/'sources/video_business.js').read_text(encoding='utf8')
VIDEO_BUILDER=(ROOT/'build_video_workbench.py').read_text(encoding='utf8')
DEPLOY=(ROOT/'tools/deploy_realism_release.py').read_text(encoding='utf8')
MAIN=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
REALISM=(ROOT/'static/realism.html').read_text(encoding='utf8')
VIDEO=(ROOT/'static/video.html').read_text(encoding='utf8')
SKETCH=(ROOT/'static/original_sketch.html').read_text(encoding='utf8')
GRAPHIC=(ROOT/'static/original_graphic.html').read_text(encoding='utf8')
ACTIVE=[MAIN,REALISM,VIDEO]
checks={
 'library flex shell':all(x in MAIN for x in ['.library-panel{','display:flex','flex-direction:column','overflow:hidden','isolation:isolate']),
 'library header outside scroll':all(x in MAIN for x in ['class="library-header"','class="library-scroll"','id="favList"','id="histList"']),
 'library scroll only body':'.library-scroll{' in MAIN and 'flex:1' in MAIN and 'overflow-y:auto' in MAIN,
 'favorite cards clip images':'.library-scroll .job{overflow:hidden' in MAIN and '.library-scroll .job img{position:static' in MAIN,
 'main liquid buttons':all(x in MAIN for x in ['liquid-button cloud','liquid-button local','liquid-label-base','liquid-label-fill','liquid-fill']),
 'liquid state helpers':all(x in MAIN for x in ['setLiquidLoading','setLiquidProgress','is-loading','--liquid-progress']),
 'liquid backend distinction':all(x in MAIN for x in ['--liquid-color:#536cff','--liquid-color:#3c9b82']),
 'liquid respects reduced motion':'prefers-reduced-motion:reduce' in MAIN and '.liquid-fill{will-change:auto}' in MAIN,
 'main prompt import':all(x in MAIN for x in ['id="importGeneratedPrompt"','importGeneratedPromptToManual','manualPositive.value=buildCorePrompt()','manualNegative.value=cfg().negative']),
 'libraries open at top':all(x in MAIN for x in ["favOverlay.querySelector('.library-scroll').scrollTop=0","histOverlay.querySelector('.library-scroll').scrollTop=0"]),
 'video libraries open at top':all(x in VIDEO for x in ["favOverlay.querySelector('.library-scroll').scrollTop=0","histOverlay.querySelector('.library-scroll').scrollTop=0"]),
 'active pages workbench shell':all(all(x in p for x in ['class="app-shell"','class="topbar"','class="brand-mark"']) for p in ACTIVE),
 'active pages consolidated nav':all(all(x in p for x in ['JT 灵感工作台','创作台','真人化','视频']) and 'href="/original-sketch"' not in p for p in ACTIVE),
 'creator and realism preview panes':all('class="preview-pane"' in p for p in [MAIN,REALISM]),
 'shared palette':all(all(x in p for x in ['--brand:#536cff','--canvas:#f6f7fb']) for p in ACTIVE),
 'original styles unified':all(x in MAIN for x in ['data-style="original_sketch"','data-style="original_graphic"','style-original-sketch.webp','style-original-graphic.webp']),
 'legacy original pages redirect':'/?style=original_sketch' in SKETCH and '/?style=original_graphic' in GRAPHIC and len(SKETCH)<1500 and len(GRAPHIC)<1500,
 'mobile top tools keep readable labels':all('.topbar-action{font-size:0' not in p for p in ACTIVE),
 'idle generation buttons have visible borders':all(x in MAIN for x in ['#aeb9ff','#a3d0c5']),
 'video preview empty state':all(x in VIDEO for x in ['<h2>视频预览</h2>','id="videoEmpty"','生成后，视频将在这里播放','id="taskPanel"']),
 'video workflow error is actionable':all(x in VIDEO for x in ['config-loading','config-error','retryWorkflows','视频配置加载失败',"btn=document.getElementById('genBtn')",'btn.disabled=true']),
 'video functions retained':all(x in VIDEO for x in ['/api/video-generate','id="genBtn"','id="wfSwitch"']),
 'video builder immutable source':'sources"/"video_business.js' in VIDEO_BUILDER and 'P.read_text' not in VIDEO_BUILDER and all(x in VIDEO_SOURCE for x in ['/api/video-generate','/api/upload','const tasks=new Map()','/api/favorites']),
 'atomic deployment includes entries and previews':all(x in DEPLOY for x in ['static/index.html','static/original_sketch.html','static/original_graphic.html','static/realism.html','static/video.html','static/previews/manifest.json']),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
