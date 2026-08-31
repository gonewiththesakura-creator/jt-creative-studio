"""Real end-to-end submit test for h3_4step after node map fix.
Uploads a real tiny PNG as first/last frame, submits to RH, polls status.
This spends a small amount of RH coins but is the only way to confirm
NODE_INFO_MISMATCH is gone.
"""
import json, time, urllib.request, pathlib, base64, secrets, os

RH_KEY = os.environ.get("RUNNINGHUB_API_KEY", "")
if not RH_KEY:
    raise RuntimeError("RUNNINGHUB_API_KEY is required")

# 1. upload a real PNG (use the sample from the workflow itself: a 1x1 won't work
#    for video, but LoadImage just needs a valid file name - use the workflow's own sample)
import io
# Use a real image: create a small 64x64 PNG programmatically
import struct, zlib

def make_png(w, h, rgb):
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b""
    for y in range(h):
        raw += b"\x00" + bytes(rgb) * w
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

png = make_png(64, 64, (180, 120, 140))

def upload(data, filename):
    boundary = "----rh" + secrets.token_hex(8)
    def f(name, val):
        return f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode()
    def fp(name, fn):
        return f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fn}\"\r\nContent-Type: image/png\r\n\r\n".encode()
    body = b"".join([f("apiKey", RH_KEY), f("fileType", "input"), fp("file", filename), data, b"\r\n", f"--{boundary}--\r\n".encode()])
    req = urllib.request.Request("https://www.runninghub.cn/task/openapi/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "Authorization": f"Bearer {RH_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    if resp.get("code") != 0:
        raise RuntimeError(f"upload failed: {resp}")
    return resp["data"]["fileName"]

print("uploading first_frame...")
f1 = upload(png, "first.png")
print("uploading last_frame...")
f2 = upload(png, "last.png")

# 2. build nodeInfoList for h3_4step (workflow 2093554183483215873)
node_list = [
    {"nodeId": "146", "fieldName": "image", "fieldValue": f1},
    {"nodeId": "147", "fieldName": "image", "fieldValue": f2},
    {"nodeId": "176", "fieldName": "value", "fieldValue": "一只猫从窗台跳下来, 轻快地落地, 全程自然流畅"},
    {"nodeId": "144", "fieldName": "value", "fieldValue": 5},
    {"nodeId": "145", "fieldName": "value", "fieldValue": 1024},
]
body = json.dumps({"addMetadata": False, "nodeInfoList": node_list, "instanceType": "default", "usePersonalQueue": "false"}).encode()
req = urllib.request.Request("https://www.runninghub.ai/openapi/v2/run/workflow/2093554183483215873",
                             data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {RH_KEY}"})
print("submitting...")
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    print("SUBMIT RESPONSE:", json.dumps(resp, ensure_ascii=False)[:600])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:600])
except Exception as e:
    print("ERR", e)
