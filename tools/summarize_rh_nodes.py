"""Summarize real RH workflow nodes: id -> class_type + title + scalar inputs."""
import json, pathlib

DIR = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")

for f in sorted(DIR.glob("*.json")):
    nodes = json.loads(f.read_text(encoding="utf-8"))
    print("=" * 60)
    print(f.name, "-", len(nodes), "nodes")
    for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
        ct = node.get("class_type", "")
        title = (node.get("_meta") or {}).get("title", "")
        ins = node.get("inputs", {})
        scalars = {k: v for k, v in ins.items() if not isinstance(v, list) and not isinstance(v, dict)}
        if scalars or any(ct.lower().find(x) >= 0 for x in ["load", "text", "prompt", "video", "image", "int", "float", "slider", "seed", "math", "condition"]):
            print(f"  {nid:>4} | {ct:<45} | {title:<28} | {json.dumps(scalars, ensure_ascii=False)[:120]}")
