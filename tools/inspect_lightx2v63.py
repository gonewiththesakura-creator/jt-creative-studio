"""Inspect h3_lightx2v real workflow: what feeds node 63 JWStringToFloat, and what
nodes 50/64/37 feed into. Find what field drives the duration that must be numeric."""
import json, pathlib

REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
nodes = json.loads((REAL / "action.json").read_text(encoding="utf-8"))  # file action = h3_lightx2v content

print("=== node 63 (JWStringToFloat) full inputs ===")
print(json.dumps(nodes.get("63"), ensure_ascii=False, indent=1))
print()
print("=== node 50 (Text) full ===")
print(json.dumps(nodes.get("50"), ensure_ascii=False, indent=1))
print()
print("=== node 64 (Int) full ===")
print(json.dumps(nodes.get("64"), ensure_ascii=False, indent=1))
print()
print("=== who connects to 63? search all nodes for 63 in inputs ===")
for nid, node in nodes.items():
    for k, v in node.get("inputs", {}).items():
        if isinstance(v, list) and str(v[0]) == "63":
            print(f"  node {nid} ({node.get('class_type')}) input '{k}' <- 63")
print()
print("=== what does 63 receive? (inputs of 63) ===")
ins = nodes.get("63", {}).get("inputs", {})
for k, v in ins.items():
    print(f"  {k}: {v}")
