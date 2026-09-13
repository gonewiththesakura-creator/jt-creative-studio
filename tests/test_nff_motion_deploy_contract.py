from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "tools" / "deploy_nff_motion_release.py"
text = DEPLOY.read_text(encoding="utf-8") if DEPLOY.exists() else ""
result = subprocess.run(
    [sys.executable, str(DEPLOY)], cwd=ROOT, text=True,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)
checks = {
    "retired entry exists": DEPLOY.is_file(),
    "retired entry fails closed": result.returncode != 0,
    "canonical deploy is named": "deploy_realism_release.py" in result.stdout,
    "legacy network and secret access removed": all(token not in text for token in (
        "paramiko", "creds.json", "AutoAddPolicy", "open_sftp", "systemctl",
    )),
}
for key, value in checks.items():
    print(key, value)
raise SystemExit(0 if all(checks.values()) else 1)
