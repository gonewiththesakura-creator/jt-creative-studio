"""Final validation with CORRECT content->file mapping."""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
REAL = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
files = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in REAL.glob("*.json")}

# CORRECT mapping: workflow content -> file whose nodes actually match.
# Verified by node ids:
#   h3_t2v_i2v (超级加速版): nodes 1,2,3,4,5,6,7,9,12,15,17,36,37,44,45,46,52,55 -> file h3_t2v_i2v
#   wardrobe (换装): nodes 1,4,5,8,11,13,17,19,20,21,22,23,26,27,28,29,30,31,32,38,39,40,42,44,45,46,47,48,49,50,51,53,54,55,56,58,59,61,62,63,64,67 -> file h3_4step
#   action (动作迁移): nodes 986,993,1000,1006,1007,1010,1012,1013,1016,1018,1020,1022,1024,1026,1031,1032,1036,1038,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1058,1059,1060,1061,1062,1063,1064,1069,1070,1071,1072,1076,1077,1078,1079,1084 -> file h3_lightx2v
#   h3_lightx2v (8步图生): nodes 1,2,3,4,5,6,7,9,12,15,17,36,37,42,44,45,46,47,50,55,64,68,69,71,75 -> file action
#   h3_4step (4步首尾帧): nodes 144,145,146,147,148,149,152,153,155,156,163,166,167,168,172,176,188,189,190,191 -> file wardrobe
CONTENT_TO_FILE = {
    "h3_t2v_i2v": "h3_t2v_i2v",
    "wardrobe": "h3_4step",
    "action": "h3_lightx2v",
    "h3_lightx2v": "action",
    "h3_4step": "wardrobe",
}

ok = True
for w in [x for x in cfg["workflows"] if x.get("kind") == "video"]:
    fname = CONTENT_TO_FILE.get(w["id"])
    nodes = files.get(fname, {})
    print(f"===== {w['id']} (workflow {w['rh_workflow_id']}) -> real file {fname}")
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
