"""Inspect h3_lightx2v: RHHiddenNodes 75 full inputs; find any node referencing 50/64/75."""
import json, pathlib

REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
nodes = json.loads((REAL / "action.json").read_text(encoding="utf-8"))

print("=== node 75 (RHHiddenNodes) ===")
print(json.dumps(nodes.get("75"), ensure_ascii=False, indent=1))
print()
print("=== all nodes that reference node 50 or 64 or 75 ===")
for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
    ins = node.get("inputs", {})
    refs = [f"{k}->{v}" for k, v in ins.items() if isinstance(v, list) and str(v[0]) in ("50", "64", "75")]
    if refs:
        print(f"  node {nid} ({node.get('class_type')}): {refs}")
print()
print("=== all node ids + class for the file ===")
for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
    print(f"  {nid:>4} {node.get('class_type')}")
