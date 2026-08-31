"""Check RHHiddenNodes structure in all video workflows + what fields they expose."""
import json, pathlib

REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
# content->file mapping from earlier validation
CONTENT_TO_FILE = {
    "h3_t2v_i2v": "h3_t2v_i2v",
    "wardrobe": "h3_4step",
    "action": "h3_lightx2v",
    "h3_lightx2v": "action",
    "h3_4step": "wardrobe",
}
for content, fname in CONTENT_TO_FILE.items():
    nodes = json.loads((REAL / f"{fname}.json").read_text(encoding="utf-8"))
    print(f"===== {content} (file {fname})")
    for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
        if node.get("class_type") == "RHHiddenNodes":
            print(f"  RHHiddenNodes node {nid}:")
            for k, v in node.get("inputs", {}).items():
                print(f"    {k} = {v}")
    # any other hidden/group nodes
    for nid, node in sorted(nodes.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
        ct = node.get("class_type", "")
        if "Hidden" in ct or "Group" in ct:
            print(f"  other hidden: {nid} {ct}")
