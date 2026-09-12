from pathlib import Path
import json,sys
ROOT = Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config.json').read_text(encoding='utf8'))
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
CREATOR=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
REALISM=(ROOT/'static/realism.html').read_text(encoding='utf8')
IMPORTER=(ROOT/'tools/import_private_realism_workflows.py').read_text(encoding='utf8')
DEPLOY=(ROOT/'tools/deploy_realism_release.py').read_text(encoding='utf8')
ids={w['id'] for w in CONFIG['workflows']}
checks={
 '3in1 removed from production config':'realism_3in1' not in ids,
 '3in1 removed from public page':'realism_3in1' not in REALISM,
 '3in1 retired from importer':'realism_3in1' not in IMPORTER,
 '3in1 retired from release target':'realism_3in1' not in DEPLOY.split('TARGET_WORKFLOWS =',1)[1].split('}',1)[0],
 'no staged painting controls':all(x not in CREATOR for x in ['id="sketchProcess"','铅绘分步','3步：','4步：']),
 'new requests force one pass':'sequence_mode = "off"' in SERVER,
 'staged execution no longer dispatches':all(x not in SERVER for x in ['rh_run_sketch_sequence(job, jobdir, w)','local_run_sketch_sequence(job, jobdir, w)']),
 'preview version remains':all(x in CREATOR for x in ['id="stylePreview"','style-original-sketch.webp']) and 'WORKFLOW_PREVIEWS' in REALISM,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
