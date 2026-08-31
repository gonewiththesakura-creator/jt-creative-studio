"""Test h3_lightx2v with duration-structured prompt via public panel."""
import json, urllib.request, base64, struct, zlib, time

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
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:400]}
    except Exception as e:
        return {"error": str(e)}

png = make_png(64, 64, (160, 140, 120))
f = api("/api/upload", {"filename": "frame.png", "data": base64.b64encode(png).decode()})
print("upload:", f)
if "fileName" not in f:
    raise SystemExit(1)

prompt = "视频时长：[5]秒\nshot1:一个女人在街道上行走，身姿摇曳，低角度仰拍，镜头逐渐上移\nshot2:她停下脚步回头看镜头，微风拂过发丝"
body = {
    "workflow": "h3_lightx2v",
    "prompt": prompt,
    "negative_prompt": "",
    "media": {"first_frame": f["fileName"]},
    "params": {"max_side": 832},
}
r = api("/api/video-generate", body)
print("submit:", json.dumps(r, ensure_ascii=False)[:200])
if "job_id" not in r:
    print("SUBMIT FAILED", r); raise SystemExit(1)
job_id = r["job_id"]
for i in range(4):
    time.sleep(6)
    j = api("/api/job/" + job_id)
    print(f"poll {i+1}: status={j.get('status')} provider={j.get('provider_status')} err={str(j.get('error'))[:250]}")
    if j.get("status") in ("done", "error"):
        break
