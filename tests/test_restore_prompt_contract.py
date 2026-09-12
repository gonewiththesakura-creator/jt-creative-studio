from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "server.py").read_text(encoding="utf8")
HTML = (ROOT / "static" / "promptgen.html").read_text(encoding="utf8")

# This never-implemented legacy proposal is not part of the shipped console.
# Keep a real green contract so the release gate cannot hide a red test while
# also preventing the UI from advertising a nonexistent recovery feature.
checks = {
    "restore endpoint retired": 'path == "/api/restore-prompt"' not in SERVER,
    "restore upload retired": 'id="restoreFile"' not in HTML,
    "restore action retired": 'id="restoreBtn"' not in HTML and "从旧图恢复提示词" not in HTML,
    "restore metadata UI retired": all(token not in HTML for token in (
        'id="restoreStatus"', 'id="restoreRawPrompt"', 'id="restoreParams"',
        "applyRecoveredPrompt", "mapped_selections", "unmatched_fragments",
    )),
}
for key, value in checks.items():
    print(key, value)
sys.exit(0 if all(checks.values()) else 1)
