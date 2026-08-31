"""Validate config.json video workflow node maps against real RH workflow JSON."""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

# Map workflowId -> real nodes
real = {}
for f in REAL.glob("*.json"):
    nodes = json.loads(f.read_text(encoding="utf-8"))
    real[f.stem] = nodes

# We know which real file corresponds to which workflowId from fetch order:
# the fetch script saved by key, so real[key] already matches the key.

ok = True
for w in [x for x in cfg["workflows"] if x.get("kind") == "video"]:
    wid = w["rh_workflow_id"]
    nodes = real.get(w["id"])
    if nodes is None:
        print(f"[{w['id']}] NO REAL NODES FILE"); ok = False; continue
    print(f"===== {w['id']} (workflow {wid}) — {len(nodes)} real nodes")
    # verify media nodes
    for key, m in (w.get("rh_media") or {}).items():
        nid = str(m["node"])
        node = nodes.get(nid)
        if not node:
            print(f"  [FAIL] media {key}: node {nid} NOT in workflow"); ok = False; continue
        field = m["field"]
        if field not in node.get("inputs", {}):
            print(f"  [FAIL] media {key}: node {nid} has no field '{field}' (inputs={list(node.get('inputs',{}).keys())})"); ok = False; continue
        print(f"  [ok] media {key}: node {nid} field '{field}' ✓")
    for key, p in (w.get("rh_params") or {}).items():
        nid = str(p["node"])
        node = nodes.get(nid)
        if not node:
            print(f"  [FAIL] param {key}: node {nid} NOT in workflow"); ok = False; continue
        field = p["field"]
        if field not in node.get("inputs", {}):
            print(f"  [FAIL] param {key}: node {nid} has no field '{field}' (inputs={list(node.get('inputs',{}).keys())})"); ok = False; continue
        print(f"  [ok] param {key}: node {nid} field '{field}' ✓")

print()
print("ALL OK" if ok else "HAS FAILURES")
