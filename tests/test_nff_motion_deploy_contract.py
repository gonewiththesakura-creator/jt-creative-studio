from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
DEPLOY=ROOT/"tools"/"deploy_nff_motion_release.py"
text=DEPLOY.read_text(encoding="utf8") if DEPLOY.exists() else ""
checks={
 "deploy script exists":DEPLOY.exists(),
 "server and five entries included":all(name in text for name in ['server.py','promptgen.html','index.html','original_sketch.html','original_graphic.html','video.html']),
 "release-specific rollback set":'.pre-nff-motion-workbench' in text,
 "stage verifies bytes":all(x in text for x in ['staging mismatch','live mismatch','hashlib.sha256']),
 "remote syntax before swap":'py_compile' in text and '.release.new' in text,
 "whole release rollback":'rollback_release' in text and 'for remote in RELEASE_FILES' in text,
 "service restart and health gate":all(x in text for x in ['systemctl restart comfy-panel','/api/health','local_comfy_ok']),
 "privileged restart used on deploy and rollback":text.count('sudo systemctl restart comfy-panel')>=2,
 "data paths excluded":all(x not in text for x in ['panel_data/jobs.json','panel_data/favorites.json','tools/creds.json\"']),
 "credentials loaded but never embedded":'password=CREDS["password"]' in text and 'RUNNINGHUB_API_KEY=' not in text and 'password="' not in text and "password='" not in text,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
