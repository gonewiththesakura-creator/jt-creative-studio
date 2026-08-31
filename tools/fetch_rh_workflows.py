"""Fetch real RunningHub workflow JSON for the 5 video workflows."""
import json, urllib.request, pathlib, os

RH_KEY = os.environ.get("RUNNINGHUB_API_KEY", "")
if not RH_KEY:
    raise RuntimeError("RUNNINGHUB_API_KEY is required")
OUT = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel/video_wf/rh_real")
OUT.mkdir(parents=True, exist_ok=True)

WFS = {
    "h3_t2v_i2v": "2093554209044480001",
    "wardrobe": "2093554183483215873",
    "action": "2093554154237509633",
    "h3_lightx2v": "2093554104655167490",
    "h3_4step": "2093554049743339522",
}

for key, wfid in WFS.items():
    body = json.dumps({"apiKey": RH_KEY, "workflowId": wfid}).encode()
    req = urllib.request.Request(
        "https://www.runninghub.cn/api/openapi/getJsonApiFormat",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {RH_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
    except Exception as e:
        print(key, "ERR", e)
        continue
    if resp.get("code") != 0:
        print(key, "FAILED", resp.get("code"), resp.get("msg"))
        continue
    prompt_raw = (resp.get("data") or {}).get("prompt") or ""
    try:
        nodes = json.loads(prompt_raw)
    except Exception as e:
        print(key, "BAD JSON", e, prompt_raw[:200])
        continue
    (OUT / f"{key}.json").write_text(json.dumps(nodes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(key, "OK", len(nodes), "nodes")
