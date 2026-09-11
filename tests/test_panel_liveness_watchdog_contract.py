from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
SCRIPT=ROOT/'tools/panel_liveness_watchdog.py'
SERVICE=ROOT/'deploy/comfy-panel-watchdog.service'
TIMER=ROOT/'deploy/comfy-panel-watchdog.timer'
checks={
 'dependency-free live endpoint':'path == "/api/live"' in SERVER and '"service": "comfy-panel"' in SERVER,
 'watchdog script exists':SCRIPT.is_file(),
 'two consecutive failures':SCRIPT.is_file() and all(x in SCRIPT.read_text(encoding='utf8') for x in ['FAILURE_THRESHOLD = 2','STATE_FILE','systemctl','restart','comfy-panel']),
 'probe is bounded':SCRIPT.is_file() and all(x in SCRIPT.read_text(encoding='utf8') for x in ['127.0.0.1:8189/api/live','timeout=3']),
 'units exist':SERVICE.is_file() and TIMER.is_file(),
 'timer every minute':TIMER.is_file() and all(x in TIMER.read_text(encoding='utf8') for x in ['OnBootSec=2min','OnUnitActiveSec=1min','Persistent=true']),
 'service calls watchdog':SERVICE.is_file() and '/usr/local/libexec/comfy-panel-watchdog.py' in SERVICE.read_text(encoding='utf8') and '/home/admin/comfy-panel/tools/panel_liveness_watchdog.py' not in SERVICE.read_text(encoding='utf8'),
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
