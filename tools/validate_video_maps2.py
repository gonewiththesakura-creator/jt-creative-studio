"""Identify each real RH workflow file by its actual node content, then
validate config.json node maps against the CORRECT file."""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

# load all real files
files = {}
for f in REAL.glob("*.json"):
    files[f.stem] = json.loads(f.read_text(encoding="utf-8"))

# signature: a set of node ids that identify the workflow
def sig(nodes):
    return sorted(str(k) for k in nodes.keys())[:8]

for name, nodes in files.items():
    print(f"--- file {name}: nodes {sig(nodes)}... (total {len(nodes)})")

print()
# Known signatures from real content:
# wardrobe (换装): nodes 1,4,5,8,11,13,17,19,20,21,22,23,26,32,38,53,54,62,63,64... (Wan2.2 换装)
# action (动作迁移): nodes 986,993,1000,1006,1007,1013,1016,1022,1024,1026,1031,1036,1047,1048,1049,1050,1055,1058,1059,1062,1063,1064,1069,1070,1071,1072,1076,1077,1078,1079,1084 (Wan2.2 动作)
# h3_lightx2v (8步图生): nodes 1,2,3,4,5,6,7,9,12,15,17,36,37,42,44,45,46,50,55,64,68,69,71,75 (H3)
# h3_4step (4步首尾帧): nodes 144,145,146,147,148,149,152,153,155,156,163,166,167,168,172,176,188,189,190,191 (H3 4步)
# h3_t2v_i2v (超级加速版): nodes 1,2,3,4,5,6,7,9,12,15,36,37,44,45,46,55 (H3)

# Determine real content by node id presence
def classify(nodes):
    ids = set(str(k) for k in nodes)
    if "146" in ids and "176" in ids:
        return "h3_4step"          # 4步首尾帧
    if "986" in ids:
        return "action"            # 动作迁移
    if "1031" in ids:
        return "action"
    if "144" in ids:
        return "h3_4step"
    if "50" in ids and "37" in ids and "64" in ids and "71" in ids:
        return "h3_lightx2v"       # 8步图生
    if "36" in ids and "44" in ids:
        return "h3_t2v_i2v"        # 超级加速版
    if "53" in ids and "54" in ids:
        return "wardrobe"          # 换装
    return "unknown"

real_content = {}
for name, nodes in files.items():
    c = classify(nodes)
    real_content[name] = c
    print(f"file {name} -> real content: {c}")

print()
ok = True
for w in [x for x in cfg["workflows"] if x.get("kind") == "video"]:
    # find the file whose content matches this workflow id
    nodes = None
    for name, c in real_content.items():
        if c == w["id"]:
            nodes = files[name]
            break
    if nodes is None:
        print(f"[{w['id']}] no real file matched"); ok = False; continue
    print(f"===== {w['id']} (workflow {w['rh_workflow_id']}) — validated against file whose content is {w['id']}")
    for key, m in (w.get("rh_media") or {}).items():
        nid = str(m["node"]); node = nodes.get(nid)
        if not node or m["field"] not in node.get("inputs", {}):
            print(f"  [FAIL] media {key}: node {nid} field '{m['field']}'"); ok = False; continue
        print(f"  [ok] media {key}: node {nid} field '{m['field']}'")
    for key, p in (w.get("rh_params") or {}).items():
        nid = str(p["node"]); node = nodes.get(nid)
        if not node or p["field"] not in node.get("inputs", {}):
            print(f"  [FAIL] param {key}: node {nid} field '{p['field']}'"); ok = False; continue
        print(f"  [ok] param {key}: node {nid} field '{p['field']}'")

print()
print("ALL OK" if ok else "HAS FAILURES")
