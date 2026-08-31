"""Precise validation: print real inputs of each target node for every workflow."""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
files = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in REAL.glob("*.json")}

# Map config workflow id -> real file by actual content (verified above):
# file action -> h3_lightx2v ; file h3_4step -> h3_t2v_i2v ; file h3_lightx2v -> action
# file wardrobe -> h3_4step ; file h3_t2v_i2v -> h3_t2v_i2v
CONTENT_TO_FILE = {
    "h3_lightx2v": "action",      # workflowId 2093554154237509633
    "h3_t2v_i2v": "h3_4step",     # workflowId 2093554209044480001
    "action": "h3_lightx2v",      # workflowId 2093554104655167490
    "h3_4step": "wardrobe",       # workflowId 2093554183483215873
    "wardrobe": "h3_4step",       # workflowId 2093554049743339522
}

print("Real file content ground truth:")
for fname, nodes in files.items():
    print(f"  {fname}: {sorted(str(k) for k in nodes)[:5]}... ({len(nodes)} nodes)")

ok = True
for w in [x for x in cfg["workflows"] if x.get("kind") == "video"]:
    fname = CONTENT_TO_FILE.get(w["id"])
    if not fname or fname not in files:
        print(f"[{w['id']}] NO REAL FILE"); ok = False; continue
    nodes = files[fname]
    print(f"===== {w['id']} (workflow {w['rh_workflow_id']}) -> real file {fname}")
    for key, m in (w.get("rh_media") or {}).items():
        nid = str(m["node"]); node = nodes.get(nid)
        if not node:
            print(f"  [FAIL] media {key}: node {nid} missing"); ok = False; continue
        ins = list(node.get("inputs", {}).keys())
        if m["field"] not in ins:
            print(f"  [FAIL] media {key}: node {nid} inputs={ins} need '{m['field']}'"); ok = False; continue
        print(f"  [ok] media {key}: node {nid} field '{m['field']}'")
    for key, p in (w.get("rh_params") or {}).items():
        nid = str(p["node"]); node = nodes.get(nid)
        if not node:
            print(f"  [FAIL] param {key}: node {nid} missing"); ok = False; continue
        ins = list(node.get("inputs", {}).keys())
        if p["field"] not in ins:
            print(f"  [FAIL] param {key}: node {nid} inputs={ins} need '{p['field']}'"); ok = False; continue
        print(f"  [ok] param {key}: node {nid} field '{p['field']}'")
print()
print("ALL OK" if ok else "HAS FAILURES")
