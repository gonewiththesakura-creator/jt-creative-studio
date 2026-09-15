import json
import re


def load_style_configs(root, page="promptgen.html"):
    html = (root / "static" / page).read_text(encoding="utf8")
    match = re.search(
        r'const STYLE_CONFIG_URL="(/static/style-configs\.[0-9a-f]{12}\.json)";',
        html,
    )
    if not match:
        raise AssertionError("creator page does not declare a content-hashed style config")
    relative = match.group(1).removeprefix("/")
    path = root / relative
    if not path.is_file():
        raise AssertionError(f"declared style config does not exist: {relative}")
    return json.loads(path.read_text(encoding="utf8"))
