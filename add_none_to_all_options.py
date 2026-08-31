from pathlib import Path
import re

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")
FILES = [ROOT / "promptgen.html", ROOT / "index.html"]

for path in FILES:
    s = path.read_text(encoding="utf-8")
    # Limit edits to the POOLS object only.
    start = s.index("const POOLS = {")
    end = s.index("\n};", start)
    pools = s[start:end]

    names = re.findall(r'^  ([A-Za-z_][A-Za-z0-9_]*): \[$', pools, re.M)
    changed = []
    for key in names:
        marker = f"  {key}: [\n"
        pos = pools.index(marker) + len(marker)
        # Do not duplicate if this pool already has an explicit generic omit option.
        head = pools[pos:pos+180]
        if '["无（不添加此部分）",""],' in head:
            continue
        pools = pools[:pos] + '    ["无（不添加此部分）",""],\n' + pools[pos:]
        changed.append(key)

    s = s[:start] + pools + s[end:]
    path.write_text(s, encoding="utf-8")
    print(path.name, "pool_count", len(names), "added_none", len(changed), changed)
