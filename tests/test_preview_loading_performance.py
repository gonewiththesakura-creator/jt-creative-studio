from pathlib import Path
import re,json,sys
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
REALISM=(ROOT/'build_realism_workbench.py').read_text(encoding='utf8')
CREATOR=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
REALISM_HTML=(ROOT/'static/realism.html').read_text(encoding='utf8')
CREATOR_HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
CREATOR_BYTES=(ROOT/'static/promptgen.html').stat().st_size
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
DEPLOY=(ROOT/'tools/deploy_realism_release.py').read_text(encoding='utf8')
ASSETS=ROOT/'static/previews'
full=[p for p in ASSETS.glob('*.webp') if not p.name.endswith('.thumb.webp')]
thumb=[p for p in ASSETS.glob('*.thumb.webp')]
checks={
 'one lightweight asset per full preview':len(full)==14 and len(thumb)==14,
 'lightweight assets materially smaller':bool(thumb) and sum(p.stat().st_size for p in thumb)<=sum(p.stat().st_size for p in full)*0.45,
 'lightweight dimensions bounded':bool(thumb) and all(max(Image.open(p).size)<=640 for p in thumb),
 'realism two-stage preview':all(x in REALISM for x in ['WORKFLOW_PREVIEW_THUMBS','preloadWorkflowPreviews','loadFullWorkflowPreview','requestIdleCallback']),
 'creator two-stage preview':all(x in CREATOR for x in ['preview_thumb','preloadStylePreviews','loadFullStylePreview','requestIdleCallback']),
 'creator html stays below fast boot budget':CREATOR_BYTES<450_000,
 'full style data externalized':bool(re.search(r'const STYLE_CONFIGS=\{\};const STYLE_BOOT=.*?;const STYLE_CONFIG_URL="/static/style-configs\.[0-9a-f]{12}\.json";',CREATOR_HTML,re.S)),
 'style data hydrates asynchronously':all(x in CREATOR_HTML for x in ['async function loadStyleConfigs()','fetch(STYLE_CONFIG_URL','renderBootPreview()','styleDataReady']),
 'remaining previews wait for hydration and idle':all(x in CREATOR_HTML for x in ['scheduleStylePreviewPreload','loadStyleConfigs().then','preloadStylePreviews']),
 'instant previews embedded':REALISM_HTML.count('data:image/webp;base64,')>=6 and CREATOR_HTML.count('data:image/webp;base64,')>=7,
 'embedded thumbs stay compact':sum(p.stat().st_size for p in thumb if p.name.startswith('realism-'))<180000 and sum(p.stat().st_size for p in thumb if p.name.startswith('style-'))<300000,
 'all thumbs in atomic release':all(('static/previews/'+p.name) in DEPLOY for p in thumb),
 'versioned preview URLs':all(x in REALISM+CREATOR for x in ['?v=']),
 'immutable preview cache':all(x in SERVER for x in ['static/previews','max-age=31536000','immutable']),
 'full quality assets preserved':len(full)==14,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
