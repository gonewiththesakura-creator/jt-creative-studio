"""Full public-panel E2E test: upload 2 images via public /api/upload,
submit h3_4step via public /api/video-generate, confirm no 803."""
import json, urllib.request, struct, zlib, base64, time

BASE = "http://8.210.125.65:8189"

def make_png(w, h, rgb):
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:500]}
    except Exception as e:
        return {"error": str(e)}

# 1. upload first/last frame
png = make_png(64, 64, (170, 110, 140))
f1 = api("/api/upload", {"filename": "first.png", "data": base64.b64encode(png).decode()})
print("upload first:", f1)
f2 = api("/api/upload", {"filename": "last.png", "data": base64.b64encode(png).decode()})
print("upload last:", f2)
if "fileName" not in f1 or "fileName" not in f2:
    print("UPLOAD FAILED, abort"); raise SystemExit(1)

# 2. submit h3_4step
body = {
    "workflow": "h3_4step",
    "prompt": "一只猫从窗台跳下来, 轻快地落地, 全程自然流畅",
    "negative_prompt": "",
    "media": {"first_frame": f1["fileName"], "last_frame": f2["fileName"]},
    "params": {"duration": 5, "max_side": 1024},
}
r = api("/api/video-generate", body)
print("submit:", json.dumps(r, ensure_ascii=False)[:300])

if "job_id" in r:
    job_id = r["job_id"]
    # poll a few times (short) to show status flow
    for i in range(3):
        time.sleep(5)
        j = api("/api/job/" + job_id)
        print(f"poll {i+1}: status={j.get('status')} provider={j.get('provider_status')} pct={j.get('progress_pct')} elapsed={j.get('elapsed')} err={str(j.get('error'))[:150]}")
        if j.get("status") in ("done", "error"):
            break
