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
import json, os, re, sys, time, uuid, threading, urllib.request, urllib.parse, urllib.error, math
import http.server, http.cookies, socketserver, pathlib, secrets, hashlib, hmac
import socket, base64, struct, subprocess, io, gzip, ipaddress

BASE = pathlib.Path(__file__).resolve().parent
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://127.0.0.1:8198").rstrip("/")
PORT = int(os.environ.get("PANEL_PORT", "8189"))
TOKEN = os.environ.get("PANEL_TOKEN", "")
PANEL_RELEASE_TOKEN = os.environ.get("PANEL_RELEASE_TOKEN", "")
_SESSION_SECRET_SOURCE = os.environ.get("PANEL_SESSION_SECRET") or TOKEN or secrets.token_urlsafe(32)
SESSION_SECRET = hashlib.sha256(("jt-session-signing:" + _SESSION_SECRET_SOURCE).encode("utf-8")).digest()
DATA_DIR = pathlib.Path(os.environ.get("PANEL_DIR", str(BASE / "panel_data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR = DATA_DIR / "jobs"; JOBS_DIR.mkdir(exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"
FAVORITES_DIR = DATA_DIR / "favorites"; FAVORITES_DIR.mkdir(exist_ok=True)
FAVORITES_FILE = DATA_DIR / "favorites.json"
UPLOAD_CAPABILITIES_FILE = DATA_DIR / "upload_capabilities.json"
UPLOAD_USAGE_FILE = DATA_DIR / "upload_usage.json"

# RunningHub API 适配
RH_BASE = "https://www.runninghub.ai/openapi/v2"
RH_KEY = os.environ.get("RUNNINGHUB_API_KEY", "")

# DreamAPI Responses image-generation adapter. The browser never sees this key
# or controls the upstream URL/text model; only an allowlisted image model,
# quality and fit mode can be selected through the creator endpoint.
DREAMAPI_KEY = os.environ.get("DREAMAPI_KEY", "")
DREAMAPI_BASE_URL = os.environ.get("DREAMAPI_BASE_URL", "https://dreamapi.club").rstrip("/")
DREAMAPI_EGRESS_URL = os.environ.get("DREAMAPI_EGRESS_URL", "").strip()
DREAMAPI_TEXT_MODEL = "gpt-5.6-luna"
DREAMAPI_DISPATCH_INSTRUCTIONS = (
    "You are an image generation dispatcher. Call the provided image_generation "
    "tool exactly once. Do not return or rewrite a prompt. Return no text."
)
DREAMAPI_TIMEOUT = 600
DREAMAPI_MAX_RESPONSE_BYTES = 96 * 1024 * 1024
DREAMAPI_MAX_IMAGE_BYTES = 32 * 1024 * 1024
DREAMAPI_MAX_SOURCE_PIXELS = 32 * 1024 * 1024
DREAMAPI_IMAGE_QUALITIES = {
    "gpt-image-2": {"low", "medium", "high", "auto"},
    "gpt-image-2.5-flare": {"low", "medium", "high", "xhigh", "max", "auto"},
    "gpt-image-2.5-sunburst": {"low", "medium", "high", "xhigh", "max", "auto"},
}
DREAMAPI_IMAGE_ACTION_MODELS = {
    "gpt-image-2.5-flare",
    "gpt-image-2.5-sunburst",
}
DREAMAPI_RATIO_SIZES = {
    "1:1": (1024, 1024),
    "2:3": (1024, 1536),
    "3:2": (1536, 1024),
    "9:16": (864, 1536),
    "16:9": (1536, 864),
}
RH_TIMEOUT_SUBMIT = 60
RH_TIMEOUT_QUERY = 30
RH_SUBMIT_HARD_TIMEOUT = 120  # wall-clock cap for the whole submit (all retries)
MAX_JSON_BYTES = 42 * 1024 * 1024  # 30 MiB image after base64 + bounded metadata
MAX_UPLOAD_JSON_BYTES = 82 * 1024 * 1024  # existing 60 MiB video after base64
MAX_HTTP_WORKERS = 32
HTTP_REQUEST_BACKLOG = 128
MAX_REJECTION_WORKERS = 8
OVERLOAD_DRAIN_TIMEOUT = 0.1
MAX_OVERLOAD_HEADER_BYTES = 16 * 1024
CLIENT_SOCKET_TIMEOUT = 10
LARGE_RESPONSE_THRESHOLD = 256 * 1024
MAX_LARGE_RESPONSE_WORKERS = 4
RESPONSE_SOCKET_TIMEOUT = 180
RESPONSE_BODY_BASE_TIMEOUT = 60
RESPONSE_BODY_MIN_BYTES_PER_SECOND = 8 * 1024
RESPONSE_BODY_MAX_TIMEOUT = 300
REQUEST_HEADER_TIMEOUT = 15
REQUEST_BODY_BASE_TIMEOUT = 15
REQUEST_BODY_MIN_BYTES_PER_SECOND = 256 * 1024
REQUEST_BODY_MAX_TIMEOUT = 300
MAX_REQUESTS_PER_CONNECTION = 1
MAX_LARGE_REQUESTS = 2
LARGE_REQUEST_THRESHOLD = 1024 * 1024
REALISM_HISTORY_LIMIT = 50
MAX_FAVORITES = 200
UPLOAD_CAPABILITY_TTL = 24 * 60 * 60
SESSION_COOKIE_TTL = 365 * 24 * 60 * 60
SESSION_COOKIE_REFRESH_AFTER = 30 * 24 * 60 * 60
LEGACY_SESSION_COOKIE_DEADLINE = int(os.environ.get(
    "PANEL_LEGACY_SESSION_COOKIE_DEADLINE", "1792022400"))
MAX_UPLOAD_CAPABILITIES = 2000
UPLOAD_SESSION_HOURLY_LIMIT = 20
UPLOAD_GLOBAL_HOURLY_LIMIT = 100
UPLOAD_SESSION_HOURLY_BYTES = 500 * 1024 * 1024
UPLOAD_GLOBAL_HOURLY_BYTES = 2 * 1024 * 1024 * 1024
BILLABLE_GLOBAL_HOURLY_LIMIT = 10
BILLABLE_GLOBAL_DAILY_LIMIT = 30
BILLABLE_SESSION_HOURLY_LIMIT = 4
# V2 query exposes only real task states, not a stable percentage. Keep these
# conservative and fixed; never manufacture progress from elapsed/poll count.
RH_STAGE_PROGRESS = {"QUEUED": 0.02, "RUNNING": 0.10}


class ProviderTaskFailed(RuntimeError):
    """The provider explicitly reported a terminal failure."""


class ProviderStateUncertain(RuntimeError):
    """A provider task exists, but its current state cannot be confirmed."""

TPL_DIR = BASE / "templates"
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
WORKFLOWS = {w["id"]: w for w in CONFIG["workflows"]}
RETIRED_REALISM_WORKFLOW_IDS = {"realism_3in1"}

# Fixed server-side mappings. The browser only chooses a style id; it cannot
# send arbitrary LoRA filenames or trigger words. Trigger tokens must match the
# tokens used by the corresponding training run.
STYLE_PRESETS = {
    "cold": {
        "trigger": "jt_style3_v2",
        "LORA1": "05_style3_v2_step1600.safetensors",
        "LORA2": "04_style3_step800.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
        "default_variant": "character_bound",
        "variants": {
            "character_bound": {
                "id": "character_bound",
                "trigger": "jt_style3_v2",
                "LORA1": "05_style3_v2_step1600.safetensors",
                "LORA2": "04_style3_step800.safetensors",
                "strengths": {"LORA1": 0.7, "LORA2": 0.6},
            },
            # The v2 run was trained as a style candidate and passed the
            # available male/no-human leakage probes. Its source set still
            # contains one recurring character, so this remains explicitly a
            # low-leakage candidate rather than a claim of full disentanglement.
            # Node 2 stays in the fixed RH/local graph at zero strength.
            "style_only": {
                "id": "style_only",
                "trigger": "jt_style3_v2",
                "LORA1": "05_style3_v2_step1600.safetensors",
                "LORA2": "05_style3_v2_step1600.safetensors",
                "strengths": {"LORA1": 0.6, "LORA2": 0.0},
            },
        },
    },
    "sketch": {
        "trigger": "jt_style1_v1",
        "LORA1": "01_style1_step900.safetensors",
        "LORA2": "01_style1_step900.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    },
    "original_sketch": {
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
    "original_graphic": {
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
    "retro_manga_luxury": {
        "trigger": "jt_style321_v1",
        "LORA1": "09_style321_v1_step200.safetensors",
        "LORA2": "09_style321_v1_step200.safetensors",
        "strengths": {"LORA1": 0.4, "LORA2": 0.0},
    },
    "style221": {
        "trigger": "zxqelun",
        "LORA1": "11_style221_v1_step400.safetensors",
        "LORA2": "11_style221_v1_step400.safetensors",
        "strengths": {"LORA1": 0.4, "LORA2": 0.0},
    },
    "style222": {
        "trigger": "zxqavri",
        "LORA1": "10_style222_v1_step400.safetensors",
        "LORA2": "10_style222_v1_step400.safetensors",
        "strengths": {"LORA1": 0.4, "LORA2": 0.0},
    },
}

def local_lora_name(name):
    """Map a trusted LoRA basename to the local ComfyUI model path."""
    return "Anima_JT\\" + pathlib.PurePath(str(name)).name


def resolve_style_preset(style_id, style_variant=None):
    """Resolve a trusted style mapping without accepting client LoRA data."""
    preset = STYLE_PRESETS.get(style_id)
    if not preset:
        raise ValueError("unknown style_id")
    variants = preset.get("variants")
    if variants:
        variant_id = str(style_variant or preset.get("default_variant") or "")
        variant = variants.get(variant_id)
        if not variant:
            raise ValueError("unknown style_variant")
        return {
            "id": variant["id"],
            "trigger": variant["trigger"],
            "LORA1": variant["LORA1"],
            "LORA2": variant["LORA2"],
            "strengths": dict(variant["strengths"]),
        }
    if style_variant not in (None, "", "default"):
        raise ValueError("unknown style_variant")
    return {
        "id": "default",
        "trigger": preset["trigger"],
        "LORA1": preset["LORA1"],
        "LORA2": preset["LORA2"],
        "strengths": dict(preset["strengths"]),
    }

RETIRED_SEQUENCE_MODES = {"sketch3", "sketch4"}

# Cloud and local image generation have independent resources. Keep each
# backend serial, but allow one RunningHub job and one local-ComfyUI job to run
# at the same time. Video jobs are async cloud tasks and may run concurrently.
_submit_locks = {
    "cloud": threading.Lock(), "local": threading.Lock(), "api": threading.Lock(),
    "video": threading.Lock(),
}
VIDEO_MAX_CONCURRENT = 2   # live RunningHub personal API limit verified by code 421
_jobs = {}                        # job_id -> job dict
_lock_jobs = threading.Lock()
_LORA_CACHE = {"t": 0.0, "list": []}
_progress = {}                    # prompt_id -> (value, max) from ComfyUI WebSocket
_favorites = {}
_archive_locks = {}
_archive_locks_guard = threading.Lock()
_favorite_operation_lock = threading.Lock()
_upload_capabilities = {}
_upload_capabilities_lock = threading.Lock()
_upload_usage = []
_upload_usage_lock = threading.Lock()
_billable_quota_lock = threading.Lock()
_admission_lock = threading.Lock()
_idempotency_lock = _admission_lock  # compatibility alias for older tests/tools
_release_draining = os.environ.get("PANEL_RELEASE_DRAIN_ON_START") == "1"
_comfy_start_lock = threading.Lock()
_recovery_jobs = set()
_recovery_jobs_lock = threading.Lock()


def _is_loopback_peer(host):
    try:
        return ipaddress.ip_address(str(host or "").split("%", 1)[0]).is_loopback
    except ValueError:
        return False

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


def _ascii_remote_url(url):
    """Return an urllib-safe ASCII form without changing URL semantics."""
    parsed = urllib.parse.urlsplit(str(url or ""))
    if (parsed.scheme.lower() not in ("http", "https") or not parsed.netloc
            or parsed.username is not None or parsed.password is not None):
        return "", None
    try:
        hostname = (parsed.hostname or "").encode("idna").decode("ascii")
    except UnicodeError:
        return "", None
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    if parsed.port is not None:
        host += f":{parsed.port}"
    raw_name = pathlib.PurePosixPath(parsed.path).name
    display_name = pathlib.PurePosixPath(urllib.parse.unquote(raw_name)).name
    path = urllib.parse.quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parsed.query, safe="=&%/:?@!$'()*+,;~-._")
    fragment = urllib.parse.quote(parsed.fragment, safe="=&%/:?@!$'()*+,;~-._")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, query, fragment)), display_name


def _json_object_from_bytes(raw, label):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} root must be an object")
    return value


def _atomic_write_bytes(path, raw):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json_object(path, value, label):
    if not isinstance(value, dict):
        raise TypeError(f"{label} root must be an object")
    path = pathlib.Path(path)
    raw = json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")
    # Keep the last known-good primary. A corrupt primary must never replace a
    # valid backup while the service is recovering.
    if path.exists():
        previous = path.read_bytes()
        try:
            _json_object_from_bytes(previous, label)
        except RuntimeError:
            pass
        else:
            _atomic_write_bytes(path.with_suffix(path.suffix + ".bak"), previous)
    _atomic_write_bytes(path, raw)
    if _json_object_from_bytes(path.read_bytes(), label) != value:
        raise RuntimeError(f"{label} atomic write verification failed")


def _preserve_corrupt_json(path):
    path = pathlib.Path(path)
    if not path.exists():
        return None
    destination = path.with_name(f"{path.name}.corrupt-{int(time.time())}-{uuid.uuid4().hex[:8]}")
    _atomic_write_bytes(destination, path.read_bytes())
    return destination


def _load_json_object(path, label):
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    primary_raw = path.read_bytes()
    try:
        return _json_object_from_bytes(primary_raw, label)
    except RuntimeError as primary_error:
        _preserve_corrupt_json(path)
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            try:
                return _json_object_from_bytes(backup.read_bytes(), label + " backup")
            except RuntimeError:
                pass
        raise RuntimeError(
            f"{label} is corrupt and no valid backup is available; original bytes were preserved"
        ) from primary_error


def load_jobs():
    global _jobs
    _jobs = _load_json_object(JOBS_FILE, "jobs ledger")
    # Normalize legacy provider URLs before the browser or urllib uses them.
    # This migration is local-only and never submits or polls a provider task.
    for j in _jobs.values():
        for image in j.get("images") or []:
            if not isinstance(image, dict) or not image.get("remote"):
                continue
            for key in ("url", "preview_url"):
                value = image.get(key)
                if not isinstance(value, str) or not value:
                    continue
                normalized, display_name = _ascii_remote_url(value)
                if normalized:
                    image[key] = normalized
                    if key == "url" and display_name:
                        image["file"] = display_name
    # Cloud jobs with a provider task id are resumable without another submit.
    for j in _jobs.values():
        if j.get("status") == "running":
            if j.get("sequence_mode") in RETIRED_SEQUENCE_MODES:
                j["status"] = "error"
                j["error"] = "服务重启中断多阶段任务；已保留阶段与RunningHub任务号，请核对后再运行"
            elif j.get("generation_backend", "cloud") == "cloud" and j.get("rh_task_id"):
                j["status"] = "recovering"
                j["provider_status"] = "RECOVERING"
            else:
                j["status"] = "error"
                j["error"] = "服务重启，任务提交状态未确认；请核对历史后再运行"
    save_jobs()

def save_jobs():
    _atomic_write_json_object(JOBS_FILE, _jobs, "jobs ledger")


def persist_provider_task(job, task_id):
    """Durably checkpoint provider acceptance before any status polling."""
    job["rh_task_id"] = task_id
    job["provider_started"] = time.time()
    with _lock_jobs:
        save_jobs()

def load_favorites():
    global _favorites
    _favorites = _load_json_object(FAVORITES_FILE, "favorites ledger")
    changed = False
    for item in _favorites.values():
        if isinstance(item, dict) and "selection_snapshot" in item:
            clean = public_selection_snapshot(item.get("selection_snapshot"))
            if clean != item.get("selection_snapshot"):
                item["selection_snapshot"] = clean
                changed = True
    if changed:
        save_favorites()


def public_favorite(item):
    result = dict(item) if isinstance(item, dict) else {}
    result["selection_snapshot"] = public_selection_snapshot(result.get("selection_snapshot"))
    for private_key in ("provider_media", "image_path", "original_url"):
        result.pop(private_key, None)
    return result

def save_favorites():
    _atomic_write_json_object(FAVORITES_FILE, _favorites, "favorites ledger")


def _upload_token_hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _session_cookie_signature(payload):
    return base64.urlsafe_b64encode(
        hmac.new(SESSION_SECRET, payload.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def _encode_session_cookie(session_id, issued_at=None):
    session_id = str(session_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", session_id):
        raise ValueError("invalid session id")
    issued_at = int(time.time() if issued_at is None else issued_at)
    payload = f"v1.{session_id}.{issued_at}"
    return payload + "." + _session_cookie_signature(payload)


def _decode_session_cookie_details(value, now=None):
    value = str(value or "")
    now = int(time.time() if now is None else now)
    parts = value.split(".")
    if len(parts) == 4 and parts[0] == "v1":
        _, session_id, issued_text, signature = parts
        if (not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", session_id)
                or not re.fullmatch(r"\d{1,12}", issued_text)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", signature)):
            return "", False
        payload = ".".join(parts[:3])
        if not hmac.compare_digest(signature, _session_cookie_signature(payload)):
            return "", False
        issued_at = int(issued_text)
        age = now - issued_at
        if age < -300 or age > SESSION_COOKIE_TTL:
            return "", False
        return session_id, age >= SESSION_COOKIE_REFRESH_AFTER

    # One bounded migration window keeps existing users' history available.
    # A legacy cookie has no timestamp, so it is rejected after the deadline.
    if len(parts) == 2 and now <= LEGACY_SESSION_COOKIE_DEADLINE:
        session_id, signature = parts
        if (re.fullmatch(r"[A-Za-z0-9_-]{20,100}", session_id)
                and re.fullmatch(r"[A-Za-z0-9_-]{43}", signature)
                and hmac.compare_digest(signature, _session_cookie_signature(session_id))):
            return session_id, True
    return "", False


def _decode_session_cookie(value):
    return _decode_session_cookie_details(value)[0]


def session_owns_record(session_id, record, owner_key="request_session_hash"):
    expected = str((record or {}).get(owner_key) or "")
    return bool(session_id and expected and hmac.compare_digest(expected, _session_hash(session_id)))


def _session_hash(value):
    return hashlib.sha256(("jt-session:" + str(value or "")).encode("utf-8")).hexdigest()


def load_upload_capabilities():
    global _upload_capabilities
    if UPLOAD_CAPABILITIES_FILE.exists():
        try:
            loaded = json.loads(UPLOAD_CAPABILITIES_FILE.read_text(encoding="utf-8"))
            _upload_capabilities = loaded if isinstance(loaded, dict) else {}
        except Exception:
            _upload_capabilities = {}
    prune_upload_capabilities(save=False)


def load_upload_usage():
    global _upload_usage
    if UPLOAD_USAGE_FILE.exists():
        try:
            loaded = json.loads(UPLOAD_USAGE_FILE.read_text(encoding="utf-8"))
            _upload_usage = loaded if isinstance(loaded, list) else []
        except Exception:
            _upload_usage = []
    prune_upload_usage(save=False)


def save_upload_usage():
    tmp = UPLOAD_USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_upload_usage, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(UPLOAD_USAGE_FILE)


def prune_upload_usage(now=None, save=True):
    now = time.time() if now is None else float(now)
    cutoff = now - 3600
    _upload_usage[:] = [
        row for row in _upload_usage
        if isinstance(row, dict) and float(row.get("created", 0)) > cutoff
        and int(row.get("bytes", 0)) >= 0
    ]
    if save:
        save_upload_usage()


def reserve_upload_attempt(session_id, byte_count, now=None):
    """Atomically account one validated provider upload before network I/O."""
    now = time.time() if now is None else float(now)
    byte_count = int(byte_count)
    if byte_count < 1:
        raise ValueError("empty upload")
    digest = _session_hash(session_id)
    with _upload_usage_lock:
        prune_upload_usage(now=now, save=False)
        session_rows = [row for row in _upload_usage if row.get("session_hash") == digest]
        checks = (
            ("session_hour", len(session_rows), UPLOAD_SESSION_HOURLY_LIMIT),
            ("session_bytes", sum(int(row["bytes"]) for row in session_rows), UPLOAD_SESSION_HOURLY_BYTES - byte_count + 1),
            ("global_hour", len(_upload_usage), UPLOAD_GLOBAL_HOURLY_LIMIT),
            ("global_bytes", sum(int(row["bytes"]) for row in _upload_usage), UPLOAD_GLOBAL_HOURLY_BYTES - byte_count + 1),
        )
        for scope, used, limit in checks:
            if used >= limit:
                rows = session_rows if scope.startswith("session") else _upload_usage
                oldest = min((float(row.get("created", now)) for row in rows), default=now)
                return {"blocked": True, "scope": scope,
                        "retry_after": max(1, math.ceil(oldest + 3600 - now))}
        _upload_usage.append({"created": now, "bytes": byte_count, "session_hash": digest})
        save_upload_usage()
    return None


def save_upload_capabilities():
    tmp = UPLOAD_CAPABILITIES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_upload_capabilities, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(UPLOAD_CAPABILITIES_FILE)


def prune_upload_capabilities(save=True):
    now = time.time()
    stale = [key for key, row in _upload_capabilities.items()
             if not isinstance(row, dict) or float(row.get("expires", 0)) <= now]
    for key in stale:
        _upload_capabilities.pop(key, None)
    if len(_upload_capabilities) > MAX_UPLOAD_CAPABILITIES:
        ordered = sorted(_upload_capabilities,
                         key=lambda key: float(_upload_capabilities[key].get("created", 0)))
        for key in ordered[:len(_upload_capabilities) - MAX_UPLOAD_CAPABILITIES]:
            _upload_capabilities.pop(key, None)
    if save:
        save_upload_capabilities()


def issue_upload_capability(provider_name, workflow_id, input_key, media_type,
                            original_filename, session_id):
    token = "upl_" + secrets.token_urlsafe(32)
    now = time.time()
    row = {
        "provider_name": str(provider_name), "workflow": str(workflow_id),
        "input_key": str(input_key), "media_type": str(media_type).lower(),
        "filename": str(original_filename), "session_hash": _session_hash(session_id),
        "created": now, "expires": now + UPLOAD_CAPABILITY_TTL,
    }
    with _upload_capabilities_lock:
        _upload_capabilities[_upload_token_hash(token)] = row
        prune_upload_capabilities(save=True)
    return token


def resolve_upload_capabilities(workflow, submitted_media, session_id):
    if not isinstance(submitted_media, dict):
        raise ValueError("media must be an object")
    provider_media, public_media = {}, {}
    now = time.time()
    with _upload_capabilities_lock:
        for key, mapping in (workflow.get("rh_media") or {}).items():
            token = submitted_media.get(key)
            if token in (None, ""):
                if mapping.get("required"):
                    label = str(mapping.get("label") or key)
                    raise ValueError(f"missing upload for input {key} ({label})")
                continue
            token = str(token)
            if not re.fullmatch(r"upl_[A-Za-z0-9_-]{30,100}", token):
                raise ValueError("upload token invalid")
            row = _upload_capabilities.get(_upload_token_hash(token))
            if not isinstance(row, dict) or float(row.get("expires", 0)) <= now:
                raise ValueError("upload token invalid or expired")
            if not secrets.compare_digest(str(row.get("session_hash") or ""), _session_hash(session_id)):
                raise ValueError("upload session mismatch")
            if row.get("workflow") != workflow.get("id"):
                raise ValueError("upload workflow mismatch")
            if row.get("input_key") != key:
                raise ValueError("upload input mismatch")
            expected_type = str(mapping.get("type") or "").lower()
            if row.get("media_type") != expected_type:
                raise ValueError("upload media type mismatch")
            provider_media[key] = str(row["provider_name"])
            public_media[key] = str(row.get("filename") or "uploaded")[:255]
    return provider_media, public_media


def upload_bound_snapshot(workflow, public_media, trusted_params, raw_snapshot, source_page):
    raw = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    raw_names = raw.get("media_names") if isinstance(raw.get("media_names"), dict) else {}
    names = {}
    for key, fallback_name in public_media.items():
        candidate = raw_names.get(key) or fallback_name
        name = re.split(r"[\\/]", str(candidate or ""))[-1].strip()
        if name and re.fullmatch(r"[^\x00-\x1f\x7f]{1,255}", name):
            names[key] = name
    return {
        "source_page": source_page,
        "workflow": workflow["id"],
        "params": _json_safe_integer_metadata(dict(trusted_params)),
        "media": {},
        "media_names": names,
    }


def prune_favorites(owner_session_hash=None):
    if owner_session_hash is None:
        owners = {str(item.get("owner_session_hash") or "") for item in _favorites.values()}
        for owner in owners:
            prune_favorites(owner)
        return
    ordered = sorted(
        (item for item in _favorites.values()
         if str(item.get("owner_session_hash") or "") == str(owner_session_hash)),
        key=lambda item: item.get("created", 0), reverse=True)
    for old in ordered[MAX_FAVORITES:]:
        _favorites.pop(old.get("id"), None)
        for key in ("image_path",):
            try:
                safe_child_path(FAVORITES_DIR, pathlib.Path(old.get(key, ""))).unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
        try:
            safe_child_path(FAVORITES_DIR, f"{old.get('id')}_preview.jpg").unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

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
    if not downloaded_media_content_type(magic, dest.name):
        part.unlink(missing_ok=True)
        raise RuntimeError("downloaded result is not a supported media file")
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


def _response_bytes_limited(response, max_bytes):
    chunks, total = [], 0
    while True:
        try:
            chunk = response.read(min(65536, max_bytes + 1 - total))
        except TypeError:
            # Lightweight test doubles and a few file-like adapters expose only
            # read() without a size argument.
            chunk = response.read()
            if len(chunk) > max_bytes:
                raise RuntimeError("provider response is too large")
            return chunk
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError("provider response is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _provider_json_request(request, data=None, timeout=30, max_bytes=4 * 1024 * 1024):
    """Bound connection and response-body reads by one wall-clock deadline."""
    box = {}

    def worker():
        try:
            with _urlopen_bounded(request, data, timeout) as response:
                raw = _response_bytes_limited(response, max_bytes)
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise RuntimeError("provider JSON root must be an object")
            box["result"] = value
        except Exception as error:
            box["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout + 5)
    if thread.is_alive():
        raise TimeoutError(f"provider response hard timeout after {timeout}s")
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise RuntimeError("provider request ended without a response")
    return box["result"]

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
    p = dest_dir / safe_output_filename(im["filename"])
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
    dest = safe_child_path(JOBS_DIR / job["id"], safe_output_filename(image["file"]))
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

def billable_quota_status(session_id, now=None):
    now = time.time() if now is None else float(now)
    hour_start, day_start = now - 3600, now - 86400
    session_digest = _session_hash(session_id)
    with _lock_jobs:
        billable = [job for job in _jobs.values()
                    if job.get("billable_quota_recorded") is True
                    and job.get("generation_backend") in ("cloud", "api")
                    and isinstance(job.get("created"), (int, float))]
        global_hour = sum(1 for job in billable if job["created"] >= hour_start)
        global_day = sum(1 for job in billable if job["created"] >= day_start)
        session_hour = sum(1 for job in billable
                           if job["created"] >= hour_start
                           and secrets.compare_digest(str(job.get("quota_session_hash") or ""), session_digest))
    retry_after = max(1, int(3600 - (now % 3600)))
    return {
        "global_hour": global_hour, "global_day": global_day,
        "session_hour": session_hour,
        "blocked": (global_hour >= BILLABLE_GLOBAL_HOURLY_LIMIT
                    or global_day >= BILLABLE_GLOBAL_DAILY_LIMIT
                    or session_hour >= BILLABLE_SESSION_HOURLY_LIMIT),
        "retry_after": retry_after,
    }


def register_billable_job(job, session_id):
    """Atomically enforce public spend limits and persist one accepted paid job."""
    with _billable_quota_lock:
        status = billable_quota_status(session_id)
        if status["blocked"]:
            return status
        job["quota_session_hash"] = _session_hash(session_id)
        job["billable_quota_recorded"] = True
        with _lock_jobs:
            _jobs[job["id"]] = job
            save_jobs()
    return None


def normalize_client_request_id(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", text):
        raise ValueError("client_request_id must be 1-96 safe characters")
    return text


def effective_request_sha256(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def idempotency_decision(client_request_id, session_id, request_sha256):
    """Return (new|duplicate|conflict, job, session_hash) for one caller."""
    session_hash = _session_hash(session_id)
    if not client_request_id or not re.fullmatch(r"[0-9a-f]{64}", str(request_sha256 or "")):
        raise ValueError("invalid idempotency binding")
    with _lock_jobs:
        matches = [
            job for job in _jobs.values()
            if job.get("client_request_id") == client_request_id
            and secrets.compare_digest(str(job.get("request_session_hash") or ""), session_hash)
        ]
    if not matches:
        return "new", None, session_hash
    duplicate = next((job for job in matches
                      if secrets.compare_digest(str(job.get("effective_request_sha256") or ""), request_sha256)), None)
    return ("duplicate", duplicate, session_hash) if duplicate else ("conflict", matches[0], session_hash)


def _json_safe_integer_metadata(value):
    """Encode integers outside JavaScript's exact range as decimal strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > 9007199254740991:
        return str(value)
    if isinstance(value, list):
        return [_json_safe_integer_metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_integer_metadata(item) for key, item in value.items()}
    return value


def public_workflow(w):
    """Return the browser-visible workflow schema without provider identifiers."""
    def public_controls(rows):
        allowed = {"type", "label", "default", "required", "group", "description", "help",
                   "placeholder", "max_length", "options", "min", "max", "step", "allow_blank", "depends_on"}
        return {key: {name: value for name, value in mapping.items() if name in allowed}
                for key, mapping in (rows or {}).items()}
    description = str(w.get("desc") or "")
    description = re.sub(r"(?:人物|画风)?LoRA(?:\([^)]*\))?", "服务端可信画风配置", description,
                         flags=re.IGNORECASE)
    description = re.sub(r"触发词\s+[^\s·,，()（）]+", "", description)
    description = re.sub(r"[^\s·,，()（）]+\.safetensors", "服务端可信模型", description)
    description = re.sub(r"(?:·\s*){2,}", "· ", description).strip(" ·")
    result = {
        "id": w["id"], "name": w["name"], "desc": description,
        "section": w.get("section", "其他"),
        "speed": w.get("speed", "—"), "ref": w.get("ref", "—"),
        "prompt_default": w.get("prompt_default", ""),
        "size_mode": w.get("size_mode", "native"),
        "size_presets": w.get("size_presets", []),
        "batch_max": w.get("batch_max", 1), "hd": w.get("hd", []),
        "translate_default": w.get("translate_default", True),
        "kind": w.get("kind", "image"),
        "rh_media": public_controls(w.get("rh_media", {})),
        "rh_params": public_controls(w.get("rh_params", {})),
        "params_defaults": w.get("params_defaults", {}),
        "subworkflows": w.get("subworkflows", []),
        "fixed_features": w.get("fixed_features", []),
        "prompt_placeholder": w.get("prompt_placeholder"),
        "prompt_hint": w.get("prompt_hint"),
    }
    return _json_safe_integer_metadata(result)


def realism_history_jobs(jobs):
    ids = {key for key, workflow in WORKFLOWS.items()
           if workflow.get("kind") in ("rh_workflow", "ai_app")}
    ids.update(RETIRED_REALISM_WORKFLOW_IDS)
    return [job for job in sorted(jobs, key=lambda row: row.get("created", 0), reverse=True)
            if job.get("workflow") in ids or job.get("style_id") == "realism"][:REALISM_HISTORY_LIMIT]


def scoped_history_jobs(jobs, scope=None, style=None, limit=12):
    if scope == "realism":
        return realism_history_jobs(jobs)
    ordered = sorted(jobs, key=lambda row: row.get("created", 0), reverse=True)
    if scope == "video":
        ids = {key for key, workflow in WORKFLOWS.items() if workflow.get("kind") == "video"}
        ordered = [job for job in ordered if job.get("workflow") in ids]
    elif scope == "creator":
        ordered = [job for job in ordered if job.get("workflow") == "anima02"]
        if style is not None:
            if style not in STYLE_PRESETS:
                return []
            ordered = [job for job in ordered if job.get("style_id") == style]
    elif scope:
        return []
    return ordered[:limit]


def normalize_realism_snapshot(w, trusted_media, trusted_params, snapshot):
    """Persist only server-validated fields in generic workflow history."""
    raw = snapshot if isinstance(snapshot, dict) else {}
    raw_names = raw.get("media_names") if isinstance(raw.get("media_names"), dict) else {}
    media_names = {}
    for key in trusted_media:
        name = re.split(r"[\\/]", str(raw_names.get(key) or ""))[-1].strip()
        if name:
            media_names[key] = name[:255]
    return {
        "source_page": "realism",
        "workflow": w["id"],
        "params": _json_safe_integer_metadata(dict(trusted_params)),
        "media": dict(trusted_media),
        "media_names": media_names,
    }


def public_job_media(media):
    result = {}
    if not isinstance(media, dict):
        return result
    for key, value in media.items():
        text = str(value or "").strip()
        if (not text or text.startswith(("api/", "upl_"))
                or "/" in text or "\\" in text
                or re.search(r"[\x00-\x1f\x7f]", text)):
            continue
        result[str(key)[:100]] = text[:255]
    return result


def public_job_error(job):
    error = str((job or {}).get("error") or "").strip()
    if not error:
        return None
    job_id = str((job or {}).get("id") or "unknown")[:64]
    backend = str((job or {}).get("generation_backend") or "cloud")
    if backend == "local":
        return f"本地任务失败；请使用面板任务号 {job_id} 联系维护人员"
    if backend == "api":
        return f"API任务失败；请使用面板任务号 {job_id} 联系维护人员"
    return f"云端任务失败；请使用面板任务号 {job_id} 联系维护人员"


def public_selection_snapshot(snapshot):
    """Return replay-safe metadata; provider assets and upload tokens never leave the server."""
    raw = snapshot if isinstance(snapshot, dict) else {}
    names = raw.get("media_names") if isinstance(raw.get("media_names"), dict) else {}
    clean_names = {}
    for key, value in names.items():
        name = re.split(r"[\\/]", str(value or ""))[-1].strip()
        if name and re.fullmatch(r"[^\x00-\x1f\x7f]{1,255}", name):
            clean_names[str(key)[:100]] = name
    result = {
        "source_page": str(raw.get("source_page") or "")[:40],
        "workflow": str(raw.get("workflow") or "")[:100],
        "params": _json_safe_integer_metadata(
            dict(raw.get("params")) if isinstance(raw.get("params"), dict) else {}),
        "media": {},
        "media_names": clean_names,
    }
    if raw.get("workflow") == "anima02" or isinstance(raw.get("state"), dict):
        def safe_value(value, depth=0):
            if depth > 5:
                return None
            if isinstance(value, str):
                return value[:12000]
            if value is None or isinstance(value, (bool, int)):
                return _json_safe_integer_metadata(value)
            if isinstance(value, float):
                return value if math.isfinite(value) else None
            if isinstance(value, list):
                return [safe_value(item, depth + 1) for item in value[:100]]
            if isinstance(value, dict):
                return {str(key)[:100]: safe_value(item, depth + 1)
                        for key, item in list(value.items())[:100]}
            return None

        creator_fields = (
            "style", "style_variant", "mode", "state", "locked", "width", "height",
            "batch", "hd", "sequence_mode", "prompt_mode", "manual_positive",
            "manual_negative", "seed", "seed_mode", "generation_backend", "api_ratio",
        )
        for key in creator_fields:
            if key in raw:
                result[key] = safe_value(raw[key])
    return result


def public_job_selection_snapshot(snapshot):
    """Minimize task/history snapshots while favorites retain owner-only replay data."""
    result = public_selection_snapshot(snapshot)
    raw_params = dict(result.get("params") or {})
    common = {
        "width", "height", "batch", "hd", "seed", "seed_mode", "mode",
        "style", "style_id", "style_variant", "sequence_mode", "prompt_mode",
    }
    workflow = WORKFLOWS.get(str(result.get("workflow") or ""), {})
    trusted_workflow_params = set((workflow.get("rh_params") or {}).keys())
    allowed = common | trusted_workflow_params
    result["params"] = {key: value for key, value in raw_params.items() if key in allowed}
    return result


def public_job_params(job):
    """Expose only controls declared by the task's trusted workflow schema."""
    raw = (job or {}).get("params")
    if not isinstance(raw, dict):
        return {}
    workflow = WORKFLOWS.get(str((job or {}).get("workflow") or ""), {})
    allowed = set((workflow.get("rh_params") or {}).keys())
    return {key: _json_safe_integer_metadata(raw[key]) for key in allowed if key in raw}


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

def prune_hd_switch_branches(api, hd):
    """Resolve the selected image branch so unused upscalers never execute."""
    upscale_types = {"UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScaleBy"}
    selected_index = max(0, min(2, int(hd)))
    switch_ids = [node_id for node_id, node in api.items()
                  if node.get("class_type") == "easy imageIndexSwitch"]
    for switch_id in switch_ids:
        inputs = api[switch_id].get("inputs") or {}
        selected = inputs.get(f"image{selected_index}")
        if not (isinstance(selected, list) and len(selected) >= 2):
            continue
        for node in api.values():
            node_inputs = node.get("inputs") or {}
            for key, value in list(node_inputs.items()):
                if isinstance(value, list) and len(value) >= 2 and str(value[0]) == str(switch_id):
                    node_inputs[key] = list(selected)
        def upscale_ancestors(link):
            found = set()
            stack = [str(link[0])] if isinstance(link, list) and len(link) >= 2 else []
            while stack:
                node_id = stack.pop()
                if node_id in found or node_id not in api:
                    continue
                node = api[node_id]
                if node.get("class_type") not in upscale_types:
                    continue
                found.add(node_id)
                for value in (node.get("inputs") or {}).values():
                    if isinstance(value, list) and len(value) >= 2:
                        stack.append(str(value[0]))
            return found

        branch_nodes = set()
        for index in range(3):
            branch_nodes.update(upscale_ancestors(inputs.get(f"image{index}")))
        keep = upscale_ancestors(selected)

        removable = branch_nodes - keep
        protected = set()
        for consumer_id, node in api.items():
            if consumer_id == switch_id or consumer_id in removable:
                continue
            for value in (node.get("inputs") or {}).values():
                if (isinstance(value, list) and len(value) >= 2 and
                        str(value[0]) in removable):
                    protected.update(upscale_ancestors(value))

        del api[switch_id]
        for node_id in removable - protected:
            api.pop(node_id, None)
    return api

def build_api(workflow, prompt, width, height, batch, hd, seed, loras=None, trigger=None, translate=True, negative_prompt="", prefix=None, lora_strengths=None):
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
    # Apply strengths while the template still carries distinct LORA1/LORA2
    # placeholders. Comparing names after substitution is ambiguous when both
    # slots intentionally reference the same file.
    for node in tpl.values():
        inputs = node.get("inputs") or {}
        lora_placeholder = inputs.get("lora_name")
        if isinstance(lora_placeholder, str) and lora_placeholder.startswith("{{LORA"):
            key = lora_placeholder.strip("{}")
            if key in (lora_strengths or {}):
                inputs["strength_model"] = float(lora_strengths[key])
    api = prune_hd_switch_branches(subst_obj(tpl, mapping), hd)
    if w["size_mode"] == "resize" and (int(width) > 0 and int(height) > 0):
        # Preserve the selected image before the switch is pruned above.
        save_ids = {"qwen2511": "21"}
        save_id = save_ids.get(workflow, "11")
        selected_image = list(api[save_id]["inputs"]["images"])
        api["500"] = {"class_type": "ImageScale", "inputs": {
            "image": selected_image, "upscale_method": "lanczos",
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
    """Submit a RunningHub task without retrying an ambiguous POST transport failure.

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
            r = _provider_json_request(req, timeout=per)
        except Exception as e:
            # The POST may have reached RunningHub even when its response was
            # lost. Retrying that ambiguous outcome can create a second billed
            # task, so only explicit provider BUSY/RATE responses below retry.
            raise RuntimeError(
                "RH submit outcome unknown after transport failure; not retried "
                f"to avoid duplicate charge: {e}"
            ) from e
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
        if task_id:
            # A provider-side task already exists. Never submit a second billed
            # task, even when that response also carries TIMEOUT/BUSY wording.
            raise RuntimeError(f"RH submit rejected for taskId {task_id}: {last}")
        # Provider TIMEOUT is ambiguous: the task may exist despite a failed
        # response. Retry only explicit capacity/rate rejections.
        transient = any(x in (code + " " + msg) for x in ("BUSY", "RATE", "TOO MANY", "TEMPORARY"))
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
    result = _provider_json_request(req, timeout=RH_TIMEOUT_SUBMIT)
    status = str(result.get("status") or "").upper()
    task_id = result.get("taskId")
    if task_id and status in ("QUEUED", "RUNNING"):
        return task_id
    raise RuntimeError("RH AI App submit rejected: " + json.dumps(result, ensure_ascii=False)[:600])

def rh_failed_task_detail(task_id):
    """Read a failed task's actionable node reason without resubmitting it."""
    body = json.dumps({"apiKey": RH_KEY, "taskId": task_id}).encode()
    req = urllib.request.Request(
        "https://www.runninghub.cn/task/openapi/outputs", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        result = _provider_json_request(req, timeout=RH_TIMEOUT_QUERY)
    except Exception:
        return ""
    failed = ((result.get("data") or {}).get("failedReason") or {})
    if not isinstance(failed, dict):
        return ""
    node_id = str(failed.get("node_id") or "?")[:80]
    node_name = str(failed.get("node_name") or "未知节点")[:160]
    error_type = str(failed.get("exception_type") or "")[:160]
    message = str(failed.get("exception_message") or "")[:500]
    return f"节点{node_id} {node_name}: {error_type} {message}".strip()


def normalize_rh_coins(response, output_rows):
    """Return one task-level RH coin value; never sum repeated output values."""
    raw = ((response.get("usage") or {}).get("consumeCoins")
           if isinstance(response, dict) else None)
    if raw in (None, ""):
        values = {str(row.get("consumeCoins")).strip() for row in (output_rows or [])
                  if isinstance(row, dict) and row.get("consumeCoins") not in (None, "")}
        if len(values) != 1:
            return None
        raw = values.pop()
    text = str(raw).strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return text


def static_content_type(path):
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(pathlib.Path(path).suffix.lower(), "application/octet-stream")


def rh_output_details(task_id):
    """Read legacy output metadata used as a billing fallback; never submits."""
    body = json.dumps({"apiKey": RH_KEY, "taskId": task_id}).encode()
    req = urllib.request.Request(
        "https://www.runninghub.cn/task/openapi/outputs", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        result = _provider_json_request(req, timeout=RH_TIMEOUT_QUERY)
    except Exception:
        return []
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, list) else []


def rh_query(task_id, job=None):
    """查询 RunningHub 任务状态，返回 (status, results)"""
    url = f"{RH_BASE}/query"
    body = {"taskId": task_id}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {RH_KEY}"},
                                 method="POST")
    try:
        r = _provider_json_request(req, timeout=RH_TIMEOUT_QUERY)
    except Exception as e:
        raise RuntimeError(f"RH query failed: {e}")
    status = r.get("status", "")
    results = r.get("results") or []
    coins = normalize_rh_coins(r, results)
    if coins is None and status == "SUCCESS":
        coins = normalize_rh_coins({}, rh_output_details(task_id))
    if job is not None and coins is not None:
        job["rh_coins"] = coins
    if status == "FAILED":
        detail = rh_failed_task_detail(task_id)
        suffix = f"；{detail}" if detail else ""
        raise ProviderTaskFailed(
            f"RH task failed: {r.get('errorCode')} {r.get('errorMessage')}{suffix}")
    return status, results


def backfill_rh_coins(job):
    """Fill billing metadata for one completed provider task at most once."""
    if job.get("rh_coins") not in (None, ""):
        return job["rh_coins"]
    if job.get("status") not in ("done", "error") or not job.get("rh_task_id"):
        return None
    if job.get("rh_coins_checked"):
        return None
    job["rh_coins_checked"] = True
    try:
        rh_query(job["rh_task_id"], job=job)
    except Exception:
        return job.get("rh_coins")
    return job.get("rh_coins")


def backfill_completed_rh_coins():
    changed = False
    with _lock_jobs:
        jobs = list(_jobs.values())
    for job in jobs:
        before = (job.get("rh_coins"), job.get("rh_coins_checked"))
        backfill_rh_coins(job)
        changed = changed or before != (job.get("rh_coins"), job.get("rh_coins_checked"))
    if changed:
        with _lock_jobs:
            save_jobs()

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
    query_failures = 0
    last_query_error = None
    while time.time() < deadline:
        try:
            status, results = rh_query(task_id, job=job)
            query_failures = 0
            last_query_error = None
        except ProviderTaskFailed:
            raise
        except Exception as error:
            query_failures += 1
            last_query_error = error
            job["provider_status"] = "QUERY_RETRY"
            job["status"] = "recovering"
            if query_failures == 1 or query_failures % 3 == 0:
                with _lock_jobs:
                    save_jobs()
            time.sleep(min(8, 2 ** min(query_failures, 3)))
            continue
        job["provider_status"] = status or "RUNNING"
        job["status"] = "running"
        fraction = RH_STAGE_PROGRESS.get(str(status or "RUNNING").upper(), 0.10)
        job["progress_pct"] = round(min(99, progress_base + progress_span * fraction))
        if status == "SUCCESS":
            if results:
                return results
            job["provider_status"] = "FINALIZING"
            time.sleep(4)
            continue
        time.sleep(8)
    detail = f": {last_query_error}" if last_query_error else ""
    raise ProviderStateUncertain(f"RH task state is still unconfirmed{detail}")


def _rh_results_to_images(results, task_id, stage_id=None, stage_label=None, result_labels=None):
    images = []
    labels = result_labels if isinstance(result_labels, list) else []
    for idx, im in enumerate(results, 1):
        url = im.get("url") or im.get("fileUrl") or ""
        if not url:
            continue
        if not isinstance(url, str) or any(ord(ch) < 32 or ch in "\"'<>`" for ch in url):
            continue
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme.lower() not in ("http", "https") or not parsed.netloc
                or parsed.username is not None or parsed.password is not None):
            continue
        url, display_name = _ascii_remote_url(url)
        if not url:
            continue
        parsed = urllib.parse.urlsplit(url)
        raw_type = str(im.get("file_type") or im.get("fileType") or im.get("outputType") or im.get("output_type") or im.get("type") or im.get("mimeType") or "").lower()
        suffix = pathlib.PurePosixPath(parsed.path).suffix.lower()
        is_image = raw_type.startswith("image/") or raw_type in {"png", "jpg", "jpeg", "webp", "gif", "avif"} or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
        images.append({
            "url": url,
            "preview_url": url + (("&" if "?" in url else "?") + "imageMogr2/thumbnail/640x640" if is_image else ""),
            "file_type": raw_type or suffix.lstrip(".") or "unknown",
            "remote": True,
            "file": display_name or pathlib.PurePosixPath(urllib.parse.unquote(parsed.path)).name or f"rh_{task_id}_{idx}.png",
            "size": None,
            "stage_id": stage_id,
            "stage_label": labels[idx - 1] if idx <= len(labels) else stage_label,
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


def downloaded_media_content_type(data, filename=""):
    image = image_content_type(data, filename)
    if image:
        return image
    suffix = pathlib.Path(str(filename or "")).suffix.lower()
    if len(data) >= 12 and data[4:8] == b"ftyp" and suffix in {".mp4", ".mov"}:
        return "video/quicktime" if suffix == ".mov" else "video/mp4"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI " and suffix == ".avi":
        return "video/x-msvideo"
    if data[:4] == b"\x1aE\xdf\xa3" and suffix in {".mkv", ".webm"}:
        return "video/webm" if suffix == ".webm" else "video/x-matroska"
    return None


def _safe_upload_filename(value):
    value = str(value or "")
    if (not value or len(value) > 255 or value in (".", "..")
            or pathlib.PurePath(value).name != value
            or "/" in value or "\\" in value
            or re.search(r"[\x00-\x1f\x7f\"']", value)):
        raise ValueError("unsafe upload filename")
    return value


def upload_media_content_type(data, filename, expected_type):
    """Validate media by magic/container bytes and require a matching suffix."""
    filename = _safe_upload_filename(filename)
    suffix = pathlib.Path(filename).suffix.lower()
    expected_type = str(expected_type or "").lower()
    if expected_type == "image":
        ctype = image_content_type(data, filename)
        allowed = {
            "image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"},
            "image/webp": {".webp"},
        }
        if not ctype or suffix not in allowed[ctype]:
            raise ValueError("invalid image media or extension")
        return ctype
    if expected_type != "video":
        raise ValueError("unsupported upload media type")
    if len(data) >= 12 and data[4:8] == b"ftyp" and suffix in {".mp4", ".mov"}:
        return "video/quicktime" if suffix == ".mov" else "video/mp4"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI " and suffix == ".avi":
        return "video/x-msvideo"
    if data[:4] == b"\x1aE\xdf\xa3" and suffix in {".mkv", ".webm"}:
        return "video/webm" if suffix == ".webm" else "video/x-matroska"
    raise ValueError("invalid video media or extension")


def validate_workflow_upload(workflow, input_key, filename, raw):
    mapping = (workflow.get("rh_media") or {}).get(str(input_key or ""))
    if not mapping:
        raise ValueError("unknown upload input")
    safe_name = _safe_upload_filename(filename)
    media_type = str(mapping.get("type") or "").lower()
    ctype = upload_media_content_type(raw, safe_name, media_type)
    return safe_name, ctype, media_type


def rh_build_ai_app_node_info(job, w):
    """Build only public editable fields from the trusted server config."""
    nodes = []
    for key, mapping in (w.get("rh_media") or {}).items():
        value = (job.get("provider_media") or {}).get(key)
        if value:
            nodes.append({"nodeId": str(mapping["node"]), "fieldName": mapping["field"], "fieldValue": value})
    for key, mapping in (w.get("rh_params") or {}).items():
        value = (job.get("params") or {}).get(key)
        if value is not None:
            nodes.append({"nodeId": str(mapping["node"]), "fieldName": mapping["field"], "fieldValue": str(value)})
    return nodes


def _coerce_rh_control(value, mapping):
    """Validate one declared workflow control and preserve its native type."""
    label = str(mapping.get("label") or mapping.get("field") or "参数")
    control_type = str(mapping.get("vtype") or mapping.get("type") or "text").lower()
    if control_type in ("text", "string", "textarea"):
        result = str(value)
        max_length = int(mapping.get("max_length", 10000))
        if len(result) > max_length:
            raise ValueError(f"{label}超过最大长度")
        return result
    if control_type in ("boolean", "bool", "switch"):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
        raise ValueError(f"{label}必须是开或关")
    if control_type in ("select", "enum", "combo"):
        result = str(value)
        options = []
        for option in mapping.get("options", []):
            if not isinstance(option, dict):
                option_value = option
            elif "value" in option:
                option_value = option["value"]
            elif "index" in option:
                option_value = option["index"]
            else:
                option_value = option.get("name", "")
            options.append(str(option_value))
        if options and result not in options:
            raise ValueError(f"{label}选项无效")
        return result
    if control_type in ("int", "integer"):
        if isinstance(value, bool):
            raise ValueError(f"{label}必须是整数")
        if isinstance(value, int):
            result = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError(f"{label}必须是整数")
            result = int(value)
        elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
            result = int(value.strip(), 10)
        else:
            raise ValueError(f"{label}必须是整数")
    elif control_type in ("float", "number"):
        if isinstance(value, bool):
            raise ValueError(f"{label}必须是数字")
        try:
            result = float(value)
            if not math.isfinite(result):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{label}必须是数字") from None
    else:
        raise ValueError(f"{label}控件类型不受支持")
    if mapping.get("min") is not None and result < mapping["min"]:
        raise ValueError(f"{label}低于最小值")
    if mapping.get("max") is not None and result > mapping["max"]:
        raise ValueError(f"{label}超过最大值")
    return result


def normalize_rh_workflow_inputs(w, media, params):
    """Whitelist and type-check inputs using one trusted workflow schema."""
    if not isinstance(media, dict) or not isinstance(params, dict):
        raise ValueError("media and params must be objects")
    trusted_media = {}
    for key, mapping in (w.get("rh_media") or {}).items():
        value = media.get(key)
        if value in (None, ""):
            if mapping.get("required"):
                raise ValueError(f"缺少必传素材：{mapping.get('label') or key}")
            continue
        trusted_media[key] = str(value)[:1000]
    trusted_params = {}
    for key, mapping in (w.get("rh_params") or {}).items():
        if key in params:
            value = params[key]
        elif "default" in mapping:
            value = mapping["default"]
        elif key in (w.get("params_defaults") or {}):
            value = w["params_defaults"][key]
        elif mapping.get("required"):
            raise ValueError(f"缺少必填参数：{mapping.get('label') or key}")
        else:
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            if mapping.get("allow_blank") and isinstance(value, str):
                trusted_params[key] = value
                continue
            if mapping.get("required"):
                raise ValueError(f"{mapping.get('label') or key}不能为空")
            continue
        result = _coerce_rh_control(value, mapping)
        if mapping.get("required") and isinstance(result, str) and not result.strip():
            raise ValueError(f"{mapping.get('label') or key}不能为空")
        trusted_params[key] = result
    return trusted_media, trusted_params


def rh_build_generic_node_info(job, w):
    """Serialize every declared generic control, including explicit false/0."""
    nodes = []
    for key, mapping in (w.get("rh_media") or {}).items():
        value = (job.get("provider_media") or {}).get(key)
        if value not in (None, ""):
            nodes.append({"nodeId": str(mapping["node"]),
                          "fieldName": mapping["field"], "fieldValue": value})
    for key, mapping in (w.get("rh_params") or {}).items():
        params = job.get("params") or {}
        if key not in params:
            continue
        if mapping.get("trusted_overrides"):
            branch = "true" if params[key] is True else "false"
            for override in mapping["trusted_overrides"].get(branch, []):
                nodes.append({"nodeId": str(override["node"]),
                              "fieldName": override["field"], "fieldValue": override["value"]})
            continue
        nodes.append({"nodeId": str(mapping["node"]),
                      "fieldName": mapping["field"], "fieldValue": params[key]})
    return nodes


def rh_run_generic(job, w):
    """Run one trusted schema-driven RunningHub workflow."""
    workflow_id = w.get("rh_workflow_id")
    if not workflow_id:
        raise RuntimeError("workflow has no trusted rh_workflow_id")
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit(workflow_id, rh_build_generic_node_info(job, w),
                        instance_type=w.get("rh_instance_type", "default"))
    persist_provider_task(job, task_id)
    job["progress_pct"] = 5
    results = _rh_wait_task(job, task_id, time.time() + 2400, 12, 88)
    job["provider_finished"] = time.time()
    images = _rh_results_to_images(results, task_id)
    if not images:
        raise RuntimeError("RH workflow succeeded but returned no downloadable result")
    job["images"] = images
    job["provider_status"] = "DONE"
    job["progress_pct"] = 100
    job["download_finished"] = time.time()
    return images

def schedule_cloud_recovery(job, delay=30):
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    with _recovery_jobs_lock:
        if job_id in _recovery_jobs:
            return
        _recovery_jobs.add(job_id)

    def worker():
        time.sleep(max(0, delay))
        with _recovery_jobs_lock:
            _recovery_jobs.discard(job_id)
        with _lock_jobs:
            current = _jobs.get(job_id)
        if current and current.get("status") == "recovering" and current.get("rh_task_id"):
            resume_cloud_job(current)

    threading.Thread(target=worker, daemon=True).start()


def resume_cloud_job(job):
    """Resume polling a persisted RunningHub task; never submit another task."""
    task_id = job.get("rh_task_id")
    if not task_id:
        raise RuntimeError("recovering cloud job has no provider task id")
    try:
        results = _rh_wait_task(job, task_id, time.time() + 2400, 12, 88)
        workflow = WORKFLOWS.get(job.get("workflow")) or {}
        images = _rh_results_to_images(
            results, task_id, result_labels=workflow.get("rh_result_labels"))
        if not images:
            raise RuntimeError("recovered task returned no downloadable result")
        job.update({"images": images, "status": "done", "provider_status": "DONE",
                    "progress_pct": 100, "provider_finished": time.time(),
                    "download_finished": time.time(), "error": None})
    except ProviderStateUncertain:
        job["status"] = "recovering"
        job["provider_status"] = "RECOVERING"
        job["error"] = None
        schedule_cloud_recovery(job)
    except Exception as error:
        job["status"] = "error"
        job["error"] = f"恢复云任务失败：{str(error)[:450]}"
    with _lock_jobs:
        save_jobs()


def rh_run_ai_app(job, w):
    app_id = w.get("rh_ai_app_id")
    if not app_id:
        raise RuntimeError("AI App has no trusted app id")
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit_ai_app(app_id, rh_build_ai_app_node_info(job, w))
    persist_provider_task(job, task_id)
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


def rh_run(job, jobdir, w):
    """RunningHub 后端执行：提交→轮询→下载"""
    wfid = w.get("rh_workflow_id")
    if not wfid:
        raise RuntimeError("workflow has no rh_workflow_id")
    node_list = rh_build_node_info(job)
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    task_id = rh_submit(wfid, node_list)
    persist_provider_task(job, task_id)
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


def _bounded_request_int(value, default=0, max_digits=20):
    """Parse a small HTTP integer without constructing attacker-sized Python ints."""
    if value in (None, ""):
        return int(default)
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple)):
        raise ValueError("invalid integer")
    if isinstance(value, int):
        if abs(value).bit_length() > 64:
            raise ValueError("integer too large")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer() or abs(value) > 2**63 - 1:
            raise ValueError("invalid integer")
        return int(value)
    text = str(value).strip()
    if len(text) > max_digits + 1 or not re.fullmatch(r"[+-]?\d+", text):
        raise ValueError("invalid integer")
    return int(text, 10)


def _dreamapi_size(width, height):
    width = _bounded_request_int(width)
    height = _bounded_request_int(height)
    if width <= 0 or height <= 0:
        raise ValueError("API width and height must be positive")
    pixels = width * height
    ratio = max(width, height) / min(width, height)
    if width % 16 or height % 16:
        raise ValueError("API width and height must be multiples of 16")
    if width > 3840 or height > 3840 or ratio > 3:
        raise ValueError("API size is outside the supported dimensions")
    if not 655360 <= pixels <= 8294400:
        raise ValueError("API total pixels are outside the supported range")
    return f"{width}x{height}"


def _dreamapi_redact_error(detail):
    detail = str(detail or "upstream error")
    if DREAMAPI_KEY:
        detail = detail.replace(DREAMAPI_KEY, "[REDACTED]")
    detail = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1[REDACTED]", detail)
    detail = re.sub(r"(?i)((?:api[_ -]?key|token|secret)\s*[:=]?\s*)[A-Za-z0-9._~+/=-]{8,}", r"\1[REDACTED]", detail)
    return re.sub(r"[\x00-\x1f\x7f]+", " ", detail).strip()[:500]


def _dreamapi_request_endpoint():
    if not DREAMAPI_EGRESS_URL:
        return DREAMAPI_BASE_URL + "/responses"
    parsed = urllib.parse.urlparse(DREAMAPI_EGRESS_URL)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise RuntimeError("DREAMAPI_EGRESS_URL must be a loopback HTTP endpoint")
    return DREAMAPI_EGRESS_URL


def compact_dreamapi_prompts(positive, negative, max_total=1600):
    """Deterministically bound Sub2API input while preserving priority order."""
    positive = str(positive or "").strip()
    negative = str(negative or "").strip()
    if len(positive) + len(negative) <= max_total:
        return positive, negative, False

    def phrases(text):
        seen = set()
        rows = []
        for part in re.split(r"[,\n]+", text):
            item = re.sub(r"\s+", " ", part).strip(" ,")
            key = item.casefold()
            if item and key not in seen:
                rows.append(item)
                seen.add(key)
        return rows

    def fit(rows, budget):
        kept = []
        used = 0
        for item in rows:
            extra = len(item) + (2 if kept else 0)
            if used + extra > budget:
                if not kept and budget > 0:
                    kept.append(item[:budget].rstrip())
                break
            kept.append(item)
            used += extra
        return ", ".join(kept)

    negative_budget = min(max_total // 4, max(200, len(negative)))
    positive_budget = max_total - negative_budget
    compact_positive = fit(phrases(positive), positive_budget)
    compact_negative = fit(phrases(negative), max_total - len(compact_positive))
    return compact_positive, compact_negative, True


def build_dreamapi_input(positive, negative, size, orientation, max_total=1600):
    """Build the complete bounded upstream input, including bridge instructions."""
    prefix = [
        f"Required canvas: exactly {size}, {orientation} composition.",
        "Keep the important subject inside the center safe area so a final crop will not cut it off.",
    ]
    bridge_overhead = len("\n".join(prefix)) + 1
    negative_overhead = len("\nAvoid: ") if str(negative or "").strip() else 0
    prompt_budget = max(1, max_total - bridge_overhead - negative_overhead)
    positive_out, negative_out, compacted = compact_dreamapi_prompts(
        positive, negative, max_total=prompt_budget)
    if not any(char.isalnum() for char in positive_out):
        raise ValueError("DreamAPI subject prompt is empty after normalization")
    rows = [*prefix, positive_out]
    if negative_out:
        rows.append("Avoid: " + negative_out)
    text = "\n".join(rows)
    if len(text) > max_total:
        raise RuntimeError("DreamAPI prompt compaction exceeded its input budget")
    return text, compacted, len(positive_out)


def _dreamapi_read_json(response):
    chunks, total = [], 0
    while True:
        chunk = response.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > DREAMAPI_MAX_RESPONSE_BYTES:
            raise RuntimeError("DreamAPI response is too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("DreamAPI returned malformed response") from error


def _dreamapi_request_json(request, data, timeout):
    """Bound connect plus the complete response body by one wall-clock deadline."""
    box = {}

    def worker():
        try:
            with _urlopen_bounded(request, data, timeout) as response:
                box["result"] = _dreamapi_read_json(response)
        except urllib.error.HTTPError as error:
            raw = error.read(8192)
            try:
                body = json.loads(raw.decode("utf-8", "replace"))
                detail = str((body.get("error") or {}).get("message") or body.get("message") or error.reason)
            except Exception:
                detail = str(error.reason or "upstream error")
            box["error"] = RuntimeError(
                f"DreamAPI HTTP {error.code}: {_dreamapi_redact_error(detail)}"
            )
        except Exception as error:
            box["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"DreamAPI hard timeout after {timeout}s")
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise RuntimeError("DreamAPI request ended without a response")
    return box["result"]


def dreamapi_run_image(job, jobdir):
    """Generate one image with DreamAPI Responses and archive an exact-size PNG."""
    if not DREAMAPI_KEY:
        raise RuntimeError("DREAMAPI_KEY is not configured")
    model = str(job.get("api_model") or "gpt-image-2.5-flare")
    quality = str(job.get("api_quality") or "medium")
    fit = str(job.get("api_fit") or "cover")
    if model not in DREAMAPI_IMAGE_QUALITIES:
        raise ValueError("unknown DreamAPI image model")
    if quality not in DREAMAPI_IMAGE_QUALITIES[model]:
        raise ValueError("quality is not supported by the DreamAPI image model")
    if fit not in {"cover", "contain"}:
        raise ValueError("unknown DreamAPI fit mode")
    size = _dreamapi_size(job["width"], job["height"])
    orientation = "square" if job["width"] == job["height"] else (
        "landscape" if job["width"] > job["height"] else "portrait")
    upstream_input, compacted, positive_chars = build_dreamapi_input(
        job.get("prompt"), job.get("negative_prompt"), size, orientation)
    job["api_prompt_compacted"] = compacted
    job["api_upstream_prompt_chars"] = positive_chars
    tool = {
        "type": "image_generation", "model": model,
        "size": size, "quality": quality,
    }
    if model in DREAMAPI_IMAGE_ACTION_MODELS:
        tool["action"] = "generate"
    payload = {
        "model": DREAMAPI_TEXT_MODEL,
        "instructions": DREAMAPI_DISPATCH_INSTRUCTIONS,
        "input": upstream_input,
        "stream": False,
        "tools": [tool],
    }
    request = urllib.request.Request(
        _dreamapi_request_endpoint(),
        headers={"Authorization": f"Bearer {DREAMAPI_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    job["provider_status"] = "API_GENERATING"
    job["provider_started"] = time.time()
    result = _dreamapi_request_json(
        request, json.dumps(payload).encode("utf-8"), DREAMAPI_TIMEOUT
    )
    if not isinstance(result, dict) or not isinstance(result.get("output"), list):
        raise RuntimeError("DreamAPI returned malformed response")
    if any(not isinstance(item, dict) for item in result["output"]):
        raise RuntimeError("DreamAPI returned malformed response")
    image_item = next((item for item in result["output"]
                       if isinstance(item, dict)
                       and item.get("type") == "image_generation_call"
                       and isinstance(item.get("result"), str) and item.get("result")), None)
    if not image_item:
        raise RuntimeError("DreamAPI returned no completed image")
    encoded = image_item["result"]
    if len(encoded) > ((DREAMAPI_MAX_IMAGE_BYTES + 2) // 3) * 4 + 4:
        raise RuntimeError("DreamAPI image data is too large")
    try:
        source = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise RuntimeError("DreamAPI returned invalid image data") from error
    if len(source) > DREAMAPI_MAX_IMAGE_BYTES:
        raise RuntimeError("DreamAPI image data is too large")
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        opened = Image.open(io.BytesIO(source))
    except (UnidentifiedImageError, OSError) as error:
        raise RuntimeError("DreamAPI returned undecodable image data") from error
    with opened as decoded:
        if decoded.width <= 0 or decoded.height <= 0 or decoded.width * decoded.height > DREAMAPI_MAX_SOURCE_PIXELS:
            raise RuntimeError("DreamAPI source image dimensions are too large")
        if decoded.format not in {"PNG", "JPEG", "WEBP"}:
            raise RuntimeError("DreamAPI returned unsupported image format")
        try:
            decoded.load()
        except Exception as error:
            raise RuntimeError("DreamAPI returned invalid image data") from error
        source_size = f"{decoded.width}x{decoded.height}"
        converted = decoded.convert("RGB")
        target = (int(job["width"]), int(job["height"]))
        if fit == "cover":
            output = ImageOps.fit(converted, target, method=Image.Resampling.LANCZOS,
                                  centering=(0.5, 0.5))
        else:
            output = ImageOps.contain(converted, target, method=Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", target, "white")
            canvas.paste(output, ((target[0] - output.width) // 2, (target[1] - output.height) // 2))
            output = canvas
        jobdir = pathlib.Path(jobdir)
        jobdir.mkdir(parents=True, exist_ok=True)
        filename = "dreamapi.png"
        destination = jobdir / filename
        output.save(destination, "PNG", optimize=True)
    job.update({
        "api_response_id": str(result.get("id") or ""),
        "api_upstream_model": str(image_item.get("model") or "unknown"),
        "api_upstream_quality": str(image_item.get("quality") or "unknown"),
        "api_upstream_size": str(image_item.get("size") or "unknown"),
        "provider_finished": time.time(), "download_finished": time.time(),
        "provider_status": "API_DONE", "progress_pct": 100,
        "images": [{
            "url": f"/api/image/{job['id']}/{filename}",
            "preview_url": f"/api/image/{job['id']}/{filename}",
            "file": filename, "size": destination.stat().st_size, "remote": False,
            "source_size": source_size, "output_size": size, "archive_status": "ready",
        }],
    })
    return job["images"]


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
        lora_strengths=job.get("lora_strengths") or {},
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


def rh_upload_file(data, filename, ctype="application/octet-stream", timeout=120):
    """Upload a binary (image/video) to RunningHub. Returns the RH fileName
    (relative path) to be placed into LoadImage/LoadVideo fieldValue."""
    boundary = "----rh" + uuid.uuid4().hex
    safe_suffix = pathlib.Path(_safe_upload_filename(filename)).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", safe_suffix):
        raise ValueError("unsafe upload extension")
    provider_filename = "upload_" + uuid.uuid4().hex + safe_suffix
    def _field(name, val):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{val}\r\n").encode()
    def _file(name, fname, ctype_):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{fname}\"\r\nContent-Type: {ctype_}\r\n\r\n").encode()
    body = b"".join([
        _field("apiKey", RH_KEY),
        _field("fileType", "input"),
        _file("file", provider_filename, ctype),
        data, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {RH_KEY}",
    }
    req = urllib.request.Request("https://www.runninghub.cn/task/openapi/upload",
                                 data=body, headers=headers)
    resp = _provider_json_request(req, timeout=timeout)
    if resp.get("code") != 0:
        raise RuntimeError(f"RH upload failed: {resp.get('code')} {resp.get('msg')}")
    fname = (resp.get("data") or {}).get("fileName")
    if not isinstance(fname, str) or not re.fullmatch(r"api/[A-Za-z0-9._/-]{1,900}", fname):
        raise RuntimeError("RH upload returned no fileName")
    if ".." in pathlib.PurePosixPath(fname).parts:
        raise RuntimeError("RH upload returned unsafe fileName")
    return fname


def rh_build_video_node_info(job, w):
    """Build RunningHub nodeInfoList for a video workflow.

    Job fields: prompt, negative_prompt, media = {key: fileName}, params = {key: value}.
    Mapping comes from the workflow config: w["rh_media"] (key->{node,field,type,label})
    and w["rh_params"] (key->{node,field,type,label}). Prompt/negative also declared
    as rh_params entries so the generic loop covers everything.
    """
    node_list = []
    media_map = w.get("rh_media") or {}
    for key, m in media_map.items():
        media = job.get("provider_media") or {}
        fname = media.get(key) or media.get(m.get("fallback_to"))
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
        overrides = (m.get("trusted_overrides") or {}).get(str(val).lower())
        if overrides is None:
            overrides = (m.get("trusted_overrides") or {}).get(str(val))
        if overrides is not None:
            for override in overrides:
                node_list.append({"nodeId": str(override["node"]), "fieldName": override["field"], "fieldValue": override["value"]})
        if m.get("node") is not None and m.get("field"):
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
    persist_provider_task(job, task_id)
    job["progress_pct"] = 5
    images = []
    deadline = time.time() + 2400
    while time.time() < deadline:
        results = _rh_wait_task(job, task_id, deadline, 12, 88)
        if results:
            job["provider_finished"] = time.time()
            job["provider_status"] = "DONE"
            job["progress_pct"] = 100
            images = _rh_results_to_images(
                results, task_id, result_labels=w.get("rh_result_labels"))
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
            elif w.get("kind") == "rh_workflow":
                rh_run_generic(job, w)
            else:
                rh_run(job, jobdir, w)
            job["status"] = "done"
            job["progress_pct"] = 100
        elif generation_backend == "local":
            local_run_image(job, jobdir, w)
            job["status"] = "done"
            job["progress_pct"] = 100
            job["provider_status"] = "LOCAL_DONE"
        elif generation_backend == "api":
            dreamapi_run_image(job, jobdir)
            job["status"] = "done"
            job["progress_pct"] = 100
        else:
            raise RuntimeError("unknown generation backend")
    except ProviderStateUncertain:
        job["status"] = "recovering"
        job["provider_status"] = "RECOVERING"
        job["error"] = None
        schedule_cloud_recovery(job)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:500]
        if job.get("generation_backend") == "api":
            job["provider_status"] = "API_ERROR"
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


def json_body_limit(path):
    return MAX_UPLOAD_JSON_BYTES if path == "/api/upload" else MAX_JSON_BYTES


def safe_child_path(root, *parts):
    """Resolve a path and prove it remains below root, not a prefix sibling."""
    root = pathlib.Path(root).resolve()
    candidate = root.joinpath(*map(pathlib.Path, parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("bad path") from None
    return candidate


def safe_output_filename(value):
    """Accept one plain ComfyUI basename, never a path supplied downstream."""
    value = str(value or "")
    if not value or value in (".", "..") or pathlib.PurePath(value).name != value:
        raise ValueError("bad output filename")
    if "/" in value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise ValueError("bad output filename")
    return value


class BoundedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = HTTP_REQUEST_BACKLOG
    max_workers = MAX_HTTP_WORKERS

    def __init__(self, *args, **kwargs):
        self._worker_slots = threading.BoundedSemaphore(self.max_workers)
        self._rejection_slots = threading.BoundedSemaphore(MAX_REJECTION_WORKERS)
        self._large_response_slots = threading.BoundedSemaphore(MAX_LARGE_RESPONSE_WORKERS)
        self._large_request_slots = threading.BoundedSemaphore(MAX_LARGE_REQUESTS)
        self._metrics_lock = threading.Lock()
        self._active_workers = 0
        self._active_rejections = 0
        self._active_large_responses = 0
        self._overload_rejections = 0
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        # Never block the accept loop waiting for a worker. A slow-client wave
        # must receive a bounded 503 instead of filling the kernel listen queue.
        if not self._worker_slots.acquire(blocking=False):
            with self._metrics_lock:
                self._overload_rejections += 1
            if not self._rejection_slots.acquire(blocking=False):
                request.close()
                return
            threading.Thread(
                target=self._send_overload_response,
                args=(request,),
                daemon=True,
            ).start()
            return
        with self._metrics_lock:
            self._active_workers += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            with self._metrics_lock:
                self._active_workers -= 1
            self._worker_slots.release()
            raise

    def _send_overload_response(self, request):
        with self._metrics_lock:
            self._active_rejections += 1
        try:
            # Read only an already-sent request header, and for at most 100 ms.
            # Graceful close after draining prevents Windows from replacing the
            # 503 response with a TCP RST while keeping the accept loop free.
            request.settimeout(OVERLOAD_DRAIN_TIMEOUT)
            received = b""
            header_end = bytes((13, 10, 13, 10))
            while (len(received) < MAX_OVERLOAD_HEADER_BYTES and
                   header_end not in received):
                try:
                    chunk = request.recv(min(4096, MAX_OVERLOAD_HEADER_BYTES - len(received)))
                except (socket.timeout, OSError):
                    break
                if not chunk:
                    break
                received += chunk
            newline = bytes((13, 10))
            body = b'{"ok":false,"service":"comfy-panel","overloaded":true}'
            response = newline.join((
                b"HTTP/1.0 503 Service Unavailable",
                b"Connection: close",
                b"Retry-After: 1",
                b"Content-Type: application/json",
                f"Content-Length: {len(body)}".encode("ascii"),
                b"",
                body,
            ))
            request.sendall(response)
            try:
                request.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        except OSError:
            pass
        finally:
            request.close()
            with self._metrics_lock:
                self._active_rejections -= 1
            self._rejection_slots.release()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._metrics_lock:
                self._active_workers -= 1
            self._worker_slots.release()

    def liveness_snapshot(self):
        with self._metrics_lock:
            return {
                "active_workers": self._active_workers,
                "max_workers": self.max_workers,
                "active_rejections": self._active_rejections,
                "max_rejection_workers": MAX_REJECTION_WORKERS,
                "active_large_responses": self._active_large_responses,
                "max_large_response_workers": MAX_LARGE_RESPONSE_WORKERS,
                "overload_rejections": self._overload_rejections,
            }

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(CLIENT_SOCKET_TIMEOUT)
        return request, client_address

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout, TimeoutError)):
            return
        super().handle_error(request, client_address)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a): pass

    def _upload_session(self, create=False):
        session_id = ""
        refresh = False
        try:
            cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            encoded = cookie.get("jt_session").value if cookie.get("jt_session") else ""
            session_id, refresh = _decode_session_cookie_details(encoded)
        except (http.cookies.CookieError, AttributeError):
            session_id = ""
        if not session_id and create:
            session_id = secrets.token_urlsafe(32)
            refresh = True
        if session_id and refresh:
            encoded = _encode_session_cookie(session_id)
            return session_id, (f"jt_session={encoded}; Path=/; Max-Age={SESSION_COOKIE_TTL}; "
                                "HttpOnly; SameSite=Strict")
        return session_id, None

    def _require_session(self):
        session_id, _ = self._upload_session(create=False)
        if not session_id:
            self._send(428, json.dumps({
                "error": "open the panel page before submitting a generation task",
            }).encode())
            return ""
        return session_id

    def _upload_quota_rejection(self, status):
        if not status:
            return False
        payload = {
            "error": "public upload limit reached; please wait before uploading another media file",
            "scope": status["scope"],
            "retry_after": status["retry_after"],
        }
        self._send(429, json.dumps(payload).encode(),
                   headers={"Retry-After": str(status["retry_after"])})
        return True

    def _billable_quota_rejection(self, status):
        if not status:
            return False
        payload = {
            "error": "public billable task limit reached; please wait before submitting a new paid task",
            "quota": {key: status[key] for key in ("global_hour", "global_day", "session_hour")},
        }
        self._send(429, json.dumps(payload).encode(),
                   headers={"Retry-After": str(status["retry_after"])})
        return True

    def _start_absolute_deadline(self, seconds):
        state = {"expired": False, "armed": True, "lock": threading.Lock()}

        def expire():
            with state["lock"]:
                if not state["armed"]:
                    return
                state["expired"] = True
                state["armed"] = False
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(max(0.01, float(seconds)), expire)
        timer.daemon = True
        timer.start()
        return timer, state

    @staticmethod
    def _cancel_absolute_deadline(deadline):
        if deadline:
            timer, state = deadline
            with state["lock"]:
                state["armed"] = False
            timer.cancel()

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            # The header deadline starts before the request line is read and
            # ends only after all headers have been parsed.
            self._cancel_absolute_deadline(getattr(self, "_header_deadline", None))
            self._header_deadline = None

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError,
                socket.timeout, TimeoutError):
            # Browsers, probes and deliberately slow clients routinely close
            # sockets mid-request. This is expected client behaviour, not a
            # server fault, so keep production stderr free of tracebacks.
            self.close_connection = True

    def handle_one_request(self):
        self._header_deadline = self._start_absolute_deadline(REQUEST_HEADER_TIMEOUT)
        try:
            super().handle_one_request()
        finally:
            self._cancel_absolute_deadline(getattr(self, "_header_deadline", None))
            self._header_deadline = None
            if MAX_REQUESTS_PER_CONNECTION == 1:
                self.close_connection = True

    def finish(self):
        try:
            super().finish()
        finally:
            if getattr(self, "_large_request_slot_acquired", False):
                self._large_request_slot_acquired = False
                self.server._large_request_slots.release()

    def _write_body(self, body, large_slot_acquired=False):
        if not body:
            return
        is_large = len(body) >= LARGE_RESPONSE_THRESHOLD
        acquired_here = False
        if is_large and not large_slot_acquired:
            if not self.server._large_response_slots.acquire(blocking=False):
                raise RuntimeError("large response capacity busy")
            acquired_here = True
        deadline = None
        if is_large:
            with self.server._metrics_lock:
                self.server._active_large_responses += 1
        try:
            if is_large:
                self.connection.settimeout(RESPONSE_SOCKET_TIMEOUT)
                timeout = min(
                    RESPONSE_BODY_MAX_TIMEOUT,
                    RESPONSE_BODY_BASE_TIMEOUT + len(body) / RESPONSE_BODY_MIN_BYTES_PER_SECOND,
                )
                deadline = self._start_absolute_deadline(timeout)
            self.wfile.write(body)
        finally:
            self._cancel_absolute_deadline(deadline)
            if is_large:
                self.connection.settimeout(CLIENT_SOCKET_TIMEOUT)
                with self.server._metrics_lock:
                    self.server._active_large_responses -= 1
                if acquired_here:
                    self.server._large_response_slots.release()

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
        is_large = len(body) >= LARGE_RESPONSE_THRESHOLD
        large_slot_acquired = False
        if is_large:
            large_slot_acquired = self.server._large_response_slots.acquire(blocking=False)
        if is_large and not large_slot_acquired:
            payload = b'{"error":"large response capacity busy"}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Retry-After", "2")
            self.end_headers()
            self.wfile.write(payload)
            return
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if headers:
                for k, v in headers.items(): self.send_header(k, v)
            self.end_headers()
            self._write_body(body, large_slot_acquired=large_slot_acquired)
        finally:
            if large_slot_acquired:
                self.server._large_response_slots.release()

    def _write_stream(self, path, ctype, download_name=None, cache_control="private, max-age=3600"):
        path = pathlib.Path(path)
        # Open first so a stat/open race cannot produce a 200 header followed
        # by a second 404 response.
        with path.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            is_large = size >= LARGE_RESPONSE_THRESHOLD
            slot = False
            if is_large:
                slot = self.server._large_response_slots.acquire(blocking=False)
            if is_large and not slot:
                return self._send(503, b'{"error":"large response capacity busy"}', headers={"Retry-After": "2"})
            deadline = None
            if is_large:
                with self.server._metrics_lock:
                    self.server._active_large_responses += 1
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                if download_name:
                    self.send_header("Content-Disposition", f'inline; filename="{download_name}"')
                self.send_header("Cache-Control", cache_control)
                self.end_headers()
                if is_large:
                    self.connection.settimeout(RESPONSE_SOCKET_TIMEOUT)
                    timeout = min(
                        RESPONSE_BODY_MAX_TIMEOUT,
                        RESPONSE_BODY_BASE_TIMEOUT + size / RESPONSE_BODY_MIN_BYTES_PER_SECOND,
                    )
                    deadline = self._start_absolute_deadline(timeout)
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            finally:
                self._cancel_absolute_deadline(deadline)
                if is_large:
                    self.connection.settimeout(CLIENT_SOCKET_TIMEOUT)
                    with self.server._metrics_lock:
                        self.server._active_large_responses -= 1
                    self.server._large_response_slots.release()

    def _send_static(self, fp, ctype):
        """Serve text assets with validator caching and bounded gzip."""
        raw = fp.read_bytes()
        etag = '"' + hashlib.sha256(raw).hexdigest()[:24] + '"'
        cache = "no-cache, must-revalidate" if fp.suffix == ".html" else "public, max-age=3600, must-revalidate"
        _, cookie_header = self._upload_session(create=True) if fp.suffix == ".html" else ("", None)
        request = urllib.parse.urlparse(self.path)
        if request.path.startswith("/static/previews/") and fp.suffix == ".webp" and re.fullmatch(r"v=[0-9a-f]{12}", request.query):
            cache = "public, max-age=31536000, immutable"
        if self.headers.get("If-None-Match") == etag:
            self.send_response(http.HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.send_header("Vary", "Accept-Encoding")
            if cookie_header:
                self.send_header("Set-Cookie", cookie_header)
            self.end_headers()
            return
        body = raw
        response_headers = {"ETag": etag, "Cache-Control": cache, "Vary": "Accept-Encoding"}
        if cookie_header:
            response_headers["Set-Cookie"] = cookie_header
        accepted = self.headers.get("Accept-Encoding", "").lower()
        if "gzip" in accepted and len(raw) >= 1024 and ctype.startswith(("text/", "application/javascript")):
            body = gzip.compress(raw, compresslevel=6, mtime=0)
            response_headers["Content-Encoding"] = "gzip"
        self._send(200, body, ctype, response_headers)

    def _auth(self):
        # 令牌鉴权已取消（用户要求 8189 直接免登录使用）
        return True

    def _management_auth(self):
        if not PANEL_RELEASE_TOKEN:
            return False
        header = str(self.headers.get("Authorization") or "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return secrets.compare_digest(header[len(prefix):], PANEL_RELEASE_TOKEN)

    def _release_in_progress(self):
        return self._send(503, json.dumps({
            "error": "release_in_progress",
            "code": "release_in_progress",
        }).encode(), headers={"Retry-After": "30"})

    def _release_state(self):
        return {
            "draining": bool(_release_draining),
            "cloud_busy": self._running_job_id("cloud") is not None,
            "local_busy": self._running_job_id("local") is not None,
            "api_busy": self._running_job_id("api") is not None,
        }

    def _read_json(self, limit=MAX_JSON_BYTES):
        n = int(self.headers.get("Content-Length", 0))
        if n < 0 or n > limit:
            raise OverflowError("request body too large")
        timeout = min(
            REQUEST_BODY_MAX_TIMEOUT,
            REQUEST_BODY_BASE_TIMEOUT + n / REQUEST_BODY_MIN_BYTES_PER_SECOND,
        )
        deadline = self._start_absolute_deadline(timeout)
        try:
            raw = self.rfile.read(n)
        finally:
            self._cancel_absolute_deadline(deadline)
        if len(raw) != n:
            if deadline[1]["expired"]:
                raise TimeoutError("request body deadline exceeded")
            raise ValueError("incomplete request body")
        return json.loads(raw.decode())

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/live":
            payload = {"ok": True, "service": "comfy-panel", **self.server.liveness_snapshot()}
            self._send(200, json.dumps(payload, separators=(",", ":")).encode())
        elif path == "/api/health":
            ok, msg = comfy_ok()
            self._send(200, json.dumps({"ok": ok, "comfy": bool(ok), "local_comfy_ok": ok,
                                        "dreamapi_configured": bool(DREAMAPI_KEY),
                                        "dreamapi_workstation_egress": bool(DREAMAPI_EGRESS_URL),
                                        "draining": bool(_release_draining),
                                        "cloud_busy": self._running_job_id("cloud") is not None,
                                        "local_busy": self._running_job_id("local") is not None,
                                        "api_busy": self._running_job_id("api") is not None}).encode())
        elif path == "/api/comfy/status":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            ok, control_ok, detail = comfy_status_detail()
            self._send(200, json.dumps({"comfy_ok": ok, "control_ok": control_ok,
                                        "detail": "ready" if ok else "unavailable"}).encode())
        elif path == "/api/workflows":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            lst = [public_workflow(w) for w in WORKFLOWS.values()]
            _, cookie_header = self._upload_session(create=True)
            headers = {"Set-Cookie": cookie_header} if cookie_header else None
            self._send(200, json.dumps(lst, ensure_ascii=False).encode(), headers=headers)
        elif path == "/api/loras":
            if not self._management_auth():
                return self._send(401, b'{"error":"management authorization required"}')
            self._send(200, json.dumps({"loras": get_lora_list()}).encode())
        elif path == "/api/favorites":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id, _ = self._upload_session(create=False)
            with _lock_jobs:
                items = [public_favorite(item) for item in sorted(
                    _favorites.values(), key=lambda x: x.get("created", 0), reverse=True)
                    if session_owns_record(session_id, item, "owner_session_hash")]
            self._send(200, json.dumps(items, ensure_ascii=False).encode())
        elif path.startswith("/api/favorite-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            fid = path.split("/api/favorite-preview/", 1)[1]
            with _lock_jobs: fav = _favorites.get(fid)
            session_id, _ = self._upload_session(create=False)
            if not fav or not session_owns_record(session_id, fav, "owner_session_hash"):
                return self._send(404, b'{"error":"favorite not found"}')
            if str(fav.get("favorite_media_type") or "").startswith("video/"):
                return self._send(415, b'{"error":"video favorites do not have image previews"}')
            try:
                src = safe_child_path(FAVORITES_DIR, pathlib.Path(fav.get("image_path", "")))
            except ValueError:
                return self._send(403, b'{"error":"bad path"}')
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
            session_id, _ = self._upload_session(create=False)
            if not fav or not session_owns_record(session_id, fav, "owner_session_hash"):
                return self._send(404, b'{"error":"favorite not found"}')
            try:
                p = safe_child_path(FAVORITES_DIR, pathlib.Path(fav.get("image_path", "")))
            except ValueError:
                return self._send(403, b'{"error":"bad path"}')
            if not p.exists(): return self._send(404, b'{"error":"favorite image missing"}')
            data = p.read_bytes()
            ctype = fav.get("favorite_media_type") or image_content_type(data, p.name) or "application/octet-stream"
            self._send(200, data, ctype, {"Cache-Control": "private, max-age=86400"})
        elif path.startswith("/api/job/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            jid = path.split("/api/job/", 1)[1]
            with _lock_jobs:
                src = _jobs.get(jid)
                session_id, _ = self._upload_session(create=False)
                if not src or not session_owns_record(session_id, src):
                    return self._send(404, b'{"error":"job not found"}')
                allowed = (
                    "id", "workflow", "status", "provider_status",
                    "progress_pct", "error", "elapsed", "created", "wf_name", "rh_coins",
                    "width", "height", "batch", "hd", "images",
                    "submit_started", "provider_started", "provider_finished",
                    "download_started", "download_finished", "selection_snapshot",
                    "prompt_mode", "seed", "seed_mode", "style_id", "style_variant", "mode",
                    "sequence_mode", "sequence_seed", "stage_status", "generation_backend",
                    "seed_supported", "api_model", "api_quality", "api_fit", "api_ratio",
                    "api_prompt_compacted", "api_upstream_prompt_chars",
                    "api_upstream_model", "api_upstream_quality", "api_upstream_size",
                    "media", "params",
                    "client_request_id",
                    "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                )
                j = {k: src.get(k) for k in allowed}
                j["error"] = public_job_error(src)
                j["media"] = public_job_media(src.get("media"))
                j["params"] = public_job_params(src)
                j["selection_snapshot"] = public_job_selection_snapshot(src.get("selection_snapshot"))
            self._send(200, json.dumps(j, ensure_ascii=False).encode())
        elif path == "/api/jobs":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            with _lock_jobs:
                # Lightweight copies: prompts can be many KB and are not used by
                # history/status UI. Omitting them cuts /api/jobs from ~60KB to
                # a few KB and prevents slow mobile polling/timeouts.
                items = []
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                scope = (query.get("scope") or [None])[0]
                style = (query.get("style") or [None])[0]
                session_id, _ = self._upload_session(create=False)
                owned_sources = [src for src in _jobs.values()
                                 if session_owns_record(session_id, src)]
                sources = scoped_history_jobs(owned_sources, scope, style)
                for src in sources:
                    allowed = (
                        "id", "workflow", "status", "provider_status",
                        "progress_pct", "error", "elapsed", "created", "wf_name", "rh_coins",
                        "width", "height", "batch", "hd", "images",
                        "submit_started", "provider_started", "provider_finished",
                        "download_started", "download_finished", "selection_snapshot",
                        "style_id", "style_variant", "mode", "seed", "seed_mode", "prompt_mode",
                        "sequence_mode", "sequence_seed", "stage_status", "generation_backend",
                        "seed_supported", "api_model", "api_quality", "api_fit", "api_ratio",
                        "api_prompt_compacted", "api_upstream_prompt_chars",
                        "api_upstream_model", "api_upstream_quality", "api_upstream_size",
                        "client_request_id",
                        "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                    )
                    j = {k: src.get(k) for k in allowed}
                    j["error"] = public_job_error(src)
                    j["media"] = public_job_media(src.get("media"))
                    j["selection_snapshot"] = public_job_selection_snapshot(src.get("selection_snapshot"))
                    items.append(j)
            self._send(200, json.dumps(items, ensure_ascii=False).encode())
        elif path.startswith("/api/local-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/local-preview/", 1)[1]
                jobid, fname = rest.split("/", 1)
                session_id, _ = self._upload_session(create=False)
                with _lock_jobs:
                    job = _jobs.get(jobid)
                if not job or not session_owns_record(session_id, job):
                    return self._send(404, b'{"error":"preview not found"}')
                p = safe_child_path(JOBS_DIR / jobid, fname)
                data = p.read_bytes()
                self._send(200, data, "image/webp", {"Cache-Control": "private, max-age=86400"})
            except ValueError:
                self._send(403, b'{"error":"bad path"}')
            except FileNotFoundError:
                self._send(404, b'{"error":"preview not found"}')
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as error:
                self._send(500, b'{"error":"preview temporarily unavailable"}')
        elif path.startswith("/api/preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/preview/", 1)[1]
                jobid, fname = rest.split("/", 1)
                session_id, _ = self._upload_session(create=False)
                with _lock_jobs:
                    job = _jobs.get(jobid)
                if not job or not session_owns_record(session_id, job):
                    return self._send(404, b'{"error":"not found"}')
                jobroot = (JOBS_DIR / jobid).resolve()
                src = safe_child_path(jobroot, fname)
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
            except ValueError:
                self._send(403, b'{"error":"bad path"}')
            except ImportError:
                self._send(501, b'{"error":"preview backend unavailable"}')
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                self._send(500, b'{"error":"preview temporarily unavailable"}')
        elif path.startswith("/api/rh-preview/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            # On-demand thumbnail for remote RunningHub result. It is NOT part
            # of job completion and never holds the generation lock.
            try:
                rest = path.split("/api/rh-preview/", 1)[1]
                jobid, idx_s = rest.split("/", 1)
                idx = int(idx_s)
                session_id, _ = self._upload_session(create=False)
                with _lock_jobs:
                    job = _jobs.get(jobid)
                    images = list((job or {}).get("images") or [])
                if (not session_owns_record(session_id, job)
                        or idx < 0 or idx >= len(images) or not images[idx].get("remote")):
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
                self._send(500, b'{"error":"preview temporarily unavailable"}')
        elif path.startswith("/api/image/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                rest = path.split("/api/image/", 1)[1]
                jobid, fname = rest.split("/", 1)
                session_id, _ = self._upload_session(create=False)
                with _lock_jobs:
                    owned_job = _jobs.get(jobid)
                if not owned_job or not session_owns_record(session_id, owned_job):
                    return self._send(404, b'{"error":"not found"}')
                p = safe_child_path(JOBS_DIR / jobid, fname)
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
                self._write_stream(p, "image/png", download_name=fname)
            except ValueError:
                self._send(403, b'{"error":"bad path"}')
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError,
                    socket.timeout, TimeoutError):
                # Browser canceled an image request (navigation/refresh). The file
                # is intact; do not append a second HTTP response after 200.
                return
            except FileNotFoundError:
                self._send(404, b'{"error":"not found"}')
            except Exception as e:
                self._send(500, b'{"error":"preview temporarily unavailable"}')
        elif path == "/realcomic":
            self.send_response(302)
            self.send_header("Location", "/realism?workflow=realcomic")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path in ("/original-sketch", "/original-graphic"):
            target = "/?style=" + ("original_sketch" if path == "/original-sketch" else "original_graphic")
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/" or path.startswith("/static/") or path in ("/promptgen", "/realism", "/video"):
            if not self._auth():
                # serve shell so user can enter token; API calls still guarded
                pass
            root = BASE / "static"
            clean_pages = {"/promptgen": "promptgen.html", "/realism": "realism.html"}
            if path in clean_pages:
                rel = clean_pages[path]
            elif path == "/video":
                rel = "video.html"
            else:
                rel = "index.html" if path == "/" else path.split("/static/", 1)[1]
            try:
                fp = safe_child_path(root, rel)
            except ValueError:
                return self._send(404, b"not found")
            if not fp.exists():
                return self._send(404, b"not found")
            ctype = static_content_type(rel)
            self._send_static(fp, ctype)
        else:
            self._send(404, b'{"error":"not found"}')

    def _running_job_id(self, generation_backend=None):
        with _lock_jobs:
            for j in _jobs.values():
                if j.get("status") in ("running", "recovering") and (generation_backend is None or j.get("generation_backend", "cloud") == generation_backend):
                    return j["id"]
        return None

    def do_POST(self):
        global _release_draining
        path = urllib.parse.urlparse(self.path).path
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._send(400, b'{"error":"invalid content length"}')
        body_limit = json_body_limit(path)
        if content_length < 0 or content_length > body_limit:
            return self._send(413, b'{"error":"request body too large"}')
        if path == "/api/admin/release-drain":
            if not self._management_auth():
                return self._send(401, b'{"error":"management authorization required"}')
            if not _is_loopback_peer(self.client_address[0]):
                return self._send(403, b'{"error":"release drain is loopback only"}')
            try:
                body = self._read_json(1024)
            except Exception:
                return self._send(400, b'{"error":"bad json"}')
            enabled = body.get("enabled") if isinstance(body, dict) else None
            if not isinstance(enabled, bool):
                return self._send(400, b'{"error":"enabled must be boolean"}')
            with _admission_lock:
                _release_draining = enabled
                state = self._release_state()
            return self._send(200, json.dumps(state, separators=(",", ":")).encode())
        if path in ("/api/workflow-upload", "/api/upload"):
            with _admission_lock:
                if _release_draining:
                    return self._release_in_progress()
        if content_length >= LARGE_REQUEST_THRESHOLD:
            if not self.server._large_request_slots.acquire(blocking=False):
                return self._send(503, b'{"error":"large upload capacity busy"}', headers={"Retry-After": "10"})
            self._large_request_slot_acquired = True
        if path == "/api/workflow-upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                body = self._read_json()
                workflow_id = str(body.get("workflow") or "")
                input_key = str(body.get("input_key") or "")
                w = WORKFLOWS.get(workflow_id)
                if not w or w.get("backend") != "runninghub" or w.get("kind") not in ("rh_workflow", "ai_app"):
                    return self._send(400, b'{"error":"unknown workflow"}')
                raw = base64.b64decode(body.get("data", ""), validate=True)
                filename, ctype, media_type = validate_workflow_upload(
                    w, input_key, body.get("filename") or "", raw)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            except Exception:
                return self._send(400, json.dumps({"error": "图片数据无效"}, ensure_ascii=False).encode())
            if not raw:
                return self._send(400, json.dumps({"error": "请选择图片"}, ensure_ascii=False).encode())
            if len(raw) > 30 * 1024 * 1024:
                return self._send(400, json.dumps({"error": "图片超过30MB限制"}, ensure_ascii=False).encode())
            session_id, cookie_header = self._upload_session(create=True)
            upload_quota = reserve_upload_attempt(session_id, len(raw))
            if self._upload_quota_rejection(upload_quota):
                return
            try:
                remote_name = rh_upload_file(raw, filename, ctype)
                upload_token = issue_upload_capability(
                    remote_name, workflow_id, input_key, media_type, filename, session_id)
            except Exception as error:
                return self._send(502, json.dumps({"error": "RunningHub上传失败，请稍后重试"}, ensure_ascii=False).encode())
            headers = {"Set-Cookie": cookie_header} if cookie_header else None
            return self._send(200, json.dumps({
                "uploadToken": upload_token, "filename": filename,
                "mediaType": ctype, "input_key": input_key,
            }, ensure_ascii=False).encode(), headers=headers)
        if path == "/api/workflow-generate":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                body = self._read_json()
            except Exception:
                return self._send(400, b'{"error":"bad json"}')
            workflow_id = str(body.get("workflow") or "")
            w = WORKFLOWS.get(workflow_id)
            if not w or w.get("backend") != "runninghub" or w.get("kind") not in ("rh_workflow", "ai_app"):
                return self._send(400, b'{"error":"unknown workflow"}')
            session_id = self._require_session()
            if not session_id:
                return
            try:
                provider_media, public_media = resolve_upload_capabilities(
                    w, body.get("media") or {}, session_id)
                _, trusted_params = normalize_rh_workflow_inputs(
                    w, public_media, body.get("params") or {})
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            try:
                client_request_id = normalize_client_request_id(body.get("client_request_id"))
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}).encode())
            selection_snapshot = upload_bound_snapshot(
                w, public_media, trusted_params, body.get("selection_snapshot"), "realism")
            request_sha256 = effective_request_sha256({
                "workflow": workflow_id, "generation_backend": "cloud",
                "provider_media": provider_media, "params": trusted_params,
            })
            with _admission_lock, _submit_locks["cloud"]:
                if _release_draining:
                    return self._release_in_progress()
                decision, existing_job, session_hash = idempotency_decision(
                    client_request_id, session_id, request_sha256)
                if decision == "duplicate":
                    return self._send(200, json.dumps({
                        "job_id": existing_job["id"], "existing_job": existing_job["id"],
                        "deduplicated": True, "message": "same request already accepted",
                    }).encode())
                if decision == "conflict":
                    return self._send(409, json.dumps({
                        "error": "client_request_id already used with different request payload",
                    }).encode())
                active_id = self._running_job_id("cloud")
                if active_id:
                    return self._send(429, json.dumps({
                        "error": "云端已有任务正在运行，请等待完成后再提交",
                    }, ensure_ascii=False).encode())
                prompt = ""
                for key in ("prompt", "instruction", "requirements", "text", "positive"):
                    if trusted_params.get(key) not in (None, ""):
                        prompt = str(trusted_params[key])
                        break
                job = {
                    "id": uuid.uuid4().hex[:12], "workflow": workflow_id,
                    "prompt": prompt, "negative_prompt": str(trusted_params.get("negative") or ""),
                    "prompt_mode": "manual", "media": public_media,
                    "provider_media": provider_media, "params": trusted_params,
                    "width": int(trusted_params.get("width") or 0),
                    "height": int(trusted_params.get("height") or 0),
                    "batch": int(trusted_params.get("batch") or 1),
                    "hd": trusted_params.get("hd", 0), "seed": trusted_params.get("seed", 0),
                    "seed_mode": "fixed" if trusted_params.get("seed") else "random",
                    "loras": {}, "lora_strengths": {}, "trigger": None, "translate": False,
                    "status": "running", "progress": 0, "progress_pct": 0, "images": [],
                    "prompt_ids": [], "error": None, "elapsed": None, "created": time.time(),
                    "wf_name": w["name"], "submit_started": None, "provider_started": None,
                    "provider_finished": None, "download_started": None, "download_finished": None,
                    "style_id": "realism", "style_variant": "default", "mode": "original",
                    "generation_backend": "cloud", "sequence_mode": "off",
                    "selection_snapshot": selection_snapshot,
                    "client_request_id": client_request_id,
                    "request_session_hash": session_hash,
                    "effective_request_sha256": request_sha256,
                }
                quota_status = register_billable_job(job, session_id)
                if self._billable_quota_rejection(quota_status):
                    return
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
                return self._send(200, json.dumps({"job_id": job["id"]}).encode())
        if path == "/api/realcomic-upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                body = self._read_json()
                workflow_id = str(body.get("workflow") or "realcomic")
                input_key = str(body.get("input_key") or "source_image")
                w = WORKFLOWS.get(workflow_id)
                if not w or w.get("kind") != "ai_app" or w.get("backend") != "runninghub":
                    return self._send(400, b'{"error":"unknown AI App"}')
                raw = base64.b64decode(body.get("data", ""), validate=True)
                filename, ctype, media_type = validate_workflow_upload(
                    w, input_key, body.get("filename") or "", raw)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            except Exception:
                return self._send(400, json.dumps({"error": "图片数据无效"}, ensure_ascii=False).encode())
            if not raw:
                return self._send(400, json.dumps({"error": "请选择二次元图片"}, ensure_ascii=False).encode())
            if len(raw) > 30 * 1024 * 1024:
                return self._send(400, json.dumps({"error": "图片超过30MB限制"}, ensure_ascii=False).encode())
            session_id, cookie_header = self._upload_session(create=True)
            upload_quota = reserve_upload_attempt(session_id, len(raw))
            if self._upload_quota_rejection(upload_quota):
                return
            try:
                remote_name = rh_upload_file(raw, filename, ctype)
                upload_token = issue_upload_capability(
                    remote_name, workflow_id, input_key, media_type, filename, session_id)
            except Exception as error:
                return self._send(502, json.dumps({"error": "RunningHub上传失败，请稍后重试"}, ensure_ascii=False).encode())
            headers = {"Set-Cookie": cookie_header} if cookie_header else None
            return self._send(200, json.dumps({
                "uploadToken": upload_token, "filename": filename,
                "mediaType": ctype, "input_key": input_key,
            }, ensure_ascii=False).encode(), headers=headers)
        if path == "/api/ai-app-generate":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            wf = str(body.get("workflow") or "realcomic")
            w = WORKFLOWS.get(wf)
            if not w or w.get("kind") != "ai_app" or w.get("backend") != "runninghub":
                return self._send(400, b'{"error":"unknown AI App"}')
            submitted_media = body.get("media") or {}
            params = body.get("params") or {}
            if not isinstance(submitted_media, dict) or not isinstance(params, dict):
                return self._send(400, b'{"error":"media and params must be objects"}')
            session_id = self._require_session()
            if not session_id:
                return
            try:
                provider_media, public_media = resolve_upload_capabilities(
                    w, submitted_media, session_id)
                _, trusted_params = normalize_rh_workflow_inputs(w, public_media, params)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            try:
                client_request_id = normalize_client_request_id(body.get("client_request_id"))
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}).encode())
            request_sha256 = effective_request_sha256({
                "workflow": wf, "generation_backend": "cloud",
                "provider_media": provider_media, "params": trusted_params,
            })
            with _admission_lock, _submit_locks["cloud"]:
                if _release_draining:
                    return self._release_in_progress()
                decision, existing_job, session_hash = idempotency_decision(
                    client_request_id, session_id, request_sha256)
                if decision == "duplicate":
                    return self._send(200, json.dumps({"job_id": existing_job["id"], "existing_job": existing_job["id"], "deduplicated": True, "message": "same request already accepted"}).encode())
                if decision == "conflict":
                    return self._send(409, json.dumps({
                        "error": "client_request_id already used with different request payload",
                    }).encode())
                active_id = self._running_job_id("cloud")
                if active_id:
                    return self._send(429, json.dumps({"error": "云端已有任务正在运行，请等待完成后再提交"}, ensure_ascii=False).encode())
                job = {"id": uuid.uuid4().hex[:12], "workflow": wf,
                       "prompt": trusted_params.get("requirements", ""), "negative_prompt": "", "prompt_mode": "manual",
                       "media": public_media, "provider_media": provider_media,
                       "params": trusted_params,
                       "width": 0, "height": 0, "batch": 1, "hd": 0, "seed": 0, "seed_mode": "random",
                       "loras": {}, "lora_strengths": {}, "trigger": None, "translate": False,
                       "status": "running", "progress": 0, "progress_pct": 0, "images": [],
                       "prompt_ids": [], "error": None, "elapsed": None, "created": time.time(), "wf_name": w["name"],
                       "submit_started": None, "provider_started": None, "provider_finished": None,
                       "download_started": None, "download_finished": None,
                       "style_id": "realcomic", "mode": "original", "generation_backend": "cloud",
                       "sequence_mode": "off", "selection_snapshot": upload_bound_snapshot(
                           w, public_media, trusted_params, body.get("selection_snapshot"), "realism"),
                       "client_request_id": client_request_id,
                       "request_session_hash": session_hash,
                       "effective_request_sha256": request_sha256,
                       "provider_attribution": w.get("provider_attribution")}
                quota_status = register_billable_job(job, session_id)
                if self._billable_quota_rejection(quota_status):
                    return
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
                return self._send(200, json.dumps({"job_id": job["id"]}).encode())
        if path == "/api/upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try:
                body = self._read_json(MAX_UPLOAD_JSON_BYTES)
                workflow_id = str(body.get("workflow") or "")
                input_key = str(body.get("input_key") or "")
                w = WORKFLOWS.get(workflow_id)
                if not w or w.get("kind") != "video" or w.get("backend") != "runninghub":
                    return self._send(400, b'{"error":"unknown workflow"}')
                raw = base64.b64decode(body.get("data", ""), validate=True)
                filename, ctype, media_type = validate_workflow_upload(
                    w, input_key, body.get("filename") or "", raw)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            except Exception:
                return self._send(400, b'{"error":"bad json (need workflow, input_key, filename and base64 data)"}')
            if not raw:
                return self._send(400, b'{"error":"empty file"}')
            if len(raw) > 60 * 1024 * 1024:
                return self._send(400, b'{"error":"file too large (>60MB)"}')
            session_id, cookie_header = self._upload_session(create=True)
            upload_quota = reserve_upload_attempt(session_id, len(raw))
            if self._upload_quota_rejection(upload_quota):
                return
            try:
                remote_name = rh_upload_file(raw, filename, ctype)
                upload_token = issue_upload_capability(
                    remote_name, workflow_id, input_key, media_type, filename, session_id)
            except Exception as error:
                return self._send(502, json.dumps({"error": "RunningHub上传失败，请稍后重试"}, ensure_ascii=False).encode())
            headers = {"Set-Cookie": cookie_header} if cookie_header else None
            return self._send(200, json.dumps({
                "uploadToken": upload_token, "filename": filename,
                "mediaType": ctype, "input_key": input_key,
            }, ensure_ascii=False).encode(), headers=headers)
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
            submitted_media = body.get("media") or {}
            if not isinstance(submitted_media, dict):
                return self._send(400, b'{"error":"media must be object {key: uploadToken}"}')
            params = body.get("params") or {}
            if not isinstance(params, dict):
                return self._send(400, b'{"error":"params must be object"}')
            # Normalize before persistence so browser-only keys, node wiring,
            # model paths and malformed enum/range values never enter a job.
            schema_params = dict(params)
            if "prompt" in (w.get("rh_params") or {}) and "prompt" not in schema_params:
                schema_params["prompt"] = prompt
            if "negative" in (w.get("rh_params") or {}) and "negative" not in schema_params:
                schema_params["negative"] = negative_prompt
            session_id = self._require_session()
            if not session_id:
                return
            try:
                provider_media, public_media = resolve_upload_capabilities(
                    w, submitted_media, session_id)
                _, params = normalize_rh_workflow_inputs(w, public_media, schema_params)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            prompt = str(params.get("prompt", prompt)).strip()
            negative_prompt = str(params.get("negative", negative_prompt)).strip()
            try:
                client_request_id = normalize_client_request_id(body.get("client_request_id"))
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}).encode())
            request_sha256 = effective_request_sha256({
                "workflow": wf, "generation_backend": "cloud",
                "provider_media": provider_media, "prompt": prompt,
                "negative_prompt": negative_prompt, "params": params,
            })
            # Serialize idempotency admission across all billable routes, then
            # apply the provider's verified two-video concurrency limit.
            with _idempotency_lock, _submit_locks["video"]:
                if _release_draining:
                    return self._release_in_progress()
                decision, existing_job, session_hash = idempotency_decision(
                    client_request_id, session_id, request_sha256)
                if decision == "duplicate":
                    return self._send(200, json.dumps({"job_id": existing_job["id"],
                        "deduplicated": True, "message": "same request already accepted"}).encode())
                if decision == "conflict":
                    return self._send(409, json.dumps({
                        "error": "client_request_id already used with different request payload",
                    }).encode())
                with _lock_jobs:
                    running_cloud = [j for j in _jobs.values()
                                     if j.get("generation_backend") == "cloud"
                                     and j.get("status") in ("running", "recovering")]
                if len(running_cloud) >= VIDEO_MAX_CONCURRENT:
                    return self._send(429, json.dumps({
                        "error": f"RunningHub任务已达总并发上限（{VIDEO_MAX_CONCURRENT}个），请等待其中一个完成",
                    }, ensure_ascii=False).encode())
                job = {"id": uuid.uuid4().hex[:12], "workflow": wf, "prompt": prompt,
                   "negative_prompt": negative_prompt, "prompt_mode": "manual",
                   "media": public_media, "provider_media": provider_media,
                   "params": params,
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
                   "sequence_mode": "off", "selection_snapshot": upload_bound_snapshot(
                       w, public_media, params, body.get("selection_snapshot"), "video"),
                   "client_request_id": client_request_id,
                   "request_session_hash": session_hash,
                   "effective_request_sha256": request_sha256}
                quota_status = register_billable_job(job, session_id)
                if self._billable_quota_rejection(quota_status):
                    return
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
                return self._send(200, json.dumps({"job_id": job["id"]}).encode())
        if path == "/api/favorites":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            jid = str(body.get("job_id", "")); idx = int(body.get("image_index", -1))
            session_id, _ = self._upload_session(create=False)
            with _favorite_operation_lock:
                with _lock_jobs:
                    job = _jobs.get(jid)
                    existing_favorite = next((fav for fav in _favorites.values()
                        if fav.get("job_id") == jid and fav.get("image_index") == idx
                        and session_owns_record(session_id, fav, "owner_session_hash")), None)
                if existing_favorite:
                    return self._send(200, json.dumps(public_favorite(existing_favorite), ensure_ascii=False).encode())
                if (not job or job.get("status") != "done"
                        or not session_owns_record(session_id, job)):
                    return self._send(404, b'{"error":"completed job not found"}')
                images = job.get("images") or []
                if idx < 0 or idx >= len(images): return self._send(400, b'{"error":"bad image index"}')
                im = images[idx]; fid = uuid.uuid4().hex[:12]
                remote_suffix = pathlib.PurePosixPath(urllib.parse.urlparse(im.get("url", "")).path).suffix.lower()
                allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".avi", ".mkv"}
                type_suffixes = {
                    "png": ".png", "image/png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "image/jpeg": ".jpg",
                    "webp": ".webp", "image/webp": ".webp", "mp4": ".mp4", "video/mp4": ".mp4",
                    "mov": ".mov", "video/quicktime": ".mov", "webm": ".webm", "video/webm": ".webm",
                    "avi": ".avi", "video/x-msvideo": ".avi", "mkv": ".mkv", "video/x-matroska": ".mkv",
                }
                suffix = remote_suffix if remote_suffix in allowed_suffixes else type_suffixes.get(str(im.get("file_type") or "").lower(), ".bin")
                dest = FAVORITES_DIR / f"{fid}{suffix}"
                try:
                    if im.get("remote"):
                        download_file_resilient(im["url"], dest, timeout=120)
                    else:
                        src = ensure_local_original(job, im)
                        dest.write_bytes(src.read_bytes())
                except Exception as e:
                    return self._send(502, json.dumps({"error": "收藏结果失败，请稍后重试"}, ensure_ascii=False).encode())
                favorite_data = dest.read_bytes()
                video_mimes = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".avi": "video/x-msvideo", ".mkv": "video/x-matroska"}
                favorite_media_type = image_content_type(favorite_data, dest.name) or video_mimes.get(suffix) or "application/octet-stream"
                fav = {
                    "id": fid, "created": time.time(), "job_id": jid, "image_index": idx,
                    "image_url": f"/api/favorite-image/{fid}",
                    "preview_url": f"/api/favorite-preview/{fid}", "original_url": im.get("url"),
                    "image_path": str(dest), "favorite_media_type": favorite_media_type,
                    "owner_session_hash": _session_hash(session_id),
                    "prompt": job.get("prompt", ""), "negative_prompt": job.get("negative_prompt", ""),
                    "prompt_mode": job.get("prompt_mode", "options"),
                    "seed": job.get("seed"), "seed_mode": job.get("seed_mode"),
                    "style_id": job.get("style_id"), "style_variant": job.get("style_variant"),
                    "mode": job.get("mode"), "generation_backend": job.get("generation_backend", "cloud"),
                    "selection_snapshot": job.get("selection_snapshot") or {},
                    "width": job.get("width"), "height": job.get("height"), "batch": job.get("batch"),
                }
                with _lock_jobs:
                    _favorites[fid] = fav
                    prune_favorites(fav["owner_session_hash"])
                    save_favorites()
                return self._send(200, json.dumps(public_favorite(fav), ensure_ascii=False).encode())
        if path == "/api/comfy/start":
            if not self._management_auth():
                return self._send(401, b'{"error":"management authorization required"}')
            if not _comfy_start_lock.acquire(blocking=False):
                return self._send(409, b'{"error":"ComfyUI start already in progress"}')
            try:
                started, msg = start_comfy_remote()
                self._send(200 if started else 502, json.dumps({
                    "started": started, "detail": msg,
                }).encode())
                return
            finally:
                _comfy_start_lock.release()
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
        if wf != "anima02" or w.get("kind") in ("video", "ai_app", "rh_workflow"):
            return self._send(400, b'{"error":"not a creator image workflow"}')
        session_id = self._require_session()
        if not session_id:
            return
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            return self._send(400, b'{"error":"prompt empty"}')
        negative_prompt = str(body.get("negative_prompt", "")).strip()
        prompt_mode = str(body.get("prompt_mode") or "options")
        if prompt_mode not in ("options", "manual"):
            return self._send(400, b'{"error":"unknown prompt_mode"}')
        generation_backend = str(body.get("generation_backend") or "cloud")
        if generation_backend not in ("cloud", "local", "api"):
            return self._send(400, b'{"error":"unknown generation_backend"}')
        try:
            client_request_id = normalize_client_request_id(body.get("client_request_id"))
        except ValueError as error:
            return self._send(400, json.dumps({"error": str(error)}).encode())
        try:
            numeric_values = {"batch": body.get("batch", 1), "hd": body.get("hd", 0)}
            if generation_backend != "api":
                numeric_values.update({
                    "width": body.get("width", 0), "height": body.get("height", 0),
                })
            if any(isinstance(value, (bool, dict, list)) for value in numeric_values.values()):
                raise TypeError("numeric parameter must be scalar")
            batch = max(1, min(_bounded_request_int(numeric_values["batch"], 1), w["batch_max"]))
            hd = _bounded_request_int(numeric_values["hd"], 0)
            width = _bounded_request_int(numeric_values.get("width", 0), 0)
            height = _bounded_request_int(numeric_values.get("height", 0), 0)
        except (TypeError, ValueError, OverflowError):
            return self._send(400, b'{"error":"invalid numeric parameters"}')
        hd_options = w.get("hd") or ["关闭"]
        if hd < 0 or hd >= len(hd_options):
            return self._send(400, b'{"error":"hd out of range"}')
        api_model = str(body.get("api_model") or "gpt-image-2.5-flare")
        api_quality = str(body.get("api_quality") or "medium")
        api_fit = str(body.get("api_fit") or "cover")
        api_ratio = str(body.get("api_ratio") or "9:16")
        if generation_backend == "api":
            if len(prompt) > 12000 or len(negative_prompt) > 12000:
                return self._send(400, b'{"error":"prompt too long (max 12000 characters)"}')
            if batch != 1:
                return self._send(400, b'{"error":"API generation supports one image per task"}')
            if hd != 0:
                return self._send(400, b'{"error":"API generation does not use the local HD pipeline"}')
            if api_model not in DREAMAPI_IMAGE_QUALITIES:
                return self._send(400, b'{"error":"unknown DreamAPI image model"}')
            if api_quality not in DREAMAPI_IMAGE_QUALITIES[api_model]:
                return self._send(400, b'{"error":"quality is not supported by the DreamAPI image model"}')
            if api_fit not in {"cover", "contain"}:
                return self._send(400, b'{"error":"unknown DreamAPI fit mode"}')
            if api_ratio not in DREAMAPI_RATIO_SIZES:
                return self._send(400, b'{"error":"unknown DreamAPI aspect ratio"}')
            width, height = DREAMAPI_RATIO_SIZES[api_ratio]
        with _admission_lock, _submit_locks[generation_backend]:
            if _release_draining:
                return self._release_in_progress()
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
            try:
                seed = _bounded_request_int(seed, 0)
            except (TypeError, ValueError, OverflowError):
                if seed_mode == "fixed":
                    return self._send(400, b'{"error":"invalid fixed seed"}')
                seed = 0
            if seed_mode == "fixed" and not (1 <= seed <= 9007199254740991):
                return self._send(400, b'{"error":"fixed seed out of range"}')
            if seed_mode == "random":
                seed = secrets.randbelow(2**53 - 1) + 1
            style_id = str(body.get("style_id") or "cold")
            mode = str(body.get("mode") or "original")
            if style_id not in STYLE_PRESETS:
                return self._send(400, b'{"error":"unknown style_id"}')
            if mode not in ("original", "character"):
                return self._send(400, b'{"error":"unknown mode"}')
            style_variant = str(body.get("style_variant") or "") or None
            try:
                preset = resolve_style_preset(style_id, style_variant)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}).encode())
            # Staged sketch painting was retired. Old clients may still send a
            # saved sequence value, but every new task executes exactly once.
            sequence_mode = "off"
            # Both image backends use the same trusted style mapping. The local
            # runner converts basenames to Anima_JT\ paths just before submit.
            loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}
            lora_strengths = dict(preset["strengths"])
            trigger = preset["trigger"]
            translate = False
            request_payload = {
                "workflow": wf, "generation_backend": generation_backend,
                "prompt": prompt, "negative_prompt": negative_prompt,
                "prompt_mode": prompt_mode, "width": width, "height": height,
                "batch": batch, "hd": hd,
                "seed": seed if seed_mode == "fixed" else "random",
                "seed_mode": seed_mode, "style_id": style_id,
                "style_variant": preset["id"], "mode": mode,
                "api_model": api_model if generation_backend == "api" else None,
                "api_quality": api_quality if generation_backend == "api" else None,
                "api_fit": api_fit if generation_backend == "api" else None,
                "api_ratio": api_ratio if generation_backend == "api" else None,
            }
            request_sha256 = effective_request_sha256(request_payload)
            cookie_header = None
            decision, existing_job, session_hash = idempotency_decision(
                client_request_id, session_id, request_sha256)
            response_headers = {"Set-Cookie": cookie_header} if cookie_header else None
            if decision == "duplicate":
                return self._send(200, json.dumps({
                    "job_id": existing_job["id"], "existing_job": existing_job["id"],
                    "deduplicated": True, "message": "same request already accepted",
                }).encode(), headers=response_headers)
            if decision == "conflict":
                return self._send(409, json.dumps({
                    "error": "client_request_id already used with different request payload",
                }).encode(), headers=response_headers)
            active_id = self._running_job_id(generation_backend)
            if active_id:
                return self._send(429, json.dumps({
                    "error": "已有任务正在运行，请等待完成后再提交",
                }, ensure_ascii=False).encode(), headers=response_headers)
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
                   "download_finished": None, "style_id": style_id,
                   "style_variant": preset["id"], "mode": mode,
                   "sequence_mode": sequence_mode, "generation_backend": generation_backend,
                   "client_request_id": client_request_id,
                   "request_session_hash": session_hash,
                   "effective_request_sha256": request_sha256,
                   "api_model": api_model if generation_backend == "api" else None,
                   "api_quality": api_quality if generation_backend == "api" else None,
                   "api_fit": api_fit if generation_backend == "api" else None,
                   "api_ratio": api_ratio if generation_backend == "api" else None,
                   "seed_supported": generation_backend != "api",
                   "comfy_prompt_id": None, "transfer_index": 0, "transfer_total": 0,
                   "transfer_started": None, "transfer_finished": None,
                   "selection_snapshot": public_selection_snapshot({
                       **(body.get("selection_snapshot") if isinstance(body.get("selection_snapshot"), dict) else {}),
                       "source_page": "creator", "workflow": "anima02",
                       "generation_backend": generation_backend,
                       **({"api_ratio": api_ratio} if generation_backend == "api" else {}),
                   })}
            if generation_backend in ("cloud", "api"):
                quota_status = register_billable_job(job, session_id)
                if self._billable_quota_rejection(quota_status):
                    return
            else:
                with _lock_jobs:
                    _jobs[job["id"]] = job
                    save_jobs()
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            self._send(200, json.dumps({"job_id": job["id"]}).encode(), headers=response_headers)

def main():
    global TOKEN
    if not TOKEN:
        TOKEN = os.environ.get("PANEL_TOKEN") or secrets.token_urlsafe(24)
        print(f"[panel] no PANEL_TOKEN set, generated: {TOKEN}", flush=True)
    load_jobs()
    load_favorites()
    load_upload_capabilities()
    load_upload_usage()
    for job in list(_jobs.values()):
        if job.get("status") == "recovering" and job.get("rh_task_id"):
            threading.Thread(target=resume_cloud_job, args=(job,), daemon=True).start()
    threading.Thread(target=backfill_completed_rh_coins, daemon=True).start()
    ok, msg = comfy_ok()
    print(f"[panel] comfy {COMFY_URL}: ok={ok} {msg}", flush=True)
    print(f"[panel] listening 0.0.0.0:{PORT} data={DATA_DIR}", flush=True)
    BoundedHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
