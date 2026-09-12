from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "promptgen.html").read_text(encoding="utf8")
BUILDER = (ROOT / "build_unified_three_styles.py").read_text(encoding="utf8")
SERVER = (ROOT / "server.py").read_text(encoding="utf8")

match = re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=", HTML, re.S)
styles = json.loads(match.group(1)) if match else {}

checks = {
    "cold branch switch exists": all(x in HTML for x in [
        'id="coldVariantSwitch"',
        'data-style-variant="character_bound"',
        'data-style-variant="style_only"',
        "人物+画风",
        "仅画风",
    ]),
    "branch switch only appears for cold": "updateColdVariantUI" in HTML,
    "branch state is submitted": "style_variant:currentStyleVariant()" in HTML,
    "branch state is snapshotted": "style_variant:currentStyleVariant()" in HTML and "snapshot.style_variant" in HTML,
    "branch restored by favorites": "setStyleVariant" in HTML and "snapshot.style_variant" in HTML,
    "history distinguishes branch": "style_variant" in HTML and "人物+画风" in HTML and "仅画风" in HTML,
    "builder owns branch UI": all(x in BUILDER for x in ["coldVariantSwitch", "character_bound", "style_only"]),
    "server persists branch": all(x in SERVER for x in ['"style_variant": preset["id"]', 'resolve_style_preset']),
    "existing cold profile is not duplicated as a fake style": "cold_style" not in styles,
    "two prompt modes remain": all(x in HTML for x in ['data-mode="original"', 'data-mode="character"']),
    "candidate limitation is disclosed": "角色偏置" in HTML or "低泄漏" in HTML,
    "candidate is not labeled as certified pure style": "仅画风候选" in HTML and ">仅画风<" not in HTML,
}
for name, passed in checks.items():
    print(name, passed)
raise SystemExit(0 if all(checks.values()) else 1)
