"""Dump the real h3_t2v_i2v file (file that matches workflow 2093554209044480001)."""
import json, pathlib

REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
nodes = json.loads((REAL / "h3_t2v_i2v.json").read_text(encoding="utf-8"))
print("nodes:", sorted(str(k) for k in nodes), len(nodes))
for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
    ct = node.get("class_type", "")
    title = (node.get("_meta") or {}).get("title", "")
    ins = node.get("inputs", {})
    scalars = {k: v for k, v in ins.items() if not isinstance(v, list) and not isinstance(v, dict)}
    if scalars:
        print(f"  {nid:>4} | {ct:<45} | {title:<30} | {json.dumps(scalars, ensure_ascii=False)[:130]}")
