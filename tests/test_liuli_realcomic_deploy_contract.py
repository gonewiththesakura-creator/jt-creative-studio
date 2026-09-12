from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
DEPLOY=ROOT/"tools"/"deploy_liuli_realcomic_release.py"
text=DEPLOY.read_text(encoding="utf8") if DEPLOY.exists() else ""
checks={
 "deploy script exists":DEPLOY.exists(),
 "server config six entries included":all(name in text for name in ['server.py','config.json','promptgen.html','index.html','original_sketch.html','original_graphic.html','realcomic.html','video.html']),
 "release-specific rollback set":'.pre-liuli-realcomic' in text,
 "stage and live byte verification":all(x in text for x in ['staging mismatch','live mismatch','hashlib.sha256']),
 "server and config syntax before swap":all(x in text for x in ['py_compile','json.load','.release.new']),
 "whole release rollback":'rollback_release' in text and 'for remote in RELEASE_FILES' in text,
 "new route rollback removes empty marker":'if remote_stat.st_size == 0' in text and 'rm -f --' in text,
 "privileged restart on deploy and rollback":text.count('sudo systemctl restart comfy-panel')>=2,
 "health and public route gates":all(x in text for x in ['/api/health','local_comfy_ok','/realcomic','data-style="hanmanga"']),
 "data and credentials excluded":all(x not in text for x in ['panel_data/jobs.json','panel_data/favorites.json','RUNNINGHUB_API_KEY=','PANEL_TOKEN=']),
 "credentials loaded but not embedded":'password=CREDS["password"]' in text and 'password="' not in text and "password='" not in text,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
