from pathlib import Path
import json, re, sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf-8")
MANIFEST=ROOT/"sources"/"pool_union_manifest.json"
checks={"union manifest exists":MANIFEST.exists()}
if MANIFEST.exists():
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    m=re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=",HTML,re.S)
    checks["embedded style JSON found"]=bool(m)
    if m:
        styles=json.loads(m.group(1))
        expected=manifest["union_pools"]
        source_pools=manifest["raw_source_pools"]
        checks["three profiles present"]=set(styles)=={"cold","sketch","graphic"}
        for source_id,pools0 in source_pools.items():
            for key,items0 in pools0.items():
                checks[f"source preserved:{source_id}:{key}"]={tuple(x) for x in items0}.issubset({tuple(x) for x in expected[key]})
        for sid in ("cold","sketch","graphic"):
            pools=styles[sid]["pools"]
            checks[f"{sid} has every source category"]=set(pools)==set(expected)
            for key,items in expected.items():
                checks[f"{sid}:{key} preserves full union"]={tuple(x) for x in pools[key]}=={tuple(x) for x in items}
        checks["manifest records all three sources"]=set(manifest.get("sources",{}))=={"cold","sketch","graphic"}
        checks["no category removed"]=all(manifest["union_counts"][k]>=max(v.get(k,0) for v in manifest["source_counts"].values()) for k in expected)
for k,v in checks.items(): print(k,v)
sys.exit(0 if checks and all(checks.values()) else 1)
