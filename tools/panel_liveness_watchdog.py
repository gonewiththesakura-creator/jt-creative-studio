#!/usr/bin/env python3
"""Restart comfy-panel only after repeated local liveness failures."""
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

LIVE_URL = "http://127.0.0.1:8189/api/live"
STATE_FILE = Path("/run/comfy-panel-watchdog.failures")
FAILURE_THRESHOLD = 2


def probe_live():
    marker = b'"service":"comfy-panel"'
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=3) as response:
            return response.status == 200 and marker in response.read(256).replace(b" ", b"")
    except urllib.error.HTTPError as error:
        # A marked overload response proves the panel process and accept loop
        # are alive. Unmarked 503s (proxy/upstream failures) are not trusted.
        if error.code != 503:
            return False
        body = error.read(256).replace(b" ", b"")
        return marker in body and b'"overloaded":true' in body
    except Exception:
        return False


def read_failures():
    try:
        return max(0, int(STATE_FILE.read_text(encoding="ascii").strip()))
    except Exception:
        return 0


def write_failures(value):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(max(0, int(value))), encoding="ascii")


def restart_panel():
    subprocess.run(["systemctl", "restart", "comfy-panel"], check=True, timeout=30)


def run_once():
    if probe_live():
        write_failures(0)
        return 0
    failures = read_failures() + 1
    if failures < FAILURE_THRESHOLD:
        write_failures(failures)
        return 0
    restart_panel()
    write_failures(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_once())
