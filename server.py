#!/usr/bin/env python3
"""comfy-panel: a minimal remote control panel for local ComfyUI.
Pure stdlib. Runs on the public relay server; talks to local ComfyUI
through an SSH reverse tunnel (server:127.0.0.1:8199 -> local:127.0.0.1:8188).

Env:
  COMFY_URL   default http://127.0.0.1:8188
  PANEL_PORT  default 8189
  PANEL_TOKEN required (auth)
  PANEL_DIR   default ./panel_data (jobs + images)
"""
import json, os, re, sys, time, uuid, threading, urllib.request, urllib.parse
import http.server, socketserver, pathlib, secrets, hashlib
import socket, base64, struct, subprocess, io, gzip

BASE = pathlib.Path(__file__).resolve().parent
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://127.0.0.1:8198").rstrip("/")
PORT = int(os.environ.get("PANEL_PORT", "8189"))
TOKEN = os.environ.get("PANEL_TOKEN", "")
DATA_DIR = pathlib.Path(os.environ.get("PANEL_DIR", str(BASE / "panel_data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR = DATA_DIR / "jobs"; JOBS_DIR.mkdir(exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"
FAVORITES_DIR = DATA_DIR / "favorites"; FAVORITES_DIR.mkdir(exist_ok=True)
FAVORITES_FILE = DATA_DIR / "favorites.json"

# RunningHub API 适配
RH_BASE = "https://www.runninghub.ai/openapi/v2"
RH_KEY = os.environ.get("RUNNINGHUB_API_KEY", "")
RH_TIMEOUT_SUBMIT = 60
RH_TIMEOUT_QUERY = 30
RH_SUBMIT_HARD_TIMEOUT = 120  # wall-clock cap for the whole submit (all retries)
# V2 query exposes only real task states, not a stable percentage. Keep these
# conservative and fixed; never manufacture progress from elapsed/poll count.
RH_STAGE_PROGRESS = {"QUEUED": 0.02, "RUNNING": 0.10}

TPL_DIR = BASE / "templates"
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
WORKFLOWS = {w["id"]: w for w in CONFIG["workflows"]}

# Fixed server-side mappings. The browser only chooses a style id; it cannot
# send arbitrary LoRA filenames or trigger words. Trigger tokens must match the
# tokens used by the corresponding training run.
STYLE_PRESETS = {
    "cold": {
        "trigger": "jt_style3_v2",
        "LORA1": "05_style3_v2_step1600.safetensors",
        "LORA2": "04_style3_step800.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
    "sketch": {
        "trigger": "jt_style1_v1",
        "LORA1": "01_style1_step900.safetensors",
        "LORA2": "01_style1_step900.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
    "graphic": {
        "trigger": "jt_style2_v1",
        "LORA1": "02_style2_step900.safetensors",
        "LORA2": "02_style2_step900.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
    "nff": {
        "trigger": "jt_nffstyle_v1",
        "LORA1": "06_nff_style_v1_step2000.safetensors",
        "LORA2": "06_nff_style_v1_step2000.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
    "hanmanga": {
        "trigger": "jt_liulistyle_v1",
        "LORA1": "08_liuli_style_v1_step600.safetensors",
        "LORA2": "08_liuli_style_v1_step600.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
}

def local_lora_name(name):
    """Map a trusted LoRA basename to the local ComfyUI model path."""
    return "Anima_JT\\" + pathlib.PurePath(str(name)).name

SKETCH_SEQUENCE_STAGES = {
    "sketch4": [
        ("rough", "第1步 · 铅笔大致轮廓", "very rough graphite construction sketch, loose gesture drawing, simple silhouette, visible construction lines, minimal facial detail, monochrome pencil only"),
        ("refined", "第2步 · 人物进一步成型", "refined graphite character sketch, corrected anatomy and facial placement, clearer hair clothing and pose, visible construction lines, monochrome pencil only"),
        ("monochrome", "第3步 · 完成黑白铅笔稿", "finished monochrome graphite anime illustration, clean final pencil linework, detailed cross-hatching, complete face hair clothing and hands, no color"),
        ("colored", "第4步 · 铅笔淡彩完成图", "finished colored-pencil anime illustration, graphite linework and hatching preserved, subtle low-saturation colored pencil and minimal marker accents"),
    ],
    "sketch3": [
        ("rough", "第1步 · 铅笔大致轮廓", "very rough graphite construction sketch, loose gesture drawing, simple silhouette, visible construction lines, minimal facial detail, monochrome pencil only"),
        ("monochrome", "第2步 · 完成黑白铅笔稿", "finished monochrome graphite anime illustration, clean final pencil linework, detailed cross-hatching, complete face hair clothing and hands, no color"),
        ("colored", "第3步 · 铅笔淡彩完成图", "finished colored-pencil anime illustration, graphite linework and hatching preserved, subtle low-saturation colored pencil and minimal marker accents"),
    ],
}

# Cloud and local image generation have independent resources. Keep each
# backend serial, but allow one RunningHub job and one local-ComfyUI job to run
# at the same time. Video jobs are async cloud tasks and may run concurrently.
_submit_locks = {"cloud": threading.Lock(), "local": threading.Lock()}
VIDEO_MAX_CONCURRENT = 3   # max simultaneous RH video tasks (RH queues the rest)
_jobs = {}                        # job_id -> job dict
_lock_jobs = threading.Lock()
_LORA_CACHE = {"t": 0.0, "list": []}
_progress = {}                    # prompt_id -> (value, max) from ComfyUI WebSocket
_favorites = {}
_archive_locks = {}
_archive_locks_guard = threading.Lock()

# ---------- minimal WebSocket client (stdlib only) for real sampling progress ----------
def _ws_connect(host, port, path):
    s = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(4096)
        if not c:
            raise ConnectionError("ws handshake closed")
        buf += c
    if b"101" not in buf.split(b"\r\n", 1)[0]:
        raise ConnectionError("ws handshake failed: " + buf[:120].decode(errors="replace"))
    return s

def _ws_recv(s):
    def exact(n):
        b = b""
        while len(b) < n:
            c = s.recv(n - len(b))
            if not c:
                raise ConnectionError("ws closed")
            b += c
        return b
    hdr = exact(2)
    opcode = hdr[0] & 0x0F
    masked = hdr[1] & 0x80
    ln = hdr[1] & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", exact(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", exact(8))[0]
    mask = exact(4) if masked else b""
    payload = exact(ln)
    if masked:
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    return opcode, payload

def _ws_loop():
    up = urllib.parse.urlparse(COMFY_URL)
    host = up.hostname or "127.0.0.1"
    port = up.port or 80
    path = "/ws?clientId=panel-progress-" + uuid.uuid4().hex[:8]
    while True:
        try:
            s = _ws_connect(host, port, path)
            while True:
                op, payload = _ws_recv(s)
                if op != 1:
                    continue
                try:
                    msg = json.loads(payload.decode())
                except Exception:
                    continue
                t = msg.get("type")
                d = msg.get("data") or {}
                pid = d.get("prompt_id")
                if t == "progress" and pid:
                    _progress[pid] = (int(d.get("value", 0) or 0), int(d.get("max", 1) or 1))
                elif t in ("execution_success", "execution_error") and pid:
                    _progress.pop(pid, None)
        except Exception:
            time.sleep(3)

threading.Thread(target=_ws_loop, daemon=True).start()

def load_jobs():
    global _jobs
    if JOBS_FILE.exists():
        try: _jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except Exception: _jobs = {}
    # On startup no worker threads exist: any job left "running" was interrupted
    # by a restart. Mark it error so it does not hold the global lock forever.
    for j in _jobs.values():
        if j.get("status") == "running":
            j["status"] = "error"
            j["error"] = "服务重启，任务中断（未出图）"
    save_jobs()

def save_jobs():
    tmp = JOBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(JOBS_FILE)

def load_favorites():
    global _favorites
    if FAVORITES_FILE.exists():
        try: _favorites = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
        except Exception: _favorites = {}

def save_favorites():
    tmp = FAVORITES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_favorites, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FAVORITES_FILE)

def http_json(url, data=None, timeout=300):
    req = urllib.request.Request(url, method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    else:
        body = None
    with urllib.request.urlopen(req, body, timeout=timeout) as r:
        return json.loads(r.read().decode())

def http_bytes(url, timeout=60, retries=3):
    """Download binary with streaming read + retry (fixes IncompleteRead)."""
    last = None
    for attempt in range(retries):
        try:
            with _urlopen_bounded(url, None, timeout) as r:
                chunks = []
                while True:
                    c = r.read(65536)
                    if not c:
                        break
                    chunks.append(c)
                return b"".join(chunks)
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed after {retries} tries: {last}")


def download_file_resilient(url, dest, timeout=900):
    """Download a large RunningHub result directly to disk.

    curl is substantially more reliable than urllib against the RH COS CDN:
    it supports IPv4, low-speed detection, connect timeout and retry without
    holding a multi-MB image in Python memory. The old urllib path caused
    500–1000s tails and sometimes saved partial-looking files.
    """
    dest = pathlib.Path(dest)
    part = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        "curl", "-4", "-fL", "--silent", "--show-error",
        "--connect-timeout", "5", "--max-time", str(int(timeout)),
        "--retry", "0",
        "--speed-time", "30", "--speed-limit", "1024",
        "-o", str(part), url,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"result download hard timeout after {timeout}s")
    if p.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"curl exit {p.returncode}: {(p.stderr or p.stdout).strip()[:300]}")
    if not part.exists() or part.stat().st_size < 8:
        part.unlink(missing_ok=True)
        raise RuntimeError("downloaded result is empty")
    with part.open("rb") as f:
        magic = f.read(16)
    if not image_content_type(magic, dest.name):
        part.unlink(missing_ok=True)
        raise RuntimeError("downloaded result is not a supported image")
    part.replace(dest)
    return dest.stat().st_size


def _urlopen_bounded(url, data, timeout):
    """urlopen with a HARD wall-clock cap.

    A socket-level timeout does not cover DNS resolution (getaddrinfo) or a
    peer that never sends bytes; a single such stall left a job "running"
    forever and blocked the global lock. This abandons the request after
    `timeout` even if the underlying call never returns. The orphaned daemon
    thread is harmless (dies with the process)."""
    box = {}

    def _worker():
        try:
            box["resp"] = urllib.request.urlopen(url, data, timeout=timeout)
        except Exception as e:
            box["err"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout + 5)
    if "resp" in box:
        return box["resp"]
    if "err" in box:
        raise box["err"]
    raise TimeoutError(f"urlopen hard timeout after {timeout}s")

def comfy_ok():
    try:
        http_json(COMFY_URL + "/system_stats", timeout=5)
        return True, "ok"
    except Exception as e:
        return False, str(e)

def comfy_status_detail():
    """Return (comfy_ok, control_ok, detail) for the detector UI."""
    ok, msg = comfy_ok()
    control_ok = False
    try:
        http_json(CONTROL_URL + "/status", timeout=5)
        control_ok = True
    except Exception:
        pass
    return ok, control_ok, msg

def start_comfy_remote():
    """Trigger local ComfyUI startup via the local watchdog control port, then wait."""
    try:
        http_json(CONTROL_URL + "/start", data={}, timeout=15)
    except Exception as e:
        return False, "无法连接本机守护进程：" + str(e)
    # 轮询等待 ComfyUI 就绪（最长约 90 秒）
    for _ in range(30):
        time.sleep(3)
        ok, _ = comfy_ok()
        if ok:
            return True, "ok"
    return False, "启动超时，请在本机手动启动 ComfyUI"

def get_lora_list(force=False):
    """ComfyUI lora_name enum via tunnel; cached 60s. Never blocks long."""
    if not force and time.time() - _LORA_CACHE["t"] < 60 and _LORA_CACHE["list"]:
        return _LORA_CACHE["list"]
    try:
        # 短超时：ComfyUI 忙时快速失败，用旧缓存兜底，不阻塞请求
        info = http_json(COMFY_URL + "/object_info/LoraLoaderModelOnly", timeout=3)
        raw = info["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
        out = []
        def rec(x):
            if isinstance(x, str): out.append(x)
            elif isinstance(x, (list, tuple)):
                for i in x: rec(i)
        rec(raw)
        _LORA_CACHE["list"] = out
        _LORA_CACHE["t"] = time.time()
        return out
    except Exception:
        return _LORA_CACHE["list"]

def gen_images(prompt_id, timeout=1800):
    """Poll history until done; return list of {filename, subfolder, type}."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = http_json(f"{COMFY_URL}/history/{prompt_id}", timeout=30)
        except Exception:
            h = {}
        if prompt_id in h:
            entry = h[prompt_id]
            st = entry.get("status", {})
            if st.get("completed") or st.get("status_str") == "success":
                imgs = []
                for nid, out in entry.get("outputs", {}).items():
                    for im in out.get("images", []):
                        imgs.append(im)
                return imgs
            if st.get("status_str") == "error" or st.get("error"):
                raise RuntimeError(f"ComfyUI execution error: {json.dumps(st, ensure_ascii=False)[:300]}")
        time.sleep(3)
    raise TimeoutError(f"comfyui timeout after {timeout}s")

def fetch_and_save(im, dest_dir):
    q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im.get("type", "output")})
    data = http_bytes(f"{COMFY_URL}/view?{q}", timeout=120)
    p = dest_dir / im["filename"]
    p.write_bytes(data)
    return p

def _comfy_view_url(im, preview=None):
    values = {"filename": im["filename"], "subfolder": im.get("subfolder", ""),
              "type": im.get("type", "output")}
    if preview:
        values["preview"] = preview
    return f"{COMFY_URL}/view?{urllib.parse.urlencode(values)}"

def fetch_preview_and_save(im, dest):
    """Fetch a compact ComfyUI WebP first, then cap decode dimensions."""
    data = http_bytes(_comfy_view_url(im, preview="webp;55"), timeout=120)
    dest = pathlib.Path(dest)
    try:
        from PIL import Image
        tmp = dest.with_suffix(".tmp.webp")
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((1280, 1280))
            image.save(tmp, "WEBP", quality=72, method=4)
        tmp.replace(dest)
    except ImportError:
        dest.write_bytes(data)
    return dest

def _archive_lock(job_id, filename):
    key = (job_id, filename)
    with _archive_locks_guard:
        return _archive_locks.setdefault(key, threading.Lock())

def ensure_local_original(job, image):
    """Return a durable original, fetching it once when not archived yet."""
    dest = JOBS_DIR / job["id"] / image["file"]
    if dest.exists():
        image["archive_status"] = "ready"
        image["size"] = dest.stat().st_size
        return dest
    with _archive_lock(job["id"], image["file"]):
        if dest.exists():
            image["archive_status"] = "ready"
            image["size"] = dest.stat().st_size
            return dest
        source = {"filename": image["comfy_filename"],
                  "subfolder": image.get("comfy_subfolder", ""),
                  "type": image.get("comfy_type", "output")}
        image["archive_status"] = "downloading"
        data = http_bytes(_comfy_view_url(source), timeout=300)
        part = dest.with_suffix(dest.suffix + ".part")
        part.write_bytes(data)
        part.replace(dest)
        image["size"] = dest.stat().st_size
        image["archive_status"] = "ready"
        return dest

def archive_local_originals(job):
    """Archive full PNGs after previews are visible; never change job success."""
    job["archive_status"] = "running"
    for image in job.get("images") or []:
        if image.get("remote"):
            continue
        try:
            ensure_local_original(job, image)
        except Exception as error:
            image["archive_status"] = "error"
            image["archive_error"] = str(error)[:300]
        with _lock_jobs:
            save_jobs()
    job["archive_status"] = "done" if all(
        image.get("remote") or image.get("archive_status") == "ready"
        for image in job.get("images") or []) else "partial"
    with _lock_jobs:
        save_jobs()

def existing_job_for_request(client_request_id, generation_backend):
    """Return a previously accepted job for an idempotent browser submit."""
    if not client_request_id:
        return None
    with _lock_jobs:
        return next((j for j in _jobs.values()
                     if j.get("client_request_id") == client_request_id
                     and j.get("generation_backend", "cloud") == generation_backend), None)

def substitute(template_text, mapping):
    return re.sub(r"\{\{[A-Z0-9_]+\}\}", lambda m: str(mapping.get(m.group(0), m.group(0))), template_text)

def subst_obj(obj, mapping):
    """Recursively replace placeholders while preserving numeric types."""
    if isinstance(obj, str):
        # A field that is exactly one placeholder (width, seed, batch, HD)
        # must retain the int/float type required by the live ComfyUI schema.
        if obj in mapping:
            return mapping[obj]
        return re.sub(r"\{\{[A-Z0-9_]+\}\}", lambda m: str(mapping.get(m.group(0), m.group(0))), obj)
    if isinstance(obj, list):
        return [subst_obj(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: subst_obj(v, mapping) for k, v in obj.items()}
    return obj

def build_api(workflow, prompt, width, height, batch, hd, seed, loras=None, trigger=None, translate=True, negative_prompt="", prefix=None):
    w = WORKFLOWS[workflow]
    tname = w["template"]
    if not translate:
        nt = tname.replace(".json", "_notrans.json")
        if (TPL_DIR / nt).exists():
            tname = nt
    tpl = json.loads((TPL_DIR / tname).read_text(encoding="utf-8"))
    mapping = {
        "{{PROMPT}}": prompt,
        "{{PROMPT_FULL}}": prepend_trigger_once(prompt, trigger),
        "{{NEGATIVE}}": negative_prompt,
        "{{WIDTH}}": int(width), "{{HEIGHT}}": int(height), "{{BATCH}}": int(batch),
        "{{HD}}": int(hd), "{{SEED}}": int(seed),
        "{{PREFIX}}": prefix or f"comfy_panel/{workflow}/{int(time.time() * 1000)}",
    }
    for l in w.get("loras", []):
        mapping["{{" + l["key"] + "}}"] = (loras or {}).get(l["key"], l["default"])
    if w.get("trigger_default"):
        mapping["{{TRIGGER}}"] = trigger if trigger is not None else w["trigger_default"]
    api = subst_obj(tpl, mapping)
    if w["size_mode"] == "resize" and (int(width) > 0 and int(height) > 0):
        # node id layout per workflow: (switch_id, save_id)
        layout = {"qwen2509": ("19", "11"), "qwen2511": ("20", "21"),
                  "anima01": ("19", "11"), "anima02": ("19", "11"),
                  "anima03": ("19", "11"), "anima04": ("19", "11")}
        switch_id, save_id = layout.get(workflow, ("19", "11"))
        api["500"] = {"class_type": "ImageScale", "inputs": {
            "image": [switch_id, 0], "upscale_method": "lanczos",
            "width": int(width), "height": int(height), "crop": "disabled"}}
        api[save_id]["inputs"]["images"] = ["500", 0]
    return api

def submit_job(payload):
    try:
        r = http_json(COMFY_URL + "/prompt", payload, timeout=120)
        if "error" in r:
            raise RuntimeError(f"ComfyUI rejected: {json.dumps(r['error'], ensure_ascii=False)[:400]}")
        if r.get("node_errors"):
            raise RuntimeError(f"node errors: {json.dumps(r['node_errors'], ensure_ascii=False)[:400]}")
        return r["prompt_id"]
    except Exception as e:
        raise RuntimeError(f"submit failed: {e}")

# ---------- RunningHub 适配层 ----------
def rh_submit(workflow_id, node_info_list, instance_type="default", use_personal_queue="false"):
    """Submit a RunningHub task. Retry only transient/busy responses.

    Bounded by a hard wall-clock deadline so a stuck DNS/socket can never
    leave a job "running" forever and hold the global lock."""
    url = f"{RH_BASE}/run/workflow/{workflow_id}"
    body = {
        "addMetadata": False,
        "nodeInfoList": node_info_list,
        "instanceType": instance_type,
        "usePersonalQueue": use_personal_queue,
    }
    deadline = time.time() + RH_SUBMIT_HARD_TIMEOUT
    last = None
    for attempt in range(3):
        if time.time() >= deadline:
            break
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {RH_KEY}"},
                                     method="POST")
        per = min(RH_TIMEOUT_SUBMIT, max(5, deadline - time.time()))
        try:
            with _urlopen_bounded(req, None, per) as resp:
                raw = resp.read().decode(errors="replace")
                r = json.loads(raw)
        except Exception as e:
            last = f"transport: {e}"
            if attempt < 2 and time.time() < deadline:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"RH submit failed after {attempt + 1} attempt(s): {last}")
        status = str(r.get("status") or "").upper()
        task_id = r.get("taskId")
        # RunningHub may acknowledge a valid submission as QUEUED before a
        # worker changes it to RUNNING. A taskId plus either state means the
        # task was accepted. Never retry QUEUED: that would create duplicates.
        if task_id and status in ("QUEUED", "RUNNING"):
            return task_id
        # Preserve the real response; the previous version produced a blank
        # `RH submit error:` when RunningHub returned a different schema.
        last = json.dumps(r, ensure_ascii=False)[:600]
        code = str(r.get("errorCode") or r.get("code") or "").upper()
        msg = str(r.get("errorMessage") or r.get("message") or "").lower()
        transient = any(x in (code + " " + msg) for x in ("BUSY", "RATE", "TOO MANY", "TEMPORARY", "TIMEOUT"))
        if transient and attempt < 2 and time.time() < deadline:
            time.sleep(2 * (attempt + 1))
            continue
        raise RuntimeError(f"RH submit rejected: {last}")
    raise RuntimeError(f"RH submit failed: hard deadline exceeded: {last}")

def rh_submit_ai_app(app_id, node_info_list):
    """Submit a trusted RunningHub AI App through the V2 task API."""
    url = f"{RH_BASE}/run/ai-app/{app_id}"
    body = {"nodeInfoList": node_info_list}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {RH_KEY}"},
                                 method="POST")
    with _urlopen_bounded(req, None, RH_TIMEOUT_SUBMIT) as resp:
        result = json.loads(resp.read().decode(errors="replace"))
    status = str(result.get("status") or "").upper()
    task_id = result.get("taskId")
    if task_id and status in ("QUEUED", "RUNNING"):
        return task_id
    raise RuntimeError("RH AI App submit rejected: " + json.dumps(result, ensure_ascii=False)[:600])

def rh_query(task_id):
    """查询 RunningHub 任务状态，返回 (status, results)"""
    url = f"{RH_BASE}/query"
    body = {"taskId": task_id}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {RH_KEY}"},
                                 method="POST")
    try:
        with _urlopen_bounded(req, None, RH_TIMEOUT_QUERY) as resp:
            r = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"RH query failed: {e}")
    status = r.get("status", "")
    if status == "FAILED":
        raise RuntimeError(f"RH task failed: {r.get('errorCode')} {r.get('errorMessage')}")
    return status, r.get("results") or []

def rh_build_node_info(job):
    """Build RunningHub nodeInfoList for anima02.
    - Prompt: verbatim (no translation). Trigger word prepended so the LoRA fires.
    - LoRA: user-selected names + strengths from config (only when non-empty).
    - Size / batch / HD / seed as the user set them."""
    w = WORKFLOWS[job["workflow"]]
    mapping = w.get("rh_node_map", {})
    loras = job.get("loras") or {}

    node_list = []
    def set_field(key, value):
        m = mapping.get(key)
        if not m:
            return
        node_list.append({"nodeId": m["node"], "fieldName": m["field"], "fieldValue": value})

    # 1. Positive/negative prompts are sent verbatim. The fixed style trigger
    # is normalized to exactly one occurrence even when a manual prompt
    # already contains it.
    trigger = job.get("trigger")
    prompt = prepend_trigger_once(job["prompt"], trigger)
    set_field("prompt", prompt)
    set_field("negative", job.get("negative_prompt", ""))

    # 2. Size / batch / HD
    set_field("width", int(job["width"]))
    set_field("height", int(job["height"]))
    set_field("batch", int(job["batch"]))
    set_field("hd", int(job.get("hd", 0)))

    # 3. Seed: only if a fixed non-zero seed was provided
    seed = int(job.get("seed") or 0)
    if seed:
        set_field("seed", seed)

    # 4. LoRA: user-selected name + strength from config (only when non-empty)
    conf_loras = {l["key"]: l for l in w.get("loras", [])}
    for key, name_field, strength_field in (("LORA1", "lora1_name", "lora1_strength"),
                                            ("LORA2", "lora2_name", "lora2_strength")):
        name = (loras or {}).get(key)
        if not name:
            continue
        set_field(name_field, name)
        conf = conf_loras.get(key)
        if conf:
            strength = (job.get("lora_strengths") or {}).get(key, conf.get("strength", 0.7))
            set_field(strength_field, float(strength))

    return node_list

def prepend_trigger_once(prompt, trigger):
    prompt = str(prompt or "").strip(); trigger = str(trigger or "").strip()
    if not trigger: return prompt
    # Trigger tokens contain underscores, so regular \b boundaries are not
    # sufficient. Remove standalone copies, tidy separators, prepend once.
    pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(trigger) + r"(?![A-Za-z0-9_])", re.I)
    prompt = pat.sub("", prompt)
    prompt = re.sub(r"(?:\s*,\s*){2,}", ", ", prompt).strip(" ,\n\t")
    return f"{trigger}, {prompt}" if prompt else trigger

def _rh_wait_task(job, task_id, deadline, progress_base=0, progress_span=100):
    while time.time() < deadline:
        status, results = rh_query(task_id)
        job["provider_status"] = status or "RUNNING"
        fraction = RH_STAGE_PROGRESS.get(str(status or "RUNNING").upper(), 0.10)
        job["progress_pct"] = round(min(99, progress_base + progress_span * fraction))
        if status == "SUCCESS":
            if results:
                return results
            job["provider_status"] = "FINALIZING"
            time.sleep(4)
            continue
        time.sleep(8)
    raise RuntimeError("RH task timeout")

def _rh_results_to_images(results, task_id, stage_id=None, stage_label=None):
    images = []
    for idx, im in enumerate(results, 1):
        url = im.get("url") or im.get("fileUrl") or ""
        if not url:
            continue
        images.append({
            "url": url,
            "preview_url": url + ("&" if "?" in url else "?") + "imageMogr2/thumbnail/640x640",
            "remote": True,
            "file": pathlib.PurePosixPath(urllib.parse.urlparse(url).path).name or f"rh_{task_id}_{idx}.png",
            "size": None,
            "stage_id": stage_id,
            "stage_label": stage_label,
        })
    return images

def image_content_type(data, filename=""):
    """Return an allowed image type from magic bytes, never extension only."""
    if data[:8] == bytes((137, 80, 78, 71, 13, 10, 26, 10)):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None

def rh_build_ai_app_node_info(job, w):
    """Build only public editable fields from the trusted server config."""
    nodes = []
    for key, mapping in (w.get("rh_media") or {}).items():
        value = (job.get("media") or {}).get(key)
        if value:
            nodes.append({"nodeId": str(mapping["node"]), "fieldName": mapping["field"], "fieldValue": value})
    for key, mapping in (w.get("rh_params") or {}).items():
        value = (job.get("params") or {}).get(key)
        if value is not None:
            nodes.append({"nodeId": str(mapping["node"]), "fieldName": mapping["field"], "fieldValue": str(value)})
    return nodes

def rh_run_ai_app(job, w):
    app_id = w.get("rh_ai_app_id")
    if not app_id:
        raise RuntimeError("AI App has no trusted app id")
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit_ai_app(app_id, rh_build_ai_app_node_info(job, w))
    job["rh_task_id"] = task_id
    job["provider_started"] = time.time()
    job["progress_pct"] = 5
    results = _rh_wait_task(job, task_id, time.time() + 1800, 12, 88)
    job["provider_finished"] = time.time()
    images = _rh_results_to_images(results, task_id)
    if not images:
        raise RuntimeError("RH AI App succeeded but returned no downloadable result")
    job["images"] = images
    job["provider_status"] = "DONE"
    job["progress_pct"] = 100
    job["download_finished"] = time.time()
    return images

def rh_run_sketch_sequence(job, jobdir, w):
    stages = SKETCH_SEQUENCE_STAGES[job["sequence_mode"]]
    sequence_seed = int(job.get("seed") or secrets.randbelow(2**31 - 1) + 1)
    job["sequence_seed"] = sequence_seed
    job["rh_task_ids"] = []
    job["stage_status"] = []
    all_images = []
    deadline = time.time() + 1800
    for stage_index, (stage_id, stage_label, stage_prompt) in enumerate(stages):
        stage_job = dict(job)
        stage_job["seed"] = sequence_seed
        stage_job["batch"] = 1
        stage_job["hd"] = job.get("hd", 0) if stage_id == "colored" else 0
        stage_job["prompt"] = f"{job['prompt']}, {stage_prompt}, same exact character, same pose, same camera, same composition across the whole process series"
        stage_job["trigger"] = STYLE_PRESETS["sketch"]["trigger"]
        node_list = rh_build_node_info(stage_job)
        task_id = rh_submit(w["rh_workflow_id"], node_list)
        job["rh_task_ids"].append(task_id)
        job["rh_task_id"] = task_id
        job["stage_status"].append({"stage_id": stage_id, "stage_label": stage_label, "status": "RUNNING", "task_id": task_id})
        job["provider_status"] = stage_label
        results = _rh_wait_task(job, task_id, deadline, int(stage_index / len(stages) * 100), max(8, int(100 / len(stages))))
        job["stage_status"][-1]["status"] = "DONE"
        all_images.extend(_rh_results_to_images(results, task_id, stage_id, stage_label))
    if not all_images:
        raise RuntimeError("RH sketch sequence returned no images")
    job["images"] = all_images
    job["provider_status"] = "DONE"
    job["progress_pct"] = 100
    job["provider_finished"] = time.time()
    return all_images

def rh_run(job, jobdir, w):
    """RunningHub 后端执行：提交→轮询→下载"""
    wfid = w.get("rh_workflow_id")
    if not wfid:
        raise RuntimeError("workflow has no rh_workflow_id")
    node_list = rh_build_node_info(job)
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit(wfid, node_list)
    job["rh_task_id"] = task_id
    job["provider_started"] = time.time()
    job["progress"] = 0
    job["progress_pct"] = 5
    images = []
    deadline = time.time() + 1800
    while time.time() < deadline:
        results = _rh_wait_task(job, task_id, deadline, 12, 88)
        if results:
            if not job.get("provider_finished"):
                job["provider_finished"] = time.time()
            job["provider_status"] = "DONE"
            job["progress_pct"] = 100
            # RunningHub result URLs are already durable HTTPS objects. Mark
            # the job done immediately instead of proxy-downloading multi-MB
            # files through this small relay server. The old synchronous
            # download saturated its network for 30–1000s, slowed /api/jobs,
            # held the global lock and caused false 409/timeout/preview errors.
            images = _rh_results_to_images(results, task_id)
            if not images:
                raise RuntimeError("RH SUCCESS but no downloadable result URL was returned")
            job["images"] = images
            job["download_started"] = None
            job["download_finished"] = time.time()
            return images
    raise RuntimeError("RH task timeout")

def local_run_image(job, jobdir, w, prompt=None, negative_prompt=None,
                    batch_size=None, hd=None, seed=None, stage_id=None,
                    stage_label=None, stage_index=0, stage_total=1):
    """Run one native-batch job on the user's local ComfyUI via COMFY_URL.

    On the relay COMFY_URL is 127.0.0.1:8199, the existing reverse tunnel to
    the user's 127.0.0.1:8188. No image-provider moderation is involved.
    """
    jobdir = pathlib.Path(jobdir)
    jobdir.mkdir(parents=True, exist_ok=True)
    api = build_api(
        job["workflow"], prompt if prompt is not None else job["prompt"],
        job["width"], job["height"],
        batch=int(job["batch"]) if batch_size is None else int(batch_size),
        hd=job.get("hd", 0) if hd is None else int(hd),
        seed=int(job["seed"]) if seed is None else int(seed),
        loras={k: local_lora_name(v) for k, v in (job.get("loras") or {}).items()},
        trigger=job.get("trigger"), translate=False,
        negative_prompt=job.get("negative_prompt", "") if negative_prompt is None else negative_prompt,
        prefix=f"comfy_panel/local/{job['id']}/{stage_id or 'image'}",
    )
    pid = submit_job({"prompt": api})
    job["prompt_ids"].append(pid)
    job["comfy_prompt_id"] = pid
    job["provider_status"] = stage_label or "LOCAL_RUNNING"
    imgs = _wait_progress(job, pid, stage_index, stage_total)
    images = []
    job["provider_status"] = "RESULT_TRANSFERRING"
    job["transfer_index"] = 0
    job["transfer_total"] = len(imgs)
    job["transfer_started"] = time.time()
    span = 100 / max(1, stage_total)
    base = stage_index * span
    for index, im in enumerate(imgs, 1):
        job["provider_status"] = "RESULT_DOWNLOADING"
        job["transfer_index"] = index
        job["progress_pct"] = round(min(99, base + span * (0.90 + 0.09 * ((index - 1) / max(1, len(imgs))))))
        preview_file = f"preview_{pathlib.Path(im['filename']).stem}.webp"
        preview_path = fetch_preview_and_save(im, jobdir / preview_file)
        images.append({
            "url": f"/api/image/{job['id']}/{im['filename']}",
            "preview_url": f"/api/local-preview/{job['id']}/{preview_file}",
            "file": im["filename"], "size": None, "remote": False,
            "preview_file": preview_file, "preview_size": preview_path.stat().st_size,
            "comfy_filename": im["filename"], "comfy_subfolder": im.get("subfolder", ""),
            "comfy_type": im.get("type", "output"), "archive_status": "pending",
            "stage_id": stage_id, "stage_label": stage_label,
        })
        job["progress_pct"] = round(min(99, base + span * (0.90 + 0.09 * (index / max(1, len(imgs))))))
    if not images:
        raise RuntimeError("local ComfyUI returned no images")
    job["transfer_finished"] = time.time()
    job["progress_pct"] = round(min(99, base + span))
    if stage_id is None:
        job["images"] = images
        job["provider_status"] = "LOCAL_PREVIEW_READY"
    return images

def local_run_sketch_sequence(job, jobdir, w):
    stages = SKETCH_SEQUENCE_STAGES[job["sequence_mode"]]
    sequence_seed = int(job["seed"])
    job["sequence_seed"] = sequence_seed
    job["stage_status"] = []
    all_images = []
    for stage_index, (stage_id, stage_label, stage_prompt) in enumerate(stages):
        job["stage_status"].append({"stage_id": stage_id, "stage_label": stage_label, "status": "RUNNING"})
        prompt = f"{job['prompt']}, {stage_prompt}, same exact character, same pose, same camera, same composition across the whole process series"
        images = local_run_image(
            job, jobdir, w, prompt=prompt, batch_size=1,
            hd=job.get("hd", 0) if stage_id == "colored" else 0,
            seed=sequence_seed, stage_id=stage_id, stage_label=stage_label,
            stage_index=stage_index, stage_total=len(stages),
        )
        all_images.extend(images)
        job["stage_status"][-1]["status"] = "DONE"
    job["images"] = all_images
    job["provider_status"] = "LOCAL_DONE"
    return all_images


def rh_upload_file(data, filename, ctype="application/octet-stream", timeout=120):
    """Upload a binary (image/video) to RunningHub. Returns the RH fileName
    (relative path) to be placed into LoadImage/LoadVideo fieldValue."""
    boundary = "----rh" + uuid.uuid4().hex
    def _field(name, val):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{val}\r\n").encode()
    def _file(name, fname, ctype_):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{fname}\"\r\nContent-Type: {ctype_}\r\n\r\n").encode()
    body = b"".join([
        _field("apiKey", RH_KEY),
        _field("fileType", "input"),
        _file("file", filename, ctype),
        data, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {RH_KEY}",
    }
    req = urllib.request.Request("https://www.runninghub.cn/task/openapi/upload",
                                 data=body, headers=headers)
    with _urlopen_bounded(req, None, timeout) as r:
        resp = json.loads(r.read().decode())
    if resp.get("code") != 0:
        raise RuntimeError(f"RH upload failed: {resp.get('code')} {resp.get('msg')}")
    fname = (resp.get("data") or {}).get("fileName")
    if not fname:
        raise RuntimeError("RH upload returned no fileName")
    return fname


def rh_build_video_node_info(job, w):
    """Build RunningHub nodeInfoList for a video workflow.

    Job fields: prompt, negative_prompt, media = {key: fileName}, params = {key: value}.
    Mapping comes from the workflow config: w["rh_media"] (key->{node,field,type,label})
    and w["rh_params"] (key->{node,field,type,label}). Prompt/negative also declared
    as rh_params entries so the generic loop covers everything.
    """
    node_list = []
    def set_field(key, value):
        m = (w.get("rh_params") or {}).get(key)
        if not m:
            return
        node_list.append({"nodeId": str(m["node"]), "fieldName": m["field"], "fieldValue": value})
    media_map = w.get("rh_media") or {}
    for key, m in media_map.items():
        fname = (job.get("media") or {}).get(key)
        if not fname:
            continue
        node_list.append({"nodeId": str(m["node"]), "fieldName": m["field"], "fieldValue": fname})
    for key, m in (w.get("rh_params") or {}).items():
        if key == "prompt":
            val = job.get("prompt", "")
        elif key == "negative":
            val = job.get("negative_prompt", "")
        else:
            val = (job.get("params") or {}).get(key)
        if val is None or val == "":
            continue
        vtype = m.get("vtype") or m.get("type")
        if vtype == "int":
            try: val = int(float(val))
            except Exception: continue
        elif vtype == "float":
            try: val = float(val)
            except Exception: continue
        else:
            val = str(val)
        node_list.append({"nodeId": str(m["node"]), "fieldName": m["field"], "fieldValue": val})
    return node_list


def rh_run_video(job, w):
    """RunningHub 视频工作流：上传已就绪的 media fileName 已存于 job["media"]，
    直接提交→轮询→结果 URL（mp4/png）透传保存。"""
    wfid = w.get("rh_workflow_id")
    if not wfid:
        raise RuntimeError("video workflow has no rh_workflow_id")
    node_list = rh_build_video_node_info(job, w)
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit(wfid, node_list)
    job["rh_task_id"] = task_id
    job["provider_started"] = time.time()
    job["progress_pct"] = 5
    images = []
    deadline = time.time() + 2400
    while time.time() < deadline:
        results = _rh_wait_task(job, task_id, deadline, 12, 88)
        if results:
            job["provider_finished"] = time.time()
            job["provider_status"] = "DONE"
            job["progress_pct"] = 100
            images = _rh_results_to_images(results, task_id)
            if not images:
                raise RuntimeError("RH SUCCESS but no downloadable result URL was returned")
            job["images"] = images
            job["download_finished"] = time.time()
            return images
    raise RuntimeError("RH video task timeout")


def run_job(job):
    """Execute job: for native batch one submission; for sequential, N submissions."""
    w = WORKFLOWS[job["workflow"]]
    t0 = time.time()
    jobdir = JOBS_DIR / job["id"]
    jobdir.mkdir(parents=True, exist_ok=True)
    try:
        generation_backend = job.get("generation_backend", "cloud")
        # RunningHub cloud route
        if generation_backend == "cloud":
            if w.get("kind") == "ai_app":
                rh_run_ai_app(job, w)
            elif w.get("kind") == "video":
                rh_run_video(job, w)
            elif job.get("sequence_mode") in SKETCH_SEQUENCE_STAGES:
                rh_run_sketch_sequence(job, jobdir, w)
            else:
                rh_run(job, jobdir, w)
            job["status"] = "done"
            job["progress_pct"] = 100
        elif generation_backend == "local":
            if job.get("sequence_mode") in SKETCH_SEQUENCE_STAGES:
                local_run_sketch_sequence(job, jobdir, w)
            else:
                local_run_image(job, jobdir, w)
            job["status"] = "done"
            job["progress_pct"] = 100
            job["provider_status"] = "LOCAL_DONE"
        else:
            raise RuntimeError("unknown generation backend")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:500]
    job["elapsed"] = round(time.time() - t0, 1)
    with _lock_jobs:
        save_jobs()
    if job.get("status") == "done" and job.get("generation_backend") == "local":
        threading.Thread(target=archive_local_originals, args=(job,), daemon=True).start()

def _wait_progress(job, pid, img_index, total, timeout=1800):
    """Poll ComfyUI history; reserve the final 10% for result transfer."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = http_json(f"{COMFY_URL}/history/{pid}", timeout=30)
        except Exception:
            h = {}
        if pid in h:
            entry = h[pid]
            st = entry.get("status", {})
            if st.get("completed") or st.get("status_str") == "success":
                imgs = []
                for nid, out in entry.get("outputs", {}).items():
                    for im in out.get("images", []):
                        imgs.append(im)
                if imgs:
                    job["progress_pct"] = round(min(99, ((img_index + 0.90) / max(1, total)) * 100))
                    return imgs
            if st.get("status_str") == "error" or st.get("error"):
                raise RuntimeError(f"ComfyUI execution error: {json.dumps(st, ensure_ascii=False)[:300]}")
        v, m = _progress.get(pid, (0, 1))
        pct = (img_index + 0.88 * (v / m if m else 0)) / max(1, total) * 100
        job["progress_pct"] = round(min(pct, 99))
        time.sleep(2)
    raise TimeoutError(f"comfyui timeout after {timeout}s")

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items(): self.send_header(k, v)
        self.end_headers()
        if body: self.wfile.write(body)

    def _send_static(self, fp, ctype):
        """Serve text assets with validator caching and bounded gzip."""
        raw = fp.read_bytes()
        etag = '"' + hashlib.sha256(raw).hexdigest()[:24] + '"'
        cache = "no-cache, must-revalidate" if fp.suffix == ".html" else "public, max-age=3600, must-revalidate"
        if self.headers.get("If-None-Match") == etag:
            self.send_response(http.HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            return
        body = raw
        response_headers = {"ETag": etag, "Cache-Control": cache, "Vary": "Accept-Encoding"}
        accepted = self.headers.get("Accept-Encoding", "").lower()
        if "gzip" in accepted and len(raw) >= 1024 and ctype.startswith(("text/", "application/javascript")):
            body = gzip.compress(raw, compresslevel=6, mtime=0)
            response_headers["Content-Encoding"] = "gzip"
        self._send(200, body, ctype, response_headers)

    def _auth(self):
        # 令牌鉴权已取消（用户要求 8189 直接免登录使用）
        return True

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode())

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            ok, msg = comfy_ok()
            self._send(200, json.dumps({"ok": ok, "comfy": msg, "local_comfy_ok": ok,
                                        "running_cloud": self._running_job_id("cloud"),
                                        "running_local": self._running_job_id("local")}).encode())
        elif path == "/api/comfy/status":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            ok, control_ok, detail = comfy_status_detail()
            self._send(200, json.dumps({"comfy_ok": ok, "control_ok": control_ok, "detail": detail}).encode())
        elif path == "/api/workflows":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            lst = [{"id": w["id"], "name": w["name"], "desc": w["desc"], "speed": w.get("speed", "—"), "ref": w.get("ref", "—"),
                    "prompt_default": w.get("prompt_default", ""), "size_mode": w.get("size_mode", "native"), "size_presets": w.get("size_presets", []),
                    "batch_max": w.get("batch_max", 1), "hd": w.get("hd", []), "needs_ollama": w.get("needs_ollama", False),
                    "loras": w.get("loras", []), "trigger_default": w.get("trigger_default"),
                    "translate_default": w.get("translate_default", True),
                    "kind": w.get("kind", "image"), "rh_media": w.get("rh_media", {}),
                    "rh_params": w.get("rh_params", {}), "params_defaults": w.get("params_defaults", {}),
                    "prompt_placeholder": w.get("prompt_placeholder"), "prompt_hint": w.get("prompt_hint")} for w in CONFIG["workflows"]]
            self._send(200, json.dumps(lst, ensure_ascii=False).encode())
        elif path == "/api/loras":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            self._send(200, json.dumps({"loras": get_lora_list()}).encode())
        elif path == "/api/favorites":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            with _lock_jobs:
                items = sorted(_favorites.values(), key=lambda x: x.get("created", 0), reverse=True)
            self._send(200, json.dumps(items, ensure_ascii=False).encode())
        elif path.startswith("/api/favorite-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            fid = path.split("/api/favorite-preview/", 1)[1]
            with _lock_jobs: fav = _favorites.get(fid)
            if not fav: return self._send(404, b'{"error":"favorite not found"}')
            src = pathlib.Path(fav.get("image_path", ""))
            if not src.exists(): return self._send(404, b'{"error":"favorite image missing"}')
            preview = FAVORITES_DIR / f"{fid}_preview.jpg"
            if not preview.exists() or preview.stat().st_mtime < src.stat().st_mtime:
                from PIL import Image
                tmp = preview.with_suffix(".tmp.jpg")
                with Image.open(src) as im:
                    im = im.convert("RGB"); im.thumbnail((640, 640))
                    im.save(tmp, "JPEG", quality=72, optimize=True, progressive=True)
                tmp.replace(preview)
            self._send(200, preview.read_bytes(), "image/jpeg", {"Cache-Control": "private, max-age=86400"})
        elif path.startswith("/api/favorite-image/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            fid = path.split("/api/favorite-image/", 1)[1]
            with _lock_jobs: fav = _favorites.get(fid)
            if not fav: return self._send(404, b'{"error":"favorite not found"}')
            p = pathlib.Path(fav.get("image_path", ""))
            if not p.exists(): return self._send(404, b'{"error":"favorite image missing"}')
            data = p.read_bytes()
            ctype = fav.get("favorite_media_type") or image_content_type(data, p.name) or "application/octet-stream"
            self._send(200, data, ctype, {"Cache-Control": "private, max-age=86400"})
        elif path.startswith("/api/job/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            jid = path.split("/api/job/", 1)[1]
            with _lock_jobs:
                src = _jobs.get(jid)
                if not src:
                    return self._send(404, b'{"error":"job not found"}')
                allowed = (
                    "id", "workflow", "status", "provider_status", "rh_task_id",
                    "progress_pct", "error", "elapsed", "created", "wf_name",
                    "width", "height", "batch", "hd", "images",
                    "submit_started", "provider_started", "provider_finished",
                    "download_started", "download_finished", "selection_snapshot",
                    "prompt", "negative_prompt", "prompt_mode", "seed", "seed_mode", "style_id", "mode",
                    "sequence_mode", "sequence_seed", "rh_task_ids", "stage_status", "generation_backend",
                    "media", "params",
                    "client_request_id", "comfy_prompt_id", "prompt_ids",
                    "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                )
                j = {k: src.get(k) for k in allowed}
            self._send(200, json.dumps(j, ensure_ascii=False).encode())
        elif path == "/api/jobs":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            with _lock_jobs:
                # Lightweight copies: prompts can be many KB and are not used by
                # history/status UI. Omitting them cuts /api/jobs from ~60KB to
                # a few KB and prevents slow mobile polling/timeouts.
                items = []
                for src in sorted(_jobs.values(), key=lambda j: j.get("created", 0), reverse=True)[:12]:
                    allowed = (
                        "id", "workflow", "status", "provider_status", "rh_task_id",
                        "progress_pct", "error", "elapsed", "created", "wf_name",
                        "width", "height", "batch", "hd", "images",
                        "submit_started", "provider_started", "provider_finished",
                        "download_started", "download_finished", "selection_snapshot",
                        "style_id", "mode", "seed", "seed_mode", "prompt_mode",
                        "sequence_mode", "sequence_seed", "rh_task_ids", "stage_status", "generation_backend",
                        "client_request_id", "comfy_prompt_id",
                        "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                    )
                    j = {k: src.get(k) for k in allowed}
                    items.append(j)
            self._send(200, json.dumps(items, ensure_ascii=False).encode())
        elif path.startswith("/api/local-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/local-preview/", 1)[1]
                jobid, fname = rest.split("/", 1)
                p = (JOBS_DIR / jobid / fname).resolve()
                if not str(p).startswith(str((JOBS_DIR / jobid).resolve())):
                    return self._send(403, b'{"error":"bad path"}')
                data = p.read_bytes()
                self._send(200, data, "image/webp", {"Cache-Control": "private, max-age=86400"})
            except FileNotFoundError:
                self._send(404, b'{"error":"preview not found"}')
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as error:
                self._send(500, json.dumps({"error": str(error)[:200]}).encode())
        elif path.startswith("/api/preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/preview/", 1)[1]
                jobid, fname = rest.split("/", 1)
                src = (JOBS_DIR / jobid / fname).resolve()
                jobroot = (JOBS_DIR / jobid).resolve()
                if not str(src).startswith(str(jobroot)):
                    return self._send(403, b'{"error":"bad path"}')
                if not src.exists():
                    return self._send(404, b'{"error":"not found"}')
                preview = jobroot / ("preview_" + pathlib.Path(fname).stem + ".jpg")
                if not preview.exists() or preview.stat().st_mtime < src.stat().st_mtime:
                    # Pillow is optional on the server; import only for previews.
                    from PIL import Image
                    tmp = preview.with_suffix(".tmp.jpg")
                    with Image.open(src) as im:
                        im = im.convert("RGB")
                        im.thumbnail((640, 640))
                        im.save(tmp, "JPEG", quality=72, optimize=True, progressive=True)
                    tmp.replace(preview)
                data = preview.read_bytes()
                self._send(200, data, "image/jpeg", {"Cache-Control": "private, max-age=86400"})
            except ImportError:
                self._send(501, b'{"error":"preview backend unavailable"}')
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)[:200]}).encode())
        elif path.startswith("/api/rh-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            # On-demand thumbnail for remote RunningHub result. It is NOT part
            # of job completion and never holds the generation lock.
            try:
                rest = path.split("/api/rh-preview/", 1)[1]
                jobid, idx_s = rest.split("/", 1)
                idx = int(idx_s)
                with _lock_jobs:
                    job = _jobs.get(jobid)
                    images = list((job or {}).get("images") or [])
                if idx < 0 or idx >= len(images) or not images[idx].get("remote"):
                    return self._send(404, b'{"error":"remote image not found"}')
                jobroot = (JOBS_DIR / jobid).resolve(); jobroot.mkdir(parents=True, exist_ok=True)
                preview = jobroot / f"remote_preview_{idx}.jpg"
                if not preview.exists():
                    src = jobroot / f"remote_source_{idx}.png"
                    # Thumbnail generation is opportunistic and must never tie
                    # up the panel for minutes. Give the CDN 12s; if it is slow,
                    # the endpoint fails quickly and the UI still offers the
                    # direct original download URL.
                    download_file_resilient(images[idx]["url"], src, timeout=12)
                    from PIL import Image
                    tmp = preview.with_suffix(".tmp.jpg")
                    with Image.open(src) as im:
                        im = im.convert("RGB"); im.thumbnail((640, 640))
                        im.save(tmp, "JPEG", quality=72, optimize=True, progressive=True)
                    tmp.replace(preview)
                    src.unlink(missing_ok=True)
                data = preview.read_bytes()
                self._send(200, data, "image/jpeg", {"Cache-Control": "public, max-age=86400"})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)[:200]}).encode())
        elif path.startswith("/api/image/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/image/", 1)[1]
                jobid, fname = rest.split("/", 1)
                p = (JOBS_DIR / jobid / fname).resolve()
                if not str(p).startswith(str((JOBS_DIR / jobid).resolve())):
                    return self._send(403, b'{"error":"bad path"}')
                if not p.exists():
                    with _lock_jobs:
                        job = _jobs.get(jobid)
                        image = next((item for item in (job or {}).get("images", [])
                                      if item.get("file") == fname), None)
                    if not job or not image or image.get("remote"):
                        return self._send(404, b'{"error":"not found"}')
                    p = ensure_local_original(job, image)
                    with _lock_jobs:
                        save_jobs()
                size = p.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f'inline; filename="{fname}"')
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                # Stream instead of constructing/writing one multi-MB response.
                # Slow mobile links frequently canceled the previous all-at-once
                # write and produced BrokenPipe while history loaded many images.
                with p.open("rb") as f:
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # Browser canceled an image request (navigation/refresh). The file
                # is intact; do not attempt to write a second 404 response.
                return
            except FileNotFoundError:
                self._send(404, b'{"error":"not found"}')
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)[:200]}).encode())
        elif path == "/" or path.startswith("/static/") or path in ("/promptgen", "/original-sketch", "/original-graphic", "/realcomic", "/video"):
            if not self._auth():
                # serve shell so user can enter token; API calls still guarded
                pass
            root = BASE / "static"
            clean_pages = {"/promptgen": "promptgen.html", "/original-sketch": "original_sketch.html", "/original-graphic": "original_graphic.html", "/realcomic": "realcomic.html"}
            if path in clean_pages:
                rel = clean_pages[path]
            elif path == "/video":
                rel = "video.html"
            else:
                rel = "index.html" if path == "/" else path.split("/static/", 1)[1]
            fp = (root / rel).resolve()
            if not str(fp).startswith(str(root.resolve())) or not fp.exists():
                return self._send(404, b"not found")
            ctype = "text/html; charset=utf-8" if rel.endswith(".html") else ("application/javascript" if rel.endswith(".js") else "text/css")
            self._send_static(fp, ctype)
        else:
            self._send(404, b'{"error":"not found"}')

    def _running_job_id(self, generation_backend=None):
        with _lock_jobs:
            for j in _jobs.values():
                if j.get("status") in ("running",) and (generation_backend is None or j.get("generation_backend", "cloud") == generation_backend):
                    return j["id"]
        return None

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/realcomic-upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                body = self._read_json()
                filename = re.split(r"[\\\\/]", str(body.get("filename") or "source.png"))[-1]
                raw = base64.b64decode(body.get("data", ""), validate=True)
            except Exception:
                return self._send(400, json.dumps({"error": "图片数据无效"}, ensure_ascii=False).encode())
            if not raw:
                return self._send(400, json.dumps({"error": "请选择二次元图片"}, ensure_ascii=False).encode())
            if len(raw) > 30 * 1024 * 1024:
                return self._send(400, json.dumps({"error": "图片超过30MB限制"}, ensure_ascii=False).encode())
            ctype = image_content_type(raw, filename)
            if not ctype:
                return self._send(400, json.dumps({"error": "只支持有效的PNG、JPEG或WebP图片"}, ensure_ascii=False).encode())
            try:
                remote_name = rh_upload_file(raw, filename, ctype)
            except Exception as e:
                return self._send(502, json.dumps({"error": f"RunningHub上传失败：{str(e)[:200]}"}, ensure_ascii=False).encode())
            return self._send(200, json.dumps({"fileName": remote_name, "filename": filename, "mediaType": ctype}, ensure_ascii=False).encode())
        if path == "/api/ai-app-generate":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            wf = str(body.get("workflow") or "realcomic")
            w = WORKFLOWS.get(wf)
            if not w or w.get("kind") != "ai_app" or w.get("backend") != "runninghub":
                return self._send(400, b'{"error":"unknown AI App"}')
            media = body.get("media") or {}
            params = body.get("params") or {}
            if not isinstance(media, dict) or not isinstance(params, dict):
                return self._send(400, b'{"error":"media and params must be objects"}')
            required = [k for k, mapping in (w.get("rh_media") or {}).items() if mapping.get("required")]
            missing = [k for k in required if not media.get(k)]
            if missing:
                return self._send(400, json.dumps({"error": f"缺少必传素材：{', '.join(missing)}"}, ensure_ascii=False).encode())
            trusted_media = {k: str(media[k]) for k in (w.get("rh_media") or {}) if media.get(k)}
            defaults = w.get("params_defaults") or {}
            trusted_params = {k: str(params.get(k, defaults.get(k, "")))[:1000] for k in (w.get("rh_params") or {})}
            client_request_id = str(body.get("client_request_id") or "").strip()[:96]
            with _submit_locks["cloud"]:
                existing_job = existing_job_for_request(client_request_id, "cloud")
                if existing_job:
                    return self._send(200, json.dumps({"job_id": existing_job["id"], "existing_job": existing_job["id"], "deduplicated": True, "message": "same request already accepted"}).encode())
                active_id = self._running_job_id("cloud")
                if active_id:
                    return self._send(429, json.dumps({"error": "云端已有任务正在运行，请等待完成后再提交", "running_job": active_id}, ensure_ascii=False).encode())
                job = {"id": uuid.uuid4().hex[:12], "workflow": wf,
                       "prompt": trusted_params.get("requirements", ""), "negative_prompt": "", "prompt_mode": "manual",
                       "media": trusted_media, "params": trusted_params,
                       "width": 0, "height": 0, "batch": 1, "hd": 0, "seed": 0, "seed_mode": "random",
                       "loras": {}, "lora_strengths": {}, "trigger": None, "translate": False,
                       "status": "running", "progress": 0, "progress_pct": 0, "images": [],
                       "prompt_ids": [], "error": None, "elapsed": None, "created": time.time(), "wf_name": w["name"],
                       "submit_started": None, "provider_started": None, "provider_finished": None,
                       "download_started": None, "download_finished": None,
                       "style_id": "realcomic", "mode": "original", "generation_backend": "cloud",
                       "sequence_mode": "off", "selection_snapshot": body.get("selection_snapshot") or {},
                       "client_request_id": client_request_id, "provider_attribution": w.get("provider_attribution")}
                with _lock_jobs:
                    _jobs[job["id"]] = job
                    save_jobs()
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
                return self._send(200, json.dumps({"job_id": job["id"]}).encode())
        if path == "/api/upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            # Browser posts raw bytes: body = {filename, data_base64} JSON (small files)
            # or multipart. Use JSON base64 for simplicity and reliability.
            try:
                body = self._read_json()
                filename = str(body.get("filename", "upload.bin"))
                raw = base64.b64decode(body.get("data", ""))
            except Exception:
                return self._send(400, b'{"error":"bad json (need filename + data base64)"}')
            if not raw:
                return self._send(400, b'{"error":"empty file"}')
            if len(raw) > 60 * 1024 * 1024:
                return self._send(400, b'{"error":"file too large (>60MB)"}')
            ctype = "image/png"
            low = filename.lower()
            if low.endswith(".jpg") or low.endswith(".jpeg"): ctype = "image/jpeg"
            elif low.endswith(".webp"): ctype = "image/webp"
            elif low.endswith(".mp4"): ctype = "video/mp4"
            elif low.endswith(".mov"): ctype = "video/quicktime"
            elif low.endswith(".avi"): ctype = "video/x-msvideo"
            elif low.endswith(".mkv"): ctype = "video/x-matroska"
            elif low.endswith(".zip"): ctype = "application/zip"
            try:
                fname = rh_upload_file(raw, filename, ctype)
            except Exception as e:
                return self._send(502, json.dumps({"error": f"RH upload failed: {str(e)[:200]}"}, ensure_ascii=False).encode())
            return self._send(200, json.dumps({"fileName": fname}).encode())
        if path == "/api/video-generate":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            wf = body.get("workflow")
            if wf not in WORKFLOWS:
                return self._send(400, b'{"error":"unknown workflow"}')
            w = WORKFLOWS[wf]
            if w.get("kind") != "video" or w.get("backend") != "runninghub":
                return self._send(400, b'{"error":"not a video workflow"}')
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return self._send(400, b'{"error":"prompt empty"}')
            negative_prompt = str(body.get("negative_prompt", "")).strip()
            media = body.get("media") or {}
            if not isinstance(media, dict):
                return self._send(400, b'{"error":"media must be object {key: fileName}"}')
            required = [k for k, m in (w.get("rh_media") or {}).items() if m.get("required")]
            missing = [k for k in required if not media.get(k)]
            if missing:
                return self._send(400, json.dumps({"error": f"missing media: {', '.join(missing)}"}, ensure_ascii=False).encode())
            params = body.get("params") or {}
            if not isinstance(params, dict):
                return self._send(400, b'{"error":"params must be object"}')
            # Video jobs are async cloud tasks: allow a small concurrent pool
            # (RH queues them itself). Image jobs stay serial via /api/generate.
            with _lock_jobs:
                running_videos = [j for j in _jobs.values()
                                  if j.get("generation_backend") == "cloud"
                                  and j.get("workflow") in WORKFLOWS
                                  and WORKFLOWS[j["workflow"]].get("kind") == "video"
                                  and j.get("status") == "running"]
            if len(running_videos) >= VIDEO_MAX_CONCURRENT:
                return self._send(429, json.dumps({
                    "error": f"视频任务已达并发上限（{VIDEO_MAX_CONCURRENT}个），请等待其中一个完成",
                    "running_jobs": [j["id"] for j in running_videos],
                }, ensure_ascii=False).encode())
            job = {"id": uuid.uuid4().hex[:12], "workflow": wf, "prompt": prompt,
                   "negative_prompt": negative_prompt, "prompt_mode": "manual",
                   "media": media, "params": params,
                   "width": 0, "height": 0, "batch": 1, "hd": 0,
                   "seed": 0, "seed_mode": "random", "loras": {}, "lora_strengths": {},
                   "trigger": None, "translate": False,
                   "status": "running", "progress": 0, "progress_pct": 0, "images": [],
                   "prompt_ids": [], "error": None, "elapsed": None,
                   "created": time.time(), "wf_name": w["name"],
                   "submit_started": None, "provider_started": None,
                   "provider_finished": None, "download_started": None,
                   "download_finished": None, "style_id": "video", "mode": "original",
                   "generation_backend": "cloud",
                   "sequence_mode": "off", "selection_snapshot": body.get("selection_snapshot") or {}}
            with _lock_jobs:
                _jobs[job["id"]] = job
                save_jobs()
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            self._send(200, json.dumps({"job_id": job["id"]}).encode())
        if path == "/api/favorites":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            jid = str(body.get("job_id", "")); idx = int(body.get("image_index", -1))
            with _lock_jobs: job = _jobs.get(jid)
            if not job or job.get("status") != "done": return self._send(404, b'{"error":"completed job not found"}')
            images = job.get("images") or []
            if idx < 0 or idx >= len(images): return self._send(400, b'{"error":"bad image index"}')
            im = images[idx]; fid = uuid.uuid4().hex[:12]
            remote_suffix = pathlib.PurePosixPath(urllib.parse.urlparse(im.get("url", "")).path).suffix.lower()
            suffix = remote_suffix if remote_suffix in (".png", ".jpg", ".jpeg", ".webp") else ".png"
            dest = FAVORITES_DIR / f"{fid}{suffix}"
            try:
                if im.get("remote"):
                    download_file_resilient(im["url"], dest, timeout=120)
                else:
                    src = ensure_local_original(job, im)
                    dest.write_bytes(src.read_bytes())
            except Exception as e:
                return self._send(502, json.dumps({"error": f"收藏图片失败：{str(e)[:200]}"}, ensure_ascii=False).encode())
            favorite_data = dest.read_bytes()
            favorite_media_type = image_content_type(favorite_data, dest.name) or "image/png"
            fav = {
                "id": fid, "created": time.time(), "job_id": jid, "image_index": idx,
                "image_url": f"/api/favorite-image/{fid}",
                "preview_url": f"/api/favorite-preview/{fid}", "original_url": im.get("url"),
                "image_path": str(dest), "favorite_media_type": favorite_media_type,
                "prompt": job.get("prompt", ""),
                "negative_prompt": job.get("negative_prompt", ""),
                "prompt_mode": job.get("prompt_mode", "options"),
                "seed": job.get("seed"), "seed_mode": job.get("seed_mode"),
                "generation_backend": job.get("generation_backend", "cloud"),
                "selection_snapshot": job.get("selection_snapshot") or {},
                "width": job.get("width"), "height": job.get("height"), "batch": job.get("batch"),
            }
            with _lock_jobs:
                _favorites[fid] = fav; save_favorites()
            return self._send(200, json.dumps(fav, ensure_ascii=False).encode())
        if path == "/api/comfy/start":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            started, msg = start_comfy_remote()
            self._send(200 if started else 502, json.dumps({"started": started, "detail": msg}).encode())
            return
        if path != "/api/generate":
            return self._send(404, b'{"error":"not found"}')
        if not self._auth():
            return self._send(401, b'{"error":"unauthorized"}')
        try:
            body = self._read_json()
        except Exception:
            return self._send(400, b'{"error":"bad json"}')
        wf = body.get("workflow"); 
        if wf not in WORKFLOWS:
            return self._send(400, b'{"error":"unknown workflow"}')
        w = WORKFLOWS[wf]
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            return self._send(400, b'{"error":"prompt empty"}')
        negative_prompt = str(body.get("negative_prompt", "")).strip()
        prompt_mode = str(body.get("prompt_mode") or "options")
        if prompt_mode not in ("options", "manual"):
            return self._send(400, b'{"error":"unknown prompt_mode"}')
        generation_backend = str(body.get("generation_backend") or "cloud")
        if generation_backend not in ("cloud", "local"):
            return self._send(400, b'{"error":"unknown generation_backend"}')
        client_request_id = str(body.get("client_request_id") or "").strip()[:96]
        with _submit_locks[generation_backend]:
            # Browser submission retries reuse this id. If the first response was
            # lost, return the same accepted task instead of generating twice.
            existing_job = existing_job_for_request(client_request_id, generation_backend)
            if existing_job:
                return self._send(200, json.dumps({
                    "job_id": existing_job["id"], "existing_job": existing_job["id"],
                    "deduplicated": True, "message": "same request already accepted",
                }).encode())
            active_id = self._running_job_id(generation_backend)
            if active_id:
                # Return the active job id: this is an expected busy state, not
                # a provider failure. 429 has clearer semantics than a raw 409.
                return self._send(429, json.dumps({
                    "error": "已有任务正在运行，请等待完成后再提交",
                    "running_job": active_id,
                }, ensure_ascii=False).encode())
            batch = max(1, min(int(body.get("batch", 1)), w["batch_max"]))
            hd = int(body.get("hd", 0))
            width = int(body.get("width", 0) or 0)
            height = int(body.get("height", 0) or 0)
            if w["size_mode"] == "native":
                presets = w["size_presets"]
                if not (width > 0 and height > 0):
                    width, height = presets[0]["w"], presets[0]["h"]
                # FLUX native latents are multiples of 16; round so delivered size is exact
                width, height = max(256, round(width / 16) * 16), max(256, round(height / 16) * 16)
            if width and height and not (256 <= width <= 2048 and 256 <= height <= 2048):
                return self._send(400, b'{"error":"size out of range 256-2048"}')
            seed_mode = str(body.get("seed_mode") or "random")
            if seed_mode not in ("random", "fixed"):
                return self._send(400, b'{"error":"unknown seed_mode"}')
            seed = body.get("seed")
            try: seed = int(seed) if seed is not None else 0
            except Exception: seed = 0
            if not (1 <= seed <= 9007199254740991):
                seed = secrets.randbelow(2**53 - 1) + 1
            style_id = str(body.get("style_id") or "cold")
            mode = str(body.get("mode") or "original")
            if style_id not in STYLE_PRESETS:
                return self._send(400, b'{"error":"unknown style_id"}')
            if mode not in ("original", "character"):
                return self._send(400, b'{"error":"unknown mode"}')
            preset = STYLE_PRESETS[style_id]
            sequence_raw = str(body.get("sequence_mode") or "off")
            sequence_mode = {"3": "sketch3", "4": "sketch4"}.get(sequence_raw, sequence_raw)
            if sequence_mode not in ("off", "sketch3", "sketch4"):
                return self._send(400, b'{"error":"unknown sequence_mode"}')
            if sequence_mode != "off" and style_id != "sketch":
                return self._send(400, b'{"error":"sketch sequence is only available for sketch style"}')
            # Both image backends use the same trusted style mapping. The local
            # runner converts basenames to Anima_JT\ paths just before submit.
            loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}
            lora_strengths = dict(preset["strengths"])
            trigger = preset["trigger"]
            translate = False
            job = {"id": uuid.uuid4().hex[:12], "workflow": wf, "prompt": prompt,
                   "negative_prompt": negative_prompt, "prompt_mode": prompt_mode,
                   "width": width, "height": height, "batch": batch, "hd": hd,
                   "seed": seed, "seed_mode": seed_mode, "loras": loras, "lora_strengths": lora_strengths,
                   "trigger": trigger, "translate": translate,
                   "status": "running", "progress": 0, "progress_pct": 0, "images": [],
                   "prompt_ids": [], "error": None, "elapsed": None,
                   "created": time.time(), "wf_name": w["name"],
                   "submit_started": None, "provider_started": None,
                   "provider_finished": None, "download_started": None,
                   "download_finished": None, "style_id": style_id, "mode": mode,
                   "sequence_mode": sequence_mode, "generation_backend": generation_backend,
                   "client_request_id": client_request_id,
                   "comfy_prompt_id": None, "transfer_index": 0, "transfer_total": 0,
                   "transfer_started": None, "transfer_finished": None,
                   "selection_snapshot": body.get("selection_snapshot") or {}}
            with _lock_jobs:
                _jobs[job["id"]] = job
                save_jobs()
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            self._send(200, json.dumps({"job_id": job["id"]}).encode())

def main():
    global TOKEN
    if not TOKEN:
        TOKEN = os.environ.get("PANEL_TOKEN") or secrets.token_urlsafe(24)
        print(f"[panel] no PANEL_TOKEN set, generated: {TOKEN}", flush=True)
    load_jobs()
    load_favorites()
    ok, msg = comfy_ok()
    print(f"[panel] comfy {COMFY_URL}: ok={ok} {msg}", flush=True)
    print(f"[panel] listening 0.0.0.0:{PORT} data={DATA_DIR}", flush=True)
    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True
    S(("0.0.0.0", PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
