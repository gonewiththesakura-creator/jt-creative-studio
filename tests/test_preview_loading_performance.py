from pathlib import Path
import re,json,sys
from PIL import Image
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
REALISM=(ROOT/'build_realism_workbench.py').read_text(encoding='utf8')
CREATOR=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
REALISM_HTML=(ROOT/'static/realism.html').read_text(encoding='utf8')
CREATOR_HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
DEPLOY=(ROOT/'tools/deploy_realism_release.py').read_text(encoding='utf8')
ASSETS=ROOT/'static/previews'
full=[p for p in ASSETS.glob('*.webp') if not p.name.endswith('.thumb.webp')]
thumb=[p for p in ASSETS.glob('*.thumb.webp')]
checks={
 'one lightweight asset per full preview':len(full)==13 and len(thumb)==13,
 'lightweight assets materially smaller':bool(thumb) and sum(p.stat().st_size for p in thumb)<=sum(p.stat().st_size for p in full)*0.45,
 'lightweight dimensions bounded':bool(thumb) and all(max(Image.open(p).size)<=640 for p in thumb),
 'realism two-stage preview':all(x in REALISM for x in ['WORKFLOW_PREVIEW_THUMBS','preloadWorkflowPreviews','loadFullWorkflowPreview','requestIdleCallback']),
 'creator two-stage preview':all(x in CREATOR for x in ['preview_thumb','preloadStylePreviews','loadFullStylePreview','requestIdleCallback']),
 'instant previews embedded':REALISM_HTML.count('data:image/webp;base64,')>=6 and CREATOR_HTML.count('data:image/webp;base64,')>=7,
 'embedded thumbs stay compact':sum(p.stat().st_size for p in thumb)<400000,
 'all thumbs in atomic release':all(('static/previews/'+p.name) in DEPLOY for p in thumb),
 'versioned preview URLs':all(x in REALISM+CREATOR for x in ['?v=']),
 'immutable preview cache':all(x in SERVER for x in ['static/previews','max-age=31536000','immutable']),
 'full quality assets preserved':len(full)==13,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
