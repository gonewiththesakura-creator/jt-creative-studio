#!/usr/bin/env python3
"""comfy-panel: a minimal remote control panel for local ComfyUI.
Pure stdlib. Runs on the public relay server; talks to local ComfyUI
through an SSH reverse tunnel (server:127.0.0.1:8199 -> local:127.0.0.1:8188).

Env:
  COMFY_URL   default http://127.0.0.1:8188
  PANEL_BIND  default 0.0.0.0
  PANEL_PORT  default 8189
  PANEL_TOKEN required (auth)
  PANEL_DIR   default ./panel_data (jobs + images)
"""
import json, os, re, sys, time, uuid, threading, urllib.request, urllib.parse, urllib.error, math
import http.server, http.cookies, socketserver, pathlib, secrets, hashlib, hmac
import socket, base64, struct, subprocess, io, gzip, ipaddress, tempfile, ssl, http.client
from video_uploads import UploadStaging
from media_library import MediaLibrary
import direct_uploads
from membership_http import MembershipGateway
from membership_store import MembershipError
from membership_media import stream_media, download_media, MediaOwnerSlots, acquire_media_slot, release_media_slot
from result_image_cache import ResultImageCache, PreviewError
_video_upload_staging = UploadStaging()

BASE = pathlib.Path(__file__).resolve().parent
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://127.0.0.1:8198").rstrip("/")
BIND_HOST = os.environ.get("PANEL_BIND", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.environ.get("PANEL_PORT", "8189"))
TOKEN = os.environ.get("PANEL_TOKEN", "")
PANEL_RELEASE_TOKEN = os.environ.get("PANEL_RELEASE_TOKEN", "")
_SESSION_SECRET_SOURCE = os.environ.get("PANEL_SESSION_SECRET") or TOKEN or secrets.token_urlsafe(32)
SESSION_SECRET = hashlib.sha256(("jt-session-signing:" + _SESSION_SECRET_SOURCE).encode("utf-8")).digest()
DATA_DIR = pathlib.Path(os.environ.get("PANEL_DIR", str(BASE / "panel_data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
_membership = MembershipGateway(DATA_DIR)
_media_library = MediaLibrary(DATA_DIR / 'media_library')
_result_image_cache = ResultImageCache(DATA_DIR / 'result_image_cache')
JOBS_DIR = DATA_DIR / "jobs"; JOBS_DIR.mkdir(exist_ok=True)
JOBS_FILE = DATA_DIR / "jobs.json"
FAVORITES_DIR = DATA_DIR / "favorites"; FAVORITES_DIR.mkdir(exist_ok=True)
FAVORITES_FILE = DATA_DIR / "favorites.json"
UPLOAD_CAPABILITIES_FILE = DATA_DIR / "upload_capabilities.json"
UPLOAD_USAGE_FILE = DATA_DIR / "upload_usage.json"

# RunningHub API 适配
RH_BASE = "https://www.runninghub.ai/openapi/v2"
RH_KEY = os.environ.get("RUNNINGHUB_API_KEY", "")

# DreamAPI Images adapter. The browser never sees this key or controls the
# upstream URL; only an allowlisted image model, quality and fit mode can be
# selected through the creator endpoint.
DREAMAPI_KEY = os.environ.get("DREAMAPI_KEY", "")
DREAMAPI_BASE_URL = os.environ.get("DREAMAPI_BASE_URL", "https://dreamapi.club").rstrip("/")
DREAMAPI_EGRESS_URL = os.environ.get("DREAMAPI_EGRESS_URL", "").strip()
DREAMAPI_CONNECTION_MODE = os.environ.get("DREAMAPI_CONNECTION_MODE", "direct").strip()
DREAMAPI_TIMEOUT = 600
DREAMAPI_MAX_RESPONSE_BYTES = 96 * 1024 * 1024
DREAMAPI_MAX_IMAGE_BYTES = 32 * 1024 * 1024
DREAMAPI_MAX_SOURCE_PIXELS = 32 * 1024 * 1024
DREAMAPI_IMAGE_QUALITIES = {
    "gpt-image-2": {"low", "medium", "high", "auto"},
    "gpt-image-2.5-flare": {"low", "medium", "high", "xhigh", "max", "auto"},
    "gpt-image-2.5-sunburst": {"low", "medium", "high", "xhigh", "max", "auto"},
}
DREAMAPI_RATIO_SIZES = {
    "1:1": (1024, 1024),
    "2:3": (1024, 1536),
    "3:2": (1536, 1024),
    "9:16": (864, 1536),
    "16:9": (1536, 864),
}
DREAMAPI_PROVIDER_SIZE_BY_RATIO = dict(DREAMAPI_RATIO_SIZES)


def _dreamapi_contract_document():
    """Return the public request-shape contract shared with the workstation proxy."""
    models = {}
    for model in sorted(DREAMAPI_IMAGE_QUALITIES):
        models[model] = {
            "qualities": sorted(DREAMAPI_IMAGE_QUALITIES[model]),
        }
    return {
        "contract_version": 3,
        "images_api": {
            "models": models,
            "output_format": "png",
            "request_keys": ["model", "n", "output_format", "prompt", "quality", "size"],
            "sizes_by_ratio": {
                ratio: f"{width}x{height}"
                for ratio, (width, height) in DREAMAPI_PROVIDER_SIZE_BY_RATIO.items()
            },
        },
        "runtime_safety": {
            "kill_worker_on_parent_exit": True,
            "persistent_uncertainty_fence": True,
        },
        "single_image_count": 1,
    }


def _dreamapi_contract_sha256():
    canonical = json.dumps(
        _dreamapi_contract_document(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


DREAMAPI_CONTRACT_SHA256 = _dreamapi_contract_sha256()
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
# V2 query exposes only real task states, not a stable percentage. Keep these
# conservative and fixed; never manufacture progress from elapsed/poll count.
RH_STAGE_PROGRESS = {"QUEUED": 0.02, "RUNNING": 0.10}


class ProviderTaskFailed(RuntimeError):
    """The provider explicitly reported a terminal failure."""


class ProviderTaskCancelled(ProviderTaskFailed):
    """The provider confirmed that this task has stopped."""


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
VIDEO_QUEUE_LIMIT = 200
VIDEO_QUEUE_SESSION_LIMIT = 100
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
                if j.get('video_queued') and j.get('dispatch_started'):
                    j['queue_hold'] = True
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
    job = _jobs.get(result.get("job_id"), {})
    if result.get("owner_session_hash") and result.get("owner_session_hash") == job.get("request_session_hash"):
        result["thumbnails"] = public_video_thumbnails(job)
        if not result["selection_snapshot"]["params"]:
            result["selection_snapshot"] = public_selection_snapshot(job.get("selection_snapshot"))
    for private_key in ("provider_media", "image_path", "original_url", "owner_session_hash", "owner_user_id"):
        result.pop(private_key, None)
    return result

def save_favorites():
    _atomic_write_json_object(FAVORITES_FILE, _favorites, "favorites ledger")


def video_favorite_archive_loop():
    """One background downloader, independent of paid generation admission."""
    while True:
        try:
            archive_next_video_favorite()
        except Exception:
            pass
        time.sleep(2)


def archive_next_video_favorite():
    with _lock_jobs:
        fav = next((dict(f) for f in _favorites.values() if f.get('archive_status') == 'saving'), None)
    if not fav:
        return
    try:
        dest = safe_child_path(FAVORITES_DIR, pathlib.Path(fav['image_path']))
        download_file_resilient(fav['original_url'], dest, timeout=120)
        changes = {'archive_status':'ready', 'archive_error':None}
    except Exception:
        changes = {'archive_status':'error', 'archive_error':'视频保存失败，请点击重试；可能是原链接已过期或网络暂时不可用'}
    with _lock_jobs:
        current = _favorites.get(fav['id'])
        if current and current.get('archive_status') == 'saving':
            before = dict(current)
            current.update(changes)
            try:
                save_favorites()
            except Exception:
                current.clear(); current.update(before)
                raise


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
                            original_filename, session_id, expires=None):
    token = "upl_" + secrets.token_urlsafe(32)
    now = time.time()
    row = {
        "provider_name": str(provider_name), "workflow": str(workflow_id),
        "input_key": str(input_key), "media_type": str(media_type).lower(),
        "filename": str(original_filename), "session_hash": _session_hash(session_id),
        "created": now, "expires": min(now + UPLOAD_CAPABILITY_TTL, expires) if expires else now + UPLOAD_CAPABILITY_TTL,
    }
    with _upload_capabilities_lock:
        _upload_capabilities[_upload_token_hash(token)] = row
        prune_upload_capabilities(save=True)
    return token


def resolve_upload_capabilities(workflow, submitted_media, session_id, params=None):
    if not isinstance(submitted_media, dict):
        raise ValueError("media must be an object")
    if params is not None and not isinstance(params, dict):
        raise ValueError('params must be an object')
    provider_media, public_media = {}, {}
    now = time.time()
    with _upload_capabilities_lock:
        for key, mapping in (workflow.get("rh_media") or {}).items():
            if not rh_input_enabled(workflow, mapping, params or {}):
                continue
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
    """Archive trusted results using the same pinned HTTPS boundary as playback."""
    return download_media(url, dest, timeout=timeout, validator=downloaded_media_content_type)


class _NoProviderRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials can be in headers OR JSON bodies. Avoid replaying them,
        # even to a different path on the same host; configured endpoints must
        # answer directly rather than change the method or destination.
        return None


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
            opener = urllib.request.build_opener(_NoProviderRedirect())
            box["resp"] = opener.open(url, data, timeout=timeout)
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


def dreamapi_workstation_egress_status():
    """Probe the configured workstation proxy and verify its request contract."""
    if not DREAMAPI_EGRESS_URL:
        return False, False, False
    try:
        endpoint = urllib.parse.urlparse(_dreamapi_request_endpoint())
        control = urllib.parse.urlparse(CONTROL_URL)
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if (endpoint.path != "/dreamapi/images/generations"
                or control.scheme != "http" or control.hostname not in loopback_hosts
                or control.username or control.password or control.query or control.fragment
                or control.path not in {"", "/"}
                or endpoint.port != control.port):
            return False, False, False
        status = http_json(CONTROL_URL + "/status", timeout=5)
        remote_sha256 = status.get("dreamapi_contract_sha256") if isinstance(status, dict) else None
        fence_active = (
            status.get("dreamapi_uncertainty_fence") is not False
            if isinstance(status, dict) else True
        )
        contract_match = (
            isinstance(remote_sha256, str)
            and hmac.compare_digest(remote_sha256, DREAMAPI_CONTRACT_SHA256)
        )
    except Exception:
        contract_match = False
        fence_active = True
    return contract_match and not fence_active, contract_match, fence_active


def dreamapi_transport_status():
    """Report configured transport readiness, not a live provider generation probe."""
    if DREAMAPI_CONNECTION_MODE == "workstation":
        ready, matched, fence = dreamapi_workstation_egress_status()
    else:
        ready, matched, fence = False, False, False
        try:
            _dreamapi_request_endpoint()
            ready = matched = bool(DREAMAPI_KEY)
        except ValueError:
            pass
        with _lock_jobs:
            fence = any(_dreamapi_pending(job) for job in _jobs.values())
        ready = ready and not fence
    return {
        "dreamapi_connection_mode": DREAMAPI_CONNECTION_MODE,
        "dreamapi_transport_ready": ready,
        "dreamapi_workstation_egress": ready if DREAMAPI_CONNECTION_MODE == "workstation" else False,
        "dreamapi_contract_match": matched,
        "dreamapi_uncertainty_fence": fence,
    }

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

def billable_quota_status(session_id, now=None, backend=None):
    """Observe historic paid-job counts without imposing website usage caps."""
    now = time.time() if now is None else float(now)
    hour_start, day_start = now - 3600, now - 86400
    session_digest = _session_hash(session_id)
    with _lock_jobs:
        billable = [job for job in _jobs.values()
                    if job.get("billable_quota_recorded") is True
                    and job.get("generation_backend") in ("cloud", "api")
                    and isinstance(job.get("created"), (int, float))]
        hour_times = sorted(job["created"] for job in billable if job["created"] > hour_start)
        day_times = sorted(job["created"] for job in billable if job["created"] > day_start)
        session_times = sorted(job["created"] for job in billable
                               if job["created"] > hour_start
                               and (backend is None or job.get("generation_backend") == backend)
                               and secrets.compare_digest(str(job.get("quota_session_hash") or ""), session_digest))
    global_hour, global_day, session_hour = len(hour_times), len(day_times), len(session_times)
    return {
        "global_hour": global_hour, "global_day": global_day,
        "session_hour": session_hour,
        "blocked": False,
        "scope": None, "backend": backend,
        "retry_after": 0,
    }


def register_billable_job(job, session_id):
    """Atomically persist an accepted paid job and its legacy ledger metadata."""
    with _billable_quota_lock:
        rejected = _membership.reserve(job, session_id)
        if rejected:
            return rejected
        job["quota_session_hash"] = _session_hash(session_id)
        job["billable_quota_recorded"] = True
        with _lock_jobs:
            _jobs[job["id"]] = job
            try:
                save_jobs()
            except Exception:
                _jobs.pop(job["id"], None)
                if job.get("membership_reserved"):
                    _membership.store.settle_job(job["id"], False)
                raise
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


def scoped_history_jobs(jobs, scope=None, style=None, limit=12, before=None):
    ordered = sorted(jobs, key=lambda row: (row.get("created", 0), row.get('id','')), reverse=True)
    if before is not None:
        ordered = [j for j in ordered if (j.get('created',0),j.get('id','')) < before]
    if scope == 'realism':
        ids = {key for key, workflow in WORKFLOWS.items()
               if workflow.get('kind') in ('rh_workflow', 'ai_app')} | set(RETIRED_REALISM_WORKFLOW_IDS)
        ordered = [job for job in ordered if job.get('style_id') == 'realism' or job.get('workflow') in ids]
    elif scope == "video":
        ids = {key for key, workflow in WORKFLOWS.items() if workflow.get("kind") == "video"}
        ordered = [job for job in ordered if job.get('style_id') == 'video' or job.get("workflow") in ids]
    elif scope == "creator":
        ordered = [job for job in ordered if job.get("workflow") == "anima02"]
        if style is not None:
            if style not in STYLE_PRESETS:
                return []
            ordered = [job for job in ordered if job.get("style_id") == style]
    elif scope:
        return []
    return ordered[:limit]


LIBRARY_SCOPES = ("creator", "realism", "video")


def owned_history_sources(session_id):
    """Jobs the caller owns and still sees in a history list. Caller holds _lock_jobs."""
    return [src for src in _jobs.values()
            if session_owns_record(session_id, src)
            and not ((src.get('style_id') in ('video', 'realism') or src.get('workflow') == 'anima02')
                     and src.get('history_cleared') and video_ui_terminal(src))]


def favorite_in_scope(item, scope):
    """Mirror of each page's own favourites filter, so a badge equals the list it opens."""
    if scope == "video":
        return item.get("style_id") == "video" or str(item.get("favorite_media_type") or "").startswith("video/")
    if scope == "realism":
        snapshot = public_favorite(item).get("selection_snapshot") or {}
        return item.get("style_id") == "realism" or snapshot.get("source_page") in ("realism", "realcomic")
    return scope == "creator"


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


def remote_output_is_image(item):
    raw_type = str(item.get('file_type') or '').lower()
    if raw_type.startswith('video/') or raw_type in {'mp4', 'mov', 'webm', 'avi', 'mkv'}:
        return False
    extensions = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'avif'}
    filename = str(item.get('file') or '')
    url_path = urllib.parse.urlsplit(str(item.get('url') or '')).path
    return (raw_type.startswith('image/') or raw_type in extensions
            or pathlib.PurePosixPath(filename or url_path).suffix.lower().lstrip('.') in extensions)


def public_job_images(job):
    images = job.get('images') or []
    if not _membership.enabled:
        return images
    result = []
    for index, source in enumerate(images):
        item = {key: value for key, value in source.items()
                if key in ('url', 'preview_url', 'file', 'file_type', 'remote', 'size', 'stage_id', 'stage_label', 'archive_status')}
        if source.get('remote'):
            item['url'] = f"/api/result-media/{job['id']}/{index}"
            # Remote images use small authenticated derivatives for gallery
            # loading. The original remains available only through the result
            # proxy and is never downloaded by the thumbnail request.
            if remote_output_is_image(source):
                item['thumb_url'] = f"/api/rh-preview/{job['id']}/{index}?size=thumb"
                item['preview_url'] = f"/api/rh-preview/{job['id']}/{index}?size=view"
            else:
                item['preview_url'] = item['url']
        result.append(item)
    return result


def _rh_balance_rejection(error):
    """Recognize an explicit unaccepted submission, never an uncertain POST."""
    if error == 'RH submission rejected: code=605':
        return True
    for prefix in ('RH submit rejected: ', 'RH AI App submit rejected: '):
        if not error.startswith(prefix):
            continue
        try:
            response = json.loads(error[len(prefix):])
        except (ValueError, TypeError):
            return False
        return (isinstance(response, dict) and not response.get('taskId')
                and str(response.get('errorCode') or response.get('code')) == '605'
                and str(response.get('status') or '').upper() not in ('RUNNING', 'QUEUED'))
    return False


def public_job_error(job):
    error = str((job or {}).get("error") or "").strip()
    if not error:
        return None
    job_id = str((job or {}).get("id") or "unknown")[:64]
    backend = str((job or {}).get("generation_backend") or "cloud")
    if backend == 'cloud' and _rh_balance_rejection(error):
        reason = '后续提交失败' if job.get('rh_task_id') else '任务未提交'
        return f"云端账户余额不足，{reason}。请联系管理员检查额度。面板任务号 {job_id}"
    if backend == "cloud" and "RH_TASK_STOPPED" in error:
        return f"任务已在云端停止或取消。面板任务号 {job_id}"
    if backend == "cloud" and "RH_TASK_UNAVAILABLE" in error:
        return f"云端返回任务不存在或已过期，已结束等待。请联系维护人员核对记录。面板任务号 {job_id}"
    if backend == "local":
        return f"本地任务失败；请使用面板任务号 {job_id} 联系维护人员"
    if backend == "api":
        detail = error.lower()
        suffix = f"面板任务号 {job_id}"
        if _dreamapi_pending(job):
            return f"上一次请求的结果尚未确认，正在保留该任务的等待窗口以避免重复计费。请查询原任务或联系维护人员，勿重复提交。{suffix}"
        if "image download" in detail or "image url" in detail:
            return f"上游已返回图片地址，但下载保存失败。请联系维护人员恢复原结果，勿重复生成。{suffix}"
        # Only publish fixed translations: never echo raw provider messages,
        # credentials, URLs, or upstream request identifiers to the browser.
        if any(marker in detail for marker in ("safety_violations", "safety system", "content_policy_violation", "content policy")):
            category = "（上游判定涉及色情或性内容）" if re.search(r"safety_violations\s*=\s*\[[^\]]*\bsexual\b", detail) else ""
            return f"未通过上游内容安全审核{category}。请检查提示词及素材是否符合内容要求，再提交。{suffix}"
        if "image generation is not enabled for this group" in detail:
            return f"当前密钥所属分组未开启生图权限，请在中转站后台检查分组设置。{suffix}"
        if "prior request outcome is still uncertain" in detail:
            return f"上一次请求的结果尚未确认，已暂停新请求以避免重复计费。请先查询原任务或联系维护人员。{suffix}"
        if "generation already in progress" in detail:
            return f"API已有任务正在生成，请等待该任务结束。{suffix}"
        if "workstation egress failed" in detail:
            return f"API转发服务连接失败，结果尚未确认。请检查工作站及网络，勿连续重试。{suffix}"
        if any(marker in detail for marker in ("insufficient_quota", "insufficient quota", "insufficient balance", "quota exceeded", "credit balance")):
            return f"中转站或上游账户额度不足，请检查余额及套餐额度。{suffix}"
        if "timeout" in detail or "timed out" in detail:
            return f"等待超时，尚不能确认上游是否已生成。请先检查原任务或中转站记录，勿连续重试。{suffix}"
        if any(marker in detail for marker in ("connection refused", "connection reset", "remote end closed", "urlopen error", "network is unreachable")):
            return f"API网络连接失败或中断，结果尚未确认。请检查转发服务及网络，勿连续重试。{suffix}"
        if "no completed image" in detail:
            return f"上游已响应，但没有返回可用图片；仅凭此错误无法判断具体原因，请联系维护人员核查。{suffix}"
        if "malformed response" in detail:
            return f"上游返回的数据格式异常，无法解析结果。请联系维护人员检查接口兼容性。{suffix}"
        if any(marker in detail for marker in ("invalid image data", "undecodable image data", "unsupported image format")):
            return f"上游返回的图片数据无法读取或格式不受支持，请联系维护人员核查。{suffix}"
        if "too large" in detail:
            return f"上游返回的数据或图片超过处理上限，请联系维护人员检查输出大小。{suffix}"
        if "dreamapi_key is not configured" in detail:
            return f"服务器尚未配置生图密钥，请联系维护人员配置。{suffix}"
        code = re.match(r"^DreamAPI HTTP (\d{3}):", error)
        if code and code.group(1) in {"400", "401", "403", "404", "429"}:
            reason = {
                "400": "生图参数未被接口接受，请检查模型、尺寸、质量和提示词；若仍失败请联系维护人员。",
                "401": "生图密钥无效或已失效，请检查中转站密钥。",
                "403": "当前账号没有权限使用此次生图请求，请检查分组权限及模型授权。",
                "404": "请求的模型或接口不存在，请检查中转站支持的模型及接口配置。",
                "429": "上游请求过于频繁或并发已满，请稍后再试，勿连续点击。",
            }[code.group(1)]
            return reason + suffix
        match = re.match(r"^DreamAPI HTTP (5\d\d):", error)
        if match:
            return (
                f"图像API上游暂时失败（HTTP {match.group(1)}），可手动重新生成；"
                f"请勿连续提交。面板任务号 {job_id}"
            )
        return f"API任务失败，暂时无法识别具体原因，请联系维护人员查看服务端记录。{suffix}"
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
            "manual_negative", "seed", "seed_mode", "generation_backend", "api_model",
            "api_quality", "api_fit", "api_ratio",
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


def public_video_thumbnails(job):
    media = public_job_media(job.get('media'))
    source_id = job.get('thumbnail_source_job') or job['id']
    if source_id != job['id'] and _jobs.get(source_id, {}).get('request_session_hash') != job.get('request_session_hash'):
        return {}
    return {key: '/api/video-thumbnail/'+source_id+'/'+digest+'.jpg'
            for key, digest in job.get('input_thumbnails', {}).items()
            if key in media and re.fullmatch(r'[0-9a-f]{32}', str(digest))}


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
        rejection = f"RH submit rejected: {last}"
        if _rh_balance_rejection(rejection):
            raise ProviderTaskFailed(rejection)
        raise RuntimeError(rejection)
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
    rejection = "RH AI App submit rejected: " + json.dumps(result, ensure_ascii=False)[:600]
    if _rh_balance_rejection(rejection):
        raise ProviderTaskFailed(rejection)
    raise RuntimeError(rejection)

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
    status = str(r.get("status") or "").strip().upper()
    unavailable = str(r.get("errorCode") or "") == "1004"
    stopped = status in {"CANCELLED", "CANCELED", "STOPPED", "CANCEL", "STOP", "ABORTED"}
    if unavailable or stopped:
        if job is not None:
            job["provider_status"] = "UNAVAILABLE" if unavailable else "STOPPED"
            job["provider_finished"] = time.time()
        if stopped and job is not None and job.get('cancel_requested'):
            raise ProviderTaskCancelled('RH_TASK_STOPPED')
        raise ProviderTaskFailed("RH_TASK_UNAVAILABLE" if unavailable else "RH_TASK_STOPPED")
    results = r.get("results") or []
    coins = normalize_rh_coins(r, results)
    if coins is None and status == "SUCCESS":
        coins = normalize_rh_coins({}, rh_output_details(task_id))
    if job is not None and coins is not None:
        job["rh_coins"] = coins
    if status == "FAILED":
        if job is not None:
            job.update(provider_status='FAILED', provider_finished=time.time())
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

def _request_provider_cancel(job, task_id):
    """Only the existing poll worker sends cancellation; never release on ACK."""
    if not job.get('cancel_requested') or time.time() < job.get('cancel_retry_after', 0):
        return
    with _lock_jobs:
        job['cancel_retry_after'] = time.time() + 60
        save_jobs()
    try:
        req = urllib.request.Request('https://www.runninghub.ai/task/openapi/cancel',
            data=json.dumps({'apiKey': RH_KEY, 'taskId': task_id}).encode(),
            headers={'Content-Type':'application/json', 'Authorization':'Bearer '+RH_KEY})
        result = _provider_json_request(req, timeout=RH_TIMEOUT_QUERY)
        if result.get('code') == 0:
            job['cancel_note'] = '取消请求已送达，等待云端确认停止'
        else:
            job['cancel_note'] = '云端尚未确认取消（代码 '+str(result.get('code'))+'），将继续核对'
    except Exception:
        job['cancel_note'] = '取消请求连接不明，正在重试并核对云端状态'
    with _lock_jobs:
        save_jobs()


def _rh_wait_task(job, task_id, deadline, progress_base=0, progress_span=100):
    query_failures = 0
    last_query_error = None
    while time.time() < deadline:
        try:
            _request_provider_cancel(job, task_id)
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


def _upload_media_content_type_from_header(header, filename, expected_type):
    """Validate media magic/container bytes and require a matching suffix."""
    filename = _safe_upload_filename(filename)
    suffix = pathlib.Path(filename).suffix.lower()
    expected_type = str(expected_type or "").lower()
    if expected_type == "image":
        ctype = image_content_type(header, filename)
        allowed = {
            "image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"},
            "image/webp": {".webp"},
        }
        if not ctype or suffix not in allowed[ctype]:
            raise ValueError("invalid image media or extension")
        return ctype
    if expected_type == "audio":
        if header[:4] == b'RIFF' and header[8:12] == b'WAVE' and suffix == '.wav':
            return 'audio/wav'
        if (header[:3] == b'ID3' or (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224)) and suffix == '.mp3':
            return 'audio/mpeg'
        if header[:4] == b'fLaC' and suffix == '.flac':
            return 'audio/flac'
        if header[:4] == b'OggS' and suffix == '.ogg':
            return 'audio/ogg'
        if header[4:8] == b'ftyp' and suffix == '.m4a':
            return 'audio/mp4'
        raise ValueError('invalid audio media or extension')
    if expected_type != "video":
        raise ValueError("unsupported upload media type")
    if len(header) >= 12 and header[4:8] == b"ftyp" and suffix in {".mp4", ".mov"}:
        return "video/quicktime" if suffix == ".mov" else "video/mp4"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI " and suffix == ".avi":
        return "video/x-msvideo"
    if header[:4] == b"\x1aE\xdf\xa3" and suffix in {".mkv", ".webm"}:
        return "video/webm" if suffix == ".webm" else "video/x-matroska"
    raise ValueError("invalid video media or extension")


def upload_media_content_type(data, filename, expected_type):
    """Validate in-memory media by magic/container bytes and matching suffix."""
    return _upload_media_content_type_from_header(bytes(data[:16]), filename, expected_type)


def upload_media_file_content_type(path, filename, expected_type):
    """Validate a temporary upload without materializing it in process memory."""
    with pathlib.Path(path).open("rb") as source:
        return _upload_media_content_type_from_header(source.read(16), filename, expected_type)


REJECTED_VIDEO_CODECS = {"av01"}
_UNSUPPORTED_VIDEO_MESSAGES = {
    "av01": "该视频是 AV1 编码，云端视频节点无法读取。请先转成 H.264（MP4）再上传，例如：ffmpeg -i 原视频.mp4 -c:v libx264 -pix_fmt yuv420p -c:a aac 新视频.mp4",
}
_MP4_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}
_MP4_MAX_BOXES = 4096
_MP4_MAX_DEPTH = 8
_MKV_SCAN_BYTES = 1024 * 1024


class UnsupportedVideoCodec(ValueError):
    """Raised when an uploaded video uses a codec the cloud nodes cannot read."""

    def __init__(self, codec):
        self.codec = codec
        self.public_message = _UNSUPPORTED_VIDEO_MESSAGES.get(
            codec, "该视频编码云端视频节点无法读取，请先转成 H.264（MP4）再上传")
        super().__init__(self.public_message)


def _mp4_sample_fourccs(f, size):
    """Collect stsd sample-entry fourccs by seeking through the box tree (no full read)."""
    found = []
    budget = [_MP4_MAX_BOXES]

    def walk(start, end, depth):
        pos = start
        while pos + 8 <= end and budget[0] > 0:
            budget[0] -= 1
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                return
            box_size, kind = struct.unpack(">I4s", head)
            header = 8
            if box_size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    return
                box_size = struct.unpack(">Q", ext)[0]
                header = 16
            elif box_size == 0:
                box_size = end - pos
            if box_size < header:
                return
            box_end = min(pos + box_size, end)
            if kind in _MP4_CONTAINER_BOXES and depth < _MP4_MAX_DEPTH:
                walk(pos + header, box_end, depth + 1)
            elif kind == b"stsd" and box_end - pos >= header + 16:
                f.seek(pos + header + 8)
                entry = f.read(8)
                if len(entry) == 8:
                    found.append(entry[4:8].decode("latin-1"))
            pos = box_end

    try:
        walk(0, size, 0)
    except Exception:
        pass
    return found


def _detect_rejected_video_codec(f, size, header):
    """Return a rejected codec fourcc/name, or None (unknown/allowed). Never raises."""
    try:
        if header[4:8] == b"ftyp":
            for code in _mp4_sample_fourccs(f, size):
                if code in REJECTED_VIDEO_CODECS:
                    return code
        elif header[:4] == b"\x1aE\xdf\xa3":
            f.seek(0)
            if b"V_AV1" in f.read(_MKV_SCAN_BYTES) and "av01" in REJECTED_VIDEO_CODECS:
                return "av01"
    except Exception:
        pass
    return None


def _check_video_codec_bytes(data):
    data = bytes(data)
    codec = _detect_rejected_video_codec(io.BytesIO(data), len(data), data[:16])
    if codec:
        raise UnsupportedVideoCodec(codec)


def _check_video_codec_file(path):
    with pathlib.Path(path).open("rb") as source:
        source.seek(0, 2)
        size = source.tell()
        source.seek(0)
        header = source.read(16)
        codec = _detect_rejected_video_codec(source, size, header)
    if codec:
        raise UnsupportedVideoCodec(codec)


def validate_workflow_upload(workflow, input_key, filename, raw):
    mapping = (workflow.get("rh_media") or {}).get(str(input_key or ""))
    if not mapping:
        raise ValueError("unknown upload input")
    safe_name = _safe_upload_filename(filename)
    media_type = str(mapping.get("type") or "").lower()
    ctype = upload_media_content_type(raw, safe_name, media_type)
    if media_type == "video":
        _check_video_codec_bytes(raw)
    return safe_name, ctype, media_type


def validate_workflow_upload_file(workflow, input_key, filename, path):
    mapping = (workflow.get("rh_media") or {}).get(str(input_key or ""))
    if not mapping:
        raise ValueError("unknown upload input")
    safe_name = _safe_upload_filename(filename)
    media_type = str(mapping.get("type") or "").lower()
    ctype = upload_media_file_content_type(path, safe_name, media_type)
    if media_type == "video":
        _check_video_codec_file(path)
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


def rh_input_enabled(w, mapping, params):
    if w.get('id') == 'h3_remix_full' and mapping.get('node') == '339':
        face = (w.get('rh_params') or {})['face_refine']
        if not _coerce_rh_control(params.get('face_refine', face['default']), face):
            return False
    rule = mapping.get('depends_on')
    if not rule:
        return True
    control = (w.get('rh_params') or {}).get(rule['key'], {})
    value = params.get(rule['key'], control.get('default'))
    return _coerce_rh_control(value, control) == rule['value']


def normalize_rh_workflow_inputs(w, media, params):
    """Whitelist and type-check inputs using one trusted workflow schema."""
    if not isinstance(media, dict) or not isinstance(params, dict):
        raise ValueError("media and params must be objects")
    trusted_media = {}
    for key, mapping in (w.get("rh_media") or {}).items():
        if not rh_input_enabled(w, mapping, params):
            continue
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
    if w.get('id') == 'h3_remix_full':
        validate_h3_remix_inputs(trusted_media, trusted_params)
    if w.get('id') == 'h3_reference_optimized':
        validate_h3_optimized_inputs(trusted_media, trusted_params)
    return trusted_media, trusted_params


def validate_h3_optimized_inputs(media, params):
    if not any(key.startswith(('reference_image', 'source_video')) for key in media):
        raise ValueError('请至少上传一张参考图或一个参考视频；音频需搭配图像或视频使用')
    if len(media) > 12:
        raise ValueError('图片、视频和音频合计最多上传 12 个素材')
    if params['first_steps'] > params['total_steps']:
        raise ValueError('一采步数不能超过总采样步数')
    if params['second_pass'] and params['first_steps'] >= params['total_steps']:
        raise ValueError('开启二次采样时，总采样步数必须大于一采步数')
    if not (params['save_first'] or (params['second_pass'] and params['save_second'])):
        raise ValueError('请至少保留一个已启用采样阶段的输出')


def validate_h3_remix_inputs(media, params):
    """Reject impossible branches before queue admission or credit reservation."""
    image_mode = params.get('mode') == 'image'
    active = {key: value for key, value in media.items() if key != 'face_reference'}
    if image_mode:
        active = {key: value for key, value in active.items() if key in ('reference_image', 'reference_image_2')}
    if not any(key.startswith(('reference_image', 'source_video')) for key in active):
        raise ValueError('请至少上传一张参考图或一个参考视频；首尾帧模式请上传前两张参考图')
    if params.get('original_audio') and not any(key.startswith(('source_video', 'reference_audio')) for key in active):
        raise ValueError('使用原声需要参考视频或参考音频；首尾帧模式请关闭原声')
    alignment = params.get('audio_duration_auto')
    if alignment in ('audio', 'video') and ('reference_audio' if alignment == 'audio' else 'source_video') not in active:
        raise ValueError('自动对齐时长需要上传对应的第一个视频或音频；首尾帧模式请使用手动时长')
    second, face = params.get('second_pass'), params.get('face_refine')
    if not (params.get('save_first') or (second and params.get('save_second')) or (face and params.get('save_face'))):
        raise ValueError('请至少保留一个已启用采样阶段的输出')
    if face and params.get('face_target') == 'reference_identity' and not (media.get('face_reference') or active.get('reference_image')):
        raise ValueError('按参考图匹配人脸需要第一张参考图或独立人脸参考图')
    for key in active:
        if key.startswith(('source_video', 'reference_audio')):
            start, end = params.get(key+'_start', 0), params.get(key+'_end', 0)
            if end and end <= start:
                raise ValueError('素材截取终点必须晚于起点；填 0 表示截取至末尾')


def rh_build_generic_node_info(job, w):
    """Serialize every declared generic control, including explicit false/0."""
    nodes = []
    for key, mapping in (w.get("rh_media") or {}).items():
        if not rh_input_enabled(w, mapping, job.get('params') or {}):
            continue
        value = (job.get("provider_media") or {}).get(key)
        if value not in (None, ""):
            nodes.append({"nodeId": str(mapping["node"]),
                          "fieldName": mapping["field"], "fieldValue": value})
    for key, mapping in (w.get("rh_params") or {}).items():
        if mapping.get('client_only'):
            continue
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


def rh_build_single_image_graph(job, w):
    """Only a server-owned graph may change wiring; browser graphs are ignored."""
    graph = json.loads(json.dumps(w['rh_optional_reference']['single_image_graph']))
    for row in rh_build_generic_node_info(job, w):
        graph[row['nodeId']]['inputs'][row['fieldName']] = row['fieldValue']
    return graph


def rh_submit_single_image_graph(job, w):
    # The documented advanced API accepts a full API-format workflow string.
    # Submit once: a lost response must never create a duplicate billed task.
    body = {'apiKey': RH_KEY, 'workflowId': w['rh_workflow_id'],
            'workflow': json.dumps(rh_build_single_image_graph(job, w), ensure_ascii=False),
            'addMetadata': False, 'instanceType': w.get('rh_instance_type', 'default'),
            'usePersonalQueue': False}
    req = urllib.request.Request('https://www.runninghub.ai/task/openapi/create',
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + RH_KEY}, method='POST')
    try:
        response = _provider_json_request(req, timeout=min(RH_TIMEOUT_SUBMIT, RH_SUBMIT_HARD_TIMEOUT))
    except Exception as error:
        raise RuntimeError('RH submit outcome unknown after transport failure; not retried to avoid duplicate charge') from error
    data = response.get('data') or {}
    if not isinstance(data, dict):
        data = {}
    task_id = data.get('taskId')
    if response.get('code') == 0 and task_id and data.get('taskStatus') in ('QUEUED', 'RUNNING'):
        return task_id
    # Do not echo a provider payload: it can include the graph or credentials.
    if task_id:
        raise RuntimeError('RH graph submit rejected for taskId ' + str(task_id))
    rejection = 'RH graph submit rejected: code=' + str(response.get('code'))
    if _rh_balance_rejection(str(response.get('msg') or '')):
        raise ProviderTaskFailed(rejection)
    raise RuntimeError(rejection)


def rh_run_generic(job, w):
    """Run one trusted schema-driven RunningHub workflow."""
    workflow_id = w.get("rh_workflow_id")
    if not workflow_id:
        raise RuntimeError("workflow has no trusted rh_workflow_id")
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    optional = w.get('rh_optional_reference')
    if optional and not rh_input_enabled(w, (w.get('rh_media') or {})[optional['media']], job.get('params') or {}):
        task_id = rh_submit_single_image_graph(job, w)
    else:
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
    except ProviderTaskCancelled:
        job.update(status='cancelled', provider_status='CANCELLED', queue_hold=False,
                   cancel_confirmed_at=time.time(), error=None)
    except ProviderTaskFailed as error:
        job.update(status='error', provider_status='FAILED', queue_hold=False,
                   provider_failure_confirmed_at=time.time(), provider_finished=time.time(),
                   error=f"恢复云任务失败：{str(error)[:450]}")
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


def _dreamapi_provider_size(job):
    """Map a panel ratio to the exact concrete canvas accepted by Images API."""
    ratio = str(job.get("api_ratio") or "")
    if ratio:
        dimensions = DREAMAPI_PROVIDER_SIZE_BY_RATIO.get(ratio)
        if dimensions is None:
            raise ValueError("unknown DreamAPI image ratio")
        return f"{dimensions[0]}x{dimensions[1]}"
    width = _bounded_request_int(job.get("width"))
    height = _bounded_request_int(job.get("height"))
    if width == height:
        return "1024x1024"
    return "1536x1024" if width > height else "1024x1536"


def _dreamapi_redact_error(detail):
    detail = str(detail or "upstream error")
    if DREAMAPI_KEY:
        detail = detail.replace(DREAMAPI_KEY, "[REDACTED]")
    detail = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1[REDACTED]", detail)
    detail = re.sub(r"(?i)((?:api[_ -]?key|token|secret)\s*[:=]?\s*)[A-Za-z0-9._~+/=-]{8,}", r"\1[REDACTED]", detail)
    return re.sub(r"[\x00-\x1f\x7f]+", " ", detail).strip()[:500]


def _dreamapi_request_endpoint():
    if DREAMAPI_CONNECTION_MODE not in {"direct", "workstation"}:
        raise ValueError("invalid DreamAPI connection mode")
    if DREAMAPI_CONNECTION_MODE == "direct":
        parsed = urllib.parse.urlparse(DREAMAPI_BASE_URL)
        loopback_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not loopback_http or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/v1"}):
            raise ValueError("DreamAPI direct base must be HTTPS or numeric loopback HTTP, with optional /v1")
        # Validate the configured port before admitting a billable request.
        parsed.port
        return DREAMAPI_BASE_URL.removesuffix("/v1") + "/v1/images/generations"
    if not DREAMAPI_EGRESS_URL:
        raise ValueError("DreamAPI workstation endpoint is not configured")
    parsed = urllib.parse.urlparse(DREAMAPI_EGRESS_URL)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username or parsed.password
            or parsed.path not in {"/dreamapi/images/generations", "/dreamapi/responses"}
            or parsed.query or parsed.fragment):
        raise RuntimeError("DREAMAPI_EGRESS_URL must be a loopback HTTP endpoint")
    # Existing installations used the old bridge path in their environment.
    # Normalize only the validated loopback route; never change its authority.
    return parsed._replace(path="/dreamapi/images/generations").geturl()


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


def build_dreamapi_input(positive, negative, size, orientation, max_total=1600,
                         final_size=None):
    """Build the complete bounded native Images API prompt."""
    prefix = [
        f"Required canvas: exactly {size}, {orientation} composition.",
    ]
    if final_size and final_size != size:
        prefix.append(
            f"Compose for a centered final crop to {final_size}; keep every important "
            "subject inside that narrower safe area."
        )
    else:
        prefix.append(
            "Keep the important subject inside the center safe area so a final crop will not cut it off."
        )
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


class DreamAPIHTTPError(RuntimeError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"DreamAPI HTTP {status}: {_dreamapi_redact_error(detail)}")


def _dreamapi_pending(job):
    return (job.get("generation_backend") == "api"
            and float(job.get("api_pending_until") or 0) > time.time())


def _dreamapi_checkpoint(job, **fields):
    with _lock_jobs:
        job.update(fields)
        save_jobs()


def _dreamapi_request_json(request, data, timeout):
    """Bound connect plus the complete response body by one wall-clock deadline."""
    box = {}

    def worker():
        try:
            endpoint = urllib.parse.urlparse(request.full_url) if isinstance(request, urllib.request.Request) else None
            if endpoint and endpoint.scheme == "http" and endpoint.hostname in {"127.0.0.1", "::1"}:
                # A same-host upstream must not inherit an outbound proxy or
                # redirect the authenticated request outside the loopback service.
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                response_context = opener.open(request, data, timeout=timeout)
            else:
                response_context = _urlopen_bounded(request, data, timeout)
            with response_context as response:
                box["result"] = _dreamapi_read_json(response)
        except urllib.error.HTTPError as error:
            raw = error.read(8192)
            try:
                body = json.loads(raw.decode("utf-8", "replace"))
                value = body.get("error") if isinstance(body, dict) else None
                detail = (value.get("message") if isinstance(value, dict) else value if isinstance(value, str) else None)
                detail = str(detail or (body.get("message") if isinstance(body, dict) else None) or error.reason)
            except Exception:
                detail = str(error.reason or "upstream error")
            box["error"] = DreamAPIHTTPError(error.code, detail)
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


def _dreamapi_download_image(url):
    """Fetch an upstream image without credentials, pinning each public HTTPS hop."""
    box = {}

    def worker():
        try:
            target = url
            deadline = time.monotonic() + 60
            for _ in range(4):
                parsed = urllib.parse.urlsplit(target)
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                        or parsed.password or parsed.fragment or parsed.port not in {None, 443}):
                    raise ValueError("unsafe DreamAPI image URL")
                addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
                ips = [row[4][0] for row in addresses]
                if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                    raise ValueError("unsafe DreamAPI image URL destination")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("DreamAPI image download timeout")
                # Preserve TLS hostname verification/SNI, but connect to the already
                # validated IP instead of resolving the hostname a second time.
                connection = http.client.HTTPSConnection(parsed.hostname, timeout=remaining,
                                                          context=ssl.create_default_context())
                pinned_ip = ips[0]
                connection._create_connection = lambda address, timeout, source_address=None: socket.create_connection(
                    (pinned_ip, 443), timeout, source_address)
                try:
                    connection.request("GET", urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
                                       headers={"Accept": "image/*"})
                    response = connection.getresponse()
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.getheader("Location")
                        if not location:
                            raise ValueError("invalid DreamAPI image URL redirect")
                        target = urllib.parse.urljoin(target, location)
                        continue
                    if response.status != 200:
                        raise RuntimeError(f"DreamAPI image download HTTP {response.status}")
                    box["result"] = _response_bytes_limited(response, DREAMAPI_MAX_IMAGE_BYTES)
                    return
                finally:
                    connection.close()
            raise ValueError("too many DreamAPI image URL redirects")
        except Exception as error:
            box["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(60)
    if thread.is_alive():
        raise TimeoutError("DreamAPI image download timeout; generation must not be resubmitted")
    if "error" in box:
        raise box["error"]
    return box["result"]


def dreamapi_run_image(job, jobdir):
    """Generate one image with DreamAPI Images and archive an exact-size PNG."""
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
    job["api_transport"] = "images"
    job["api_dispatch_profile"] = "native_images"
    job["dreamapi_contract_sha256"] = DREAMAPI_CONTRACT_SHA256
    job["api_action_mode"] = "direct"
    job["api_connection_mode"] = DREAMAPI_CONNECTION_MODE
    output_size = _dreamapi_size(job["width"], job["height"])
    provider_size = _dreamapi_provider_size(job)
    orientation = "square" if job["width"] == job["height"] else (
        "landscape" if job["width"] > job["height"] else "portrait")
    upstream_input, compacted, positive_chars = build_dreamapi_input(
        job.get("prompt"), job.get("negative_prompt"), provider_size, orientation,
        final_size=output_size)
    job["api_prompt_compacted"] = compacted
    job["api_upstream_prompt_chars"] = positive_chars
    payload = {
        "model": model,
        "prompt": upstream_input,
        "size": provider_size,
        "quality": quality,
        "n": 1,
        "output_format": "png",
    }
    request = urllib.request.Request(
        _dreamapi_request_endpoint(),
        headers={
            "Authorization": f"Bearer {DREAMAPI_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    job["provider_status"] = "API_GENERATING"
    job["progress_pct"] = 15
    job["api_provider_size"] = provider_size
    job["provider_started"] = time.time()
    if DREAMAPI_CONNECTION_MODE == "direct":
        _dreamapi_checkpoint(job, api_pending_until=time.time() + DREAMAPI_TIMEOUT + 60)
    try:
        result = _dreamapi_request_json(
            request, json.dumps(payload).encode("utf-8"), DREAMAPI_TIMEOUT
        )
    except DreamAPIHTTPError as error:
        if 400 <= error.status < 500 and error.status != 408:
            _dreamapi_checkpoint(job, api_pending_until=0, provider_rejection_confirmed_at=time.time(), provider_http_status=error.status)
        raise
    _dreamapi_checkpoint(job, api_pending_until=0)
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise RuntimeError("DreamAPI returned malformed response")
    if any(not isinstance(item, dict) for item in result["data"]):
        raise RuntimeError("DreamAPI returned malformed response")
    response_id = str(result.get("id") or "")
    response_shape = ",".join(sorted(str(key) for key in result))
    job["api_response_id"] = response_id
    job["api_response_shape"] = response_shape
    image_item = next((item for item in result["data"]
                       if isinstance(item.get("b64_json"), str)
                       and item.get("b64_json")), None)
    url_item = next((item for item in result["data"]
                     if isinstance(item.get("url"), str) and item.get("url")), None)
    if not image_item and not url_item:
        suffix = f" (response_id={response_id or 'none'}, keys={response_shape or 'none'})"
        raise RuntimeError("DreamAPI returned no completed image" + suffix)
    _dreamapi_checkpoint(job, provider_result_received_at=time.time())
    job["provider_status"] = "API_PROCESSING_RESULT"
    job["progress_pct"] = 75
    if image_item:
        encoded = image_item["b64_json"]
        if len(encoded) > ((DREAMAPI_MAX_IMAGE_BYTES + 2) // 3) * 4 + 4:
            raise RuntimeError("DreamAPI image data is too large")
        try:
            source = base64.b64decode(encoded, validate=True)
        except Exception as error:
            raise RuntimeError("DreamAPI returned invalid image data") from error
    else:
        # Private ledger only: public job serializers have explicit allowlists.
        _dreamapi_checkpoint(job, api_result_url=url_item["url"])
        try:
            source = _dreamapi_download_image(url_item["url"])
        except Exception as error:
            raise RuntimeError("DreamAPI image download failed: " + type(error).__name__) from error
        image_item = url_item
    if len(source) > DREAMAPI_MAX_IMAGE_BYTES:
        raise RuntimeError("DreamAPI image data is too large")
    job["provider_status"] = "API_VALIDATING_RESULT"
    job["progress_pct"] = 88
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
        target = (int(job["width"]), int(job["height"]))
        jobdir = pathlib.Path(jobdir)
        jobdir.mkdir(parents=True, exist_ok=True)
        filename = "dreamapi.png"
        destination = jobdir / filename
        geometry_normalized = decoded.size != target
        reencoded = decoded.format != "PNG" or geometry_normalized
        if not reencoded:
            destination.write_bytes(source)
        else:
            converted = decoded.convert("RGB")
            if geometry_normalized and fit == "cover":
                output = ImageOps.fit(
                    converted, target, method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            elif geometry_normalized:
                output = ImageOps.contain(
                    converted, target, method=Image.Resampling.LANCZOS,
                )
                canvas = Image.new("RGB", target, "white")
                canvas.paste(
                    output,
                    ((target[0] - output.width) // 2, (target[1] - output.height) // 2),
                )
                output = canvas
            else:
                output = converted
            output.save(destination, "PNG", optimize=True)
    job.update({
        "api_geometry_normalized": geometry_normalized,
        "api_image_reencoded": reencoded,
        "api_upstream_model": str(image_item.get("model") or result.get("model") or "unknown"),
        "api_upstream_quality": str(image_item.get("quality") or result.get("quality") or "unknown"),
        "api_upstream_size": str(image_item.get("size") or result.get("size") or source_size),
        "provider_finished": time.time(), "download_finished": time.time(),
        "provider_status": "API_DONE", "progress_pct": 100,
        "images": [{
            "url": f"/api/image/{job['id']}/{filename}",
            "preview_url": f"/api/image/{job['id']}/{filename}",
            "file": filename, "size": destination.stat().st_size, "remote": False,
            "source_size": source_size, "output_size": output_size, "archive_status": "ready",
        }],
    })
    job.pop("api_result_url", None)
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
    if _membership.enabled and job.get('membership_reserved'):
        with _lock_jobs:
            job['submit_started'] = time.time()
            save_jobs()
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


class _MultipartUploadStream:
    """A seek-free multipart body that sends the media part from a file object."""

    def __init__(self, source, size, prefix, suffix):
        self.source = source
        self.size = int(size)
        self.prefix = prefix
        self.suffix = suffix
        self._part = 0
        self._offset = 0

    def __len__(self):
        return len(self.prefix) + self.size + len(self.suffix)

    def read(self, amount=-1):
        if amount is None or amount < 0:
            amount = len(self)
        chunks = []
        remaining = amount
        while remaining > 0 and self._part < 3:
            if self._part == 0:
                part = self.prefix
            elif self._part == 1:
                part = self.source.read(remaining)
                if not part:
                    self._part += 1
                    self._offset = 0
                    continue
                chunks.append(part)
                remaining -= len(part)
                continue
            else:
                part = self.suffix
            chunk = part[self._offset:self._offset + remaining]
            if chunk:
                chunks.append(chunk)
                remaining -= len(chunk)
                self._offset += len(chunk)
            if self._offset >= len(part):
                self._part += 1
                self._offset = 0
        return b"".join(chunks)

    def close(self):
        self.source.close()


def _rh_upload_stream(source, size, filename, ctype="application/octet-stream", timeout=120):
    """Upload one known-size stream to RunningHub without copying media bytes."""
    boundary = "----rh" + uuid.uuid4().hex
    safe_suffix = pathlib.Path(_safe_upload_filename(filename)).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", safe_suffix):
        raise ValueError("unsafe upload extension")
    provider_filename = "upload_" + uuid.uuid4().hex + safe_suffix
    def _file(name, fname, ctype_):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{fname}\"\r\nContent-Type: {ctype_}\r\n\r\n").encode()
    prefix = _file("file", provider_filename, ctype)
    suffix = b"\r\n" + f"--{boundary}--\r\n".encode()
    body = _MultipartUploadStream(source, size, prefix, suffix)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {RH_KEY}",
        "Content-Length": str(len(body)),
    }
    req = urllib.request.Request(f"{RH_BASE}/media/upload/binary",
                                 data=body, headers=headers)
    try:
        resp = _provider_json_request(req, timeout=timeout)
    finally:
        body.close()
    if resp.get("code") not in (0, 200):
        raise RuntimeError(f"RH upload failed: {resp.get('code')} {resp.get('message')}")
    data = resp.get("data") or {}
    fname = data.get("filename") or data.get("fileName")
    if not isinstance(fname, str) or not re.fullmatch(r"(?:api|openapi)/[A-Za-z0-9._/-]{1,900}", fname):
        raise RuntimeError("RH upload returned no fileName")
    if ".." in pathlib.PurePosixPath(fname).parts:
        raise RuntimeError("RH upload returned unsafe fileName")
    return fname


def rh_upload_file(data, filename, ctype="application/octet-stream", timeout=120):
    """Legacy in-memory upload helper retained for JSON upload compatibility."""
    return _rh_upload_stream(io.BytesIO(data), len(data), filename, ctype, timeout)


def rh_upload_temp_file(path, filename, ctype="application/octet-stream", timeout=120):
    """Stream a private temporary upload to RunningHub without loading it in RAM."""
    path = pathlib.Path(path)
    return _rh_upload_stream(path.open("rb"), path.stat().st_size, filename, ctype, timeout)


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


def rh_build_h3_graph(job, w):
    # The graph is server-owned; never accept executable workflow JSON from a browser.
    graph = json.loads((BASE/'video_wf/h3_edit_multi_api.json').read_text(encoding='utf8'))
    references = graph['225']['inputs']
    assert graph['225']['class_type'] == 'MiniMaxH3ReferenceToVideo'
    for i in range(2,5):
        key = 'reference_image_'+str(i)
        if not job.get('provider_media',{}).get(key): continue
        node = str(292+i)
        graph[node] = {'class_type':'LoadImage','inputs':{'image':job['provider_media'][key]}}
        references['ref_images.ref_image_'+str(i-1)] = [node,0]
    for item in rh_build_video_node_info(job,w):
        graph[item['nodeId']]['inputs'][item['fieldName']] = item['fieldValue']
    # Preserve both model consumers (guider and scheduler). Optional reference
    # images retain 294-296; LoRA slots use a separate range, 301-303.
    original = graph.pop('285')
    model = original['inputs']['model']
    params = job.get('params') or {}
    chain = {}
    for slot in range(1, 4):
        model_key = f'lora_{slot}_model'
        strength_key = f'lora_{slot}_strength'
        model_schema = w['rh_params'][model_key]
        strength_schema = w['rh_params'][strength_key]
        selected = _coerce_rh_control(params.get(model_key, model_schema['default']), model_schema)
        strength = _coerce_rh_control(params.get(strength_key, strength_schema['default']), strength_schema)
        if selected == 'none' or strength == 0:
            continue
        filename = w['rh_lora_catalog'][selected]
        node = str(300 + slot)
        if node in graph:
            raise RuntimeError('LoRA node conflicts with workflow node')
        chain[node] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'lora_name': filename, 'strength_model': strength, 'model': model}}
        model = [node, 0]
    for node in graph.values():
        for field, value in node['inputs'].items():
            if value == ['285', 0]:
                node['inputs'][field] = model
    graph.update(chain)
    return graph


def rh_build_h3_remix_graph(job, w):
    """Build only trusted branches; no browser-supplied graphs, paths or API keys."""
    media, params = normalize_rh_workflow_inputs(w, job.get('provider_media') or {}, job.get('params') or {})
    graph = json.loads(json.dumps(w['rh_graph']))
    for key, mapping in w['rh_params'].items():
        if mapping.get('node') and key in params:
            graph[mapping['node']]['inputs'][mapping['field']] = params[key]
    setup = graph['295']['inputs']
    setup['prompt'] = job.get('prompt', params['prompt'])
    setup.update(prompt_optimizer_enabled=False, prompt_optimizer_api_key='', prompt_optimizer_api_url='', embedded_media_json='[]')
    records, counts = [], {'image': 0, 'video': 0, 'audio': 0}
    def trim_time(seconds):
        millis = round(seconds * 1000)
        return f'{millis // 60000:02}:{millis // 1000 % 60:02}:{millis % 1000:03}'
    for key, mapping in w['rh_media'].items():
        filename = media.get(key)
        if not filename or key == 'face_reference':
            continue
        kind = mapping['type']
        counts[kind] += 1
        record = dict(media_type=kind, ordinal=counts[kind], filename=filename,
                      subfolder='', storage='input', audio_trim='')
        if kind != 'image':
            record['audio_trim'] = trim_time(params.get(key+'_start', 0))+'-'+trim_time(params.get(key+'_end', 0))
        records.append(record)
        # Transport strings are also declared node inputs, recognized by the
        # provider's input-file resolver; embedded JSON preserves gallery order.
        index = len(records)
        setup[f'media_{index}'] = filename
        setup[f'media_type_{index}'] = kind
        setup[f'media_trim_{index}'] = record['audio_trim']
    setup['embedded_media_json'] = json.dumps(records, ensure_ascii=False)
    second, face = params['second_pass'], params['face_refine']
    setup['second_sampling_output_connected'] = second or face
    graph['321']['inputs']['aspect_ratio'] = params['aspect_ratio']
    for slot, node, row in [(1,'284','lora_1'),(2,'342','lora_1'),(3,'342','lora_2')]:
        graph[node]['inputs'][row].update(on=params[f'lora_{slot}_enabled'],
            strength=params[f'lora_{slot}_strength'], bypass=params[f'lora_{slot}_bypass'])
    if not second:
        graph['340']['inputs']['images'] = ['298', 0]
    if face and media.get('face_reference'):
        graph['339'] = dict(class_type='LoadImage',inputs=dict(image=media['face_reference']))
        graph['340']['inputs']['reference_face'] = ['339', 0]
    if not params['sparse_attention']:
        for node in graph.values():
            for field, value in list(node['inputs'].items()):
                if value == ['327', 0]:
                    node['inputs'][field] = ['325', 0]
    # Do not let an unused switch input force unnecessary audio decoding.
    selected_audio = graph['297']['inputs']['on_true' if params['original_audio'] else 'on_false']
    for node in graph.values():
        for field, value in list(node['inputs'].items()):
            if value == ['297', 0]:
                node['inputs'][field] = selected_audio
    roots = []
    for node, enabled, prefix in [('349',params['save_first'],'JT_H3_First'),
        ('351',second and params['save_second'],'JT_H3_Second'),
        ('350',face and params['save_face'],'JT_H3_Face')]:
        if enabled:
            roots.append(node)
            graph[node]['inputs'].update(filename_prefix=prefix,save_metadata=False,
                save_output=True,pingpong=params['pingpong'],crf=params['crf'])
    # Traverse dependencies instead of leaving disabled sampling/output nodes
    # in the submitted graph. This also removes previews and unused inputs.
    keep = set()
    def visit(node_id):
        if node_id in keep:
            return
        keep.add(node_id)
        for value in graph[node_id]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and isinstance(value[1],int):
                visit(value[0])
    for root in roots:
        visit(root)
    return {node: value for node,value in graph.items() if node in keep}


def rh_build_h3_optimized_graph(job, w):
    """Restore only selected inputs/branches from the verified, server-owned graph."""
    media, params = normalize_rh_workflow_inputs(w, job.get('provider_media') or {}, job.get('params') or {})
    graph = json.loads(json.dumps(w['rh_graph']))
    for key, mapping in w['rh_params'].items():
        if mapping.get('node') and key in params:
            graph[mapping['node']]['inputs'][mapping['field']] = params[key]
    graph['263']['inputs']['text'] = params['prompt']
    # Resolve random seeds to a valid uint before the provider sees the graph.
    # Derivation by task id keeps an uncertain submission retry deterministic.
    if params['seed'] < 0:
        identity = str(job.get('id') or job.get('client_request_id') or 'offline-preview')
        digest = hmac.new(SESSION_SECRET, ('h3-optimized-seed:'+identity).encode(), hashlib.sha256).digest()
        graph['256']['inputs']['noise_seed'] = int.from_bytes(digest[:8], 'big') % (2**53)
    references = graph['265']['inputs']
    for key in list(references):
        if key.startswith(('ref_images.', 'ref_videos.', 'ref_video_audios.', 'ref_audios.')):
            del references[key]
    counts = {'image':0, 'video':0, 'audio':0}
    for key, mapping in w['rh_media'].items():
        if key not in media:
            continue
        node, kind = mapping['node'], mapping['type']
        graph[node]['inputs'][mapping['field']] = media[key]
        index = counts[kind]; counts[kind] += 1
        prefix = {'image':'ref_images.ref_image_', 'video':'ref_videos.ref_video_', 'audio':'ref_audios.ref_audio_'}[kind]
        references[prefix+str(index)] = [node,0]
        if kind == 'video' and params[key+'_audio']:
            references['ref_video_audios.ref_video_audio_'+str(index)] = [node,2]
    def bypass(node_id):
        upstream = graph[node_id]['inputs']['model']
        for row in graph.values():
            for key, value in list(row['inputs'].items()):
                if value == [node_id,0]:row['inputs'][key] = upstream
    if not params['memory_attention']:bypass('58')
    for slot, node in ((3,'322'),(2,'128'),(1,'53')):
        if not params[f'lora_{slot}_enabled'] or params[f'lora_{slot}_strength'] == 0:
            bypass(node)
    roots = []
    for node, enabled, prefix in [('264',params['save_first'],'JT_H3_Optimized_First'),
                                 ('214',params['second_pass'] and params['save_second'],'JT_H3_Optimized_Second')]:
        if enabled:
            roots.append(node)
            graph[node]['inputs'].update(filename_prefix=prefix,save_metadata=False,save_output=True,
                frame_rate=24,pingpong=params['pingpong'],crf=params['crf'])
    keep = set()
    def visit(node):
        if node in keep:return
        keep.add(node)
        for value in graph[node]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and isinstance(value[1],int):
                visit(value[0])
    for root in roots:visit(root)
    return {key:row for key,row in graph.items() if key in keep}


def rh_submit_h3_multi(job, w):
    builders = {'h3_remix_full':rh_build_h3_remix_graph, 'h3_reference_optimized':rh_build_h3_optimized_graph}
    graph = builders.get(w.get('id'), rh_build_h3_graph)(job, w)
    body = {'apiKey':RH_KEY,'workflowId':w['rh_workflow_id'],
            'workflow':json.dumps(graph,ensure_ascii=False),'nodeInfoList':[],
            'addMetadata':False,'usePersonalQueue':False,'instanceType':'default'}
    req = urllib.request.Request('https://www.runninghub.ai/task/openapi/create',
        data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+RH_KEY})
    result = _provider_json_request(req,timeout=RH_TIMEOUT_SUBMIT)
    task_id = (result.get('data') or {}).get('taskId')
    if result.get('code') == 0 and task_id: return str(task_id)
    if task_id:
        # A task already exists even if the response also reports an error.
        # Keep its identifier and poll it instead of enabling a second submit.
        persist_provider_task(job, str(task_id))
        raise ProviderStateUncertain('RH submission returned a task id with an unconfirmed state')
    if result.get('code') not in (None, 0):
        raise ProviderTaskFailed('RH submission rejected: code='+str(result.get('code')))
    raise ProviderStateUncertain('RH submission returned no task id')


def rh_run_video(job, w):
    """RunningHub 视频工作流：上传已就绪的 media fileName 已存于 job["media"]，
    直接提交→轮询→结果 URL（mp4/png）透传保存。"""
    wfid = w.get("rh_workflow_id")
    if not wfid:
        raise RuntimeError("video workflow has no rh_workflow_id")
    node_list = rh_build_video_node_info(job, w)
    job["submit_started"] = time.time()
    job["provider_status"] = "SUBMITTING"
    multi = w.get('id') in ('h3_edit_n', 'h3_remix_full', 'h3_reference_optimized')
    task_id = rh_submit_h3_multi(job,w) if multi else rh_submit(wfid, node_list)
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


def _video_waiting():
    return sorted((j for j in _jobs.values() if j.get('video_queued') and j.get('status') == 'queued'),
                  key=lambda j: (j.get('queue_order', j['created']),
                                 j.get('queue_slot_created', j['created']), j.get('queue_slot_id', j['id'])))


def normalize_video_thumbnail(value):
    from PIL import Image
    if not isinstance(value, str) or len(value) > 44000:
        raise ValueError('thumbnail too large')
    raw = base64.b64decode(value, validate=True)
    if len(raw) > 32768:
        raise ValueError('thumbnail too large')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != 'JPEG' or not (0 < image.width <= 160 and 0 < image.height <= 90):
            raise ValueError('thumbnail must be a small JPEG')
        image.load()
        output = io.BytesIO()
        image.convert('RGB').save(output, format='JPEG', quality=65)
        return output.getvalue()


def _cloud_slot_used(job):
    return job.get('generation_backend') == 'cloud' and (
        job.get('status') in ('running', 'recovering') or job.get('queue_hold'))


def dispatch_video_queue():
    """Claim under shared admission lock, persist before starting any paid work."""
    with _admission_lock, _lock_jobs:
        if _release_draining:
            return
        free = max(0, VIDEO_MAX_CONCURRENT - sum(bool(_cloud_slot_used(j)) for j in _jobs.values()))
        for job in _video_waiting():
            if free <= 0:
                break
            if time.time() >= job.get('queue_media_expires', 0):
                job.update(status='error', error='排队素材已过期，请重新上传后提交', provider_status='QUEUE_EXPIRED')
                save_jobs()
                continue
            if _membership.enabled and job.get('membership_reserved'):
                try:
                    _membership.store.start_job(job['id'])
                except MembershipError as error:
                    if error.code != 'concurrency_limit':
                        job.update(status='error', error=str(error), provider_status='MEMBERSHIP_REJECTED')
                        _membership.settle(job)
                        save_jobs()
                    continue
            job.update(status='running', provider_status='DISPATCHING', dispatch_started=time.time())
            save_jobs()
            try:
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
            except Exception:
                job.update(status='queued', provider_status='QUEUED', dispatch_started=None)
                save_jobs()
                raise
            free -= 1


def video_queue_loop():
    while True:
        try:
            if _membership.enabled:
                with _lock_jobs:
                    membership_jobs = [dict(job) for job in _jobs.values() if job.get('membership_reserved')]
                _membership.reconcile(membership_jobs)
            reconcile_video_queue_holds()
            dispatch_video_queue()
        except Exception:
            # Persistence/launch failures must never trigger a second paid submit.
            pass
        time.sleep(2)


_queue_hold_check_after = 0
_queue_hold_idle_sample = None


def reconcile_video_queue_holds():
    """Release stale reservations after two fully accounted provider samples.

    Unknown submissions are never resubmitted or claimed to have failed upstream.
    The five-minute grace also excludes a delayed submit response from recovery.
    """
    global _queue_hold_check_after, _queue_hold_idle_sample
    now = time.time()
    with _admission_lock, _lock_jobs:
        if _release_draining or now < _queue_hold_check_after:
            return
        held = {j['id']: j.get('submit_started') or j.get('dispatch_started') or j.get('created', now)
                for j in _jobs.values() if j.get('video_queued') and j.get('queue_hold')
                and j.get('status') == 'error' and not j.get('rh_task_id')}
        active = {j['id']: j.get('rh_task_id') for j in _jobs.values()
                  if j.get('generation_backend') == 'cloud' and j.get('status') in ('running', 'recovering')}
        if not held or any(now-start < 300 for start in held.values()) or any(not tid for tid in active.values()):
            _queue_hold_idle_sample = None
            return
        _queue_hold_check_after = now + 60
    try:
        req = urllib.request.Request('https://www.runninghub.ai/uc/openapi/accountStatus',
            data=json.dumps({'apikey': RH_KEY}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+RH_KEY})
        response = _provider_json_request(req, timeout=RH_TIMEOUT_QUERY)
        count = (response.get('data') or {}).get('currentTaskCounts')
        if response.get('code') != 0 or isinstance(count, bool) or str(count) != str(len(active)):
            _queue_hold_idle_sample = None
            return
        # A nonzero account count is safe only if every slot is explained by a
        # known task which the provider still confirms as active. Never infer
        # this from our potentially stale local statuses alone.
        if len(set(active.values())) != len(active) or any(
                rh_query(tid)[0] not in ('RUNNING', 'QUEUED') for tid in active.values()):
            _queue_hold_idle_sample = None
            return
    except Exception:
        _queue_hold_idle_sample = None
        return
    with _admission_lock, _lock_jobs:
        current_active = {j['id']: j.get('rh_task_id') for j in _jobs.values()
                          if j.get('generation_backend') == 'cloud' and j.get('status') in ('running', 'recovering')}
        current_held = {j['id']: j.get('submit_started') or j.get('dispatch_started') or j.get('created', now)
                        for j in _jobs.values() if j.get('video_queued') and j.get('queue_hold')
                        and j.get('status') == 'error' and not j.get('rh_task_id')}
        if _release_draining or current_active != active or current_held != held:
            _queue_hold_idle_sample = None
            return
        sample = (held, active)
        if _queue_hold_idle_sample != sample:
            _queue_hold_idle_sample = sample
            return
        before = {}
        for job_id, started in held.items():
            job = _jobs.get(job_id)
            if not job or job.get('status') != 'error' or not job.get('queue_hold') or job.get('rh_task_id'):
                continue
            before[job_id] = dict(job)
            job.update(queue_hold=False, queue_hold_released_at=time.time(),
                       queue_hold_release_reason='provider_active_accounted_twice' if active else 'provider_idle_confirmed_twice',
                       provider_status='SUBMIT_UNCONFIRMED_IDLE',
                       error='提交时连接中断，未收到任务号；已核对云端任务并释放占位，旧任务结果仍未知，未自动重提。')
        try:
            if before:
                save_jobs()
        except Exception:
            for job_id, previous in before.items():
                _jobs[job_id].clear(); _jobs[job_id].update(previous)
            raise
        _queue_hold_idle_sample = None


def _cloud_failure_confirmed(job):
    """Also recognize terminal exceptions saved before failure states were fixed."""
    if job.get('status') != 'error' or job.get('generation_backend') != 'cloud':
        return False
    if job.get('provider_failure_confirmed_at'):
        return True
    error = str(job.get('error') or '').removeprefix('恢复云任务失败：')
    if job.get('rh_task_id'):
        return error.startswith('RH task failed: ')
    return (re.fullmatch(r'RH submission rejected: code=[1-9]\d*', error) is not None
            or _rh_balance_rejection(error))


def video_ui_terminal(job):
    """UI clearing must not hide work whose provider outcome is unresolved."""
    confirmed_failure = _cloud_failure_confirmed(job)
    return (job.get('status') in ('done', 'error', 'cancelled')
            and not job.get('queue_hold')
            and not _cloud_slot_used(job)
            and not _dreamapi_pending(job)
            and (confirmed_failure or (
                not (job.get('cancel_requested') and not job.get('cancel_confirmed_at'))
                and job.get('provider_status') not in ('RUNNING', 'QUEUED', 'RECOVERING', 'SUBMITTING'))))


def video_redoable(job):
    return job.get('style_id') in ('video', 'realism') and video_ui_terminal(job)


def clear_video_ui(session_id, scope, page='video'):
    """Persist display-only clearing, retaining job inputs, outputs and favorites."""
    flags = {
        'history': ('history_cleared', 'task_cleared', 'gallery_cleared'),
        'errors': ('history_cleared', 'task_cleared', 'gallery_cleared'),
        'gallery': ('gallery_cleared',),
    }
    if scope not in flags:
        raise ValueError('未知的清除范围')
    with _lock_jobs:
        matching = [job for job in _jobs.values()
                    if job.get('style_id') == page
                    and session_owns_record(session_id, job) and video_ui_terminal(job)
                    and (scope != 'errors' or job.get('status') in ('error', 'cancelled'))
                    and (scope != 'gallery' or job.get('status') == 'done')]
        before = {job['id']: dict(job) for job in matching
                  if any(not job.get(flag) for flag in flags[scope])}
        for job in matching:
            if job['id'] in before:
                job.update({flag: True for flag in flags[scope]})
        try:
            if before:
                save_jobs()
        except Exception:
            for job_id, previous in before.items():
                _jobs[job_id].clear(); _jobs[job_id].update(previous)
            raise
        return {'ok': True, 'scope': scope, 'cleared_ids': [job['id'] for job in matching]}


def clear_creator_ui(session_id, scope=None, ids=None):
    """2026-11-12: hide the caller's failed / cancelled creator records, or the listed finished ones
    (records whose pictures have expired). Display only: the job, its outputs and favourites stay."""
    if scope not in (None, 'errors'):
        raise ValueError('未知的清除范围')
    ids = [] if ids is None else ids
    if (not isinstance(ids, list) or len(ids) > 60
            or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{12}', item) for item in ids)):
        raise ValueError('任务编号不正确')
    if scope is None and not ids:
        raise ValueError('没有要清除的记录')
    wanted = set(ids)
    with _lock_jobs:
        matching = [job for job in _jobs.values()
                    if job.get('workflow') == 'anima02'
                    and session_owns_record(session_id, job) and video_ui_terminal(job)
                    and (job['id'] in wanted or (scope == 'errors' and job.get('status') in ('error', 'cancelled')))]
        before = {job['id']: dict(job) for job in matching if not job.get('history_cleared')}
        for job in matching:
            job['history_cleared'] = True
        try:
            if before:
                save_jobs()
        except Exception:
            for job_id, previous in before.items():
                _jobs[job_id].clear(); _jobs[job_id].update(previous)
            raise
        return {'ok': True, 'scope': scope, 'cleared_ids': sorted(job['id'] for job in matching)}


# 2026-11-12: showcase pictures and display names for the scheme cards, managed by the administrator.
SHOWCASE_DIR = DATA_DIR / 'showcase'
SHOWCASE_MAX_IMAGE_BYTES = 2 * 1024 * 1024
SHOWCASE_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}
_lock_showcase = threading.Lock()


def _showcase_read():
    try:
        data = json.loads((SHOWCASE_DIR / 'showcase.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}


def _showcase_write(items):
    SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOWCASE_DIR / 'showcase.json'
    temporary = target.with_name('showcase.json.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temporary, target)
    keep = {item.get('image') for item in items.values()}
    for path in SHOWCASE_DIR.iterdir():
        if re.fullmatch(r'[0-9a-f]{32}\.(?:png|jpg|webp)', path.name) and path.name not in keep:
            try: path.unlink()
            except OSError: pass


def _showcase_image_kind(raw):
    if raw[:8] == b'\x89PNG\r\n\x1a\n': return 'png'
    if raw[:3] == b'\xff\xd8\xff': return 'jpg'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': return 'webp'
    return None


def public_showcase():
    with _lock_showcase:
        items = _showcase_read()
    return {key: {'name': str(value.get('name') or ''),
                  'image': '/api/showcase-image/' + value['image'] if value.get('image') else ''}
            for key, value in items.items() if value.get('name') or value.get('image')}


def showcase_admin(actor, body, action='showcase'):
    """Administrator view and edits. body None = list; otherwise save one card or delete it."""
    if body is None:
        return {'items': public_showcase()}
    workflow_id = body.get('workflow_id')
    if not isinstance(workflow_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', workflow_id):
        raise ValueError('功能编号不正确')
    with _lock_showcase:
        items = _showcase_read()
        if action == 'showcase/delete':
            items.pop(workflow_id, None)
        else:
            # A creator style card is addressed as "style.<style id>".
            if workflow_id not in WORKFLOWS and not (workflow_id.startswith('style.')
                                                     and workflow_id[6:] in STYLE_PRESETS):
                raise ValueError('没有这个功能')
            entry = dict(items.get(workflow_id) or {})
            if 'name' in body:
                name = body['name']
                if not isinstance(name, str) or len(name.strip()) > 40 or re.search(r'[\x00-\x1f\x7f]', name):
                    raise ValueError('名字最多 40 个字')
                entry['name'] = name.strip()
            if body.get('remove_image') is True:
                entry.pop('image', None)
            if body.get('image') is not None:
                image = body['image']
                match = isinstance(image, str) and re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)', image)
                if not match:
                    raise ValueError('图片格式不支持，请用 PNG、JPG 或 WebP')
                try:
                    raw = base64.b64decode(match.group(1), validate=True)
                except ValueError:
                    raise ValueError('图片数据不完整') from None
                kind = _showcase_image_kind(raw)
                if not kind:
                    raise ValueError('图片格式不支持，请用 PNG、JPG 或 WebP')
                if len(raw) > SHOWCASE_MAX_IMAGE_BYTES:
                    raise ValueError('图片超过 2MB')
                filename = hashlib.sha256(raw).hexdigest()[:32] + '.' + kind
                SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
                (SHOWCASE_DIR / filename).write_bytes(raw)
                entry['image'] = filename
            entry['updated'] = int(time.time())
            if entry.get('name') or entry.get('image'):
                items[workflow_id] = entry
            else:
                items.pop(workflow_id, None)
        _showcase_write(items)
    return {'items': public_showcase()}


def video_queue_snapshot(session_id, page='video'):
    with _lock_jobs:
        waiting = _video_waiting()
        positions = {j['id']: i + 1 for i, j in enumerate(waiting)}
        own = [j for j in _jobs.values() if j.get('style_id') == page and session_owns_record(session_id, j)
               and not (j.get('task_cleared') and video_ui_terminal(j))]
        active = sorted((j for j in own if j.get('status') in ('queued', 'running', 'recovering')),
                        key=lambda j: (j.get('status') == 'queued', positions.get(j['id'], 0), j['created']))
        recent = sorted((j for j in own if j.get('status') not in ('queued', 'running', 'recovering')),
                        key=lambda j: j['created'], reverse=True)[:20]
        rows = []
        for j in active + recent:
            row = {k: j.get(k) for k in ('id', 'workflow', 'wf_name', 'status', 'provider_status', 'progress_pct',
                                        'created', 'elapsed', 'prompt', 'negative_prompt', 'rh_coins', 'queue_revision')}
            row.update(media=public_job_media(j.get('media')), params=public_job_params(j),
                       error=public_job_error(j), position=positions.get(j['id']),
                       editable=j.get('status') == 'queued', queue_hold=bool(j.get('queue_hold')))
            row.update(cancellable=j.get('generation_backend') == 'cloud' and j.get('status') in ('running','recovering'),
                       cancel_requested=bool(j.get('cancel_requested')), cancel_note=j.get('cancel_note'),
                       cancel_confirmed=bool(j.get('cancel_confirmed_at')),
                       gallery_cleared=bool(j.get('gallery_cleared')), redoable=video_redoable(j))
            row['thumbnails'] = public_video_thumbnails(j)
            rows.append(row)
        return {'jobs': rows, 'running': sum(bool(_cloud_slot_used(j)) for j in _jobs.values()),
                'waiting': len(waiting), 'limit': VIDEO_MAX_CONCURRENT, 'draining': bool(_release_draining)}


def video_redo_draft(session_id, job_id, page='video'):
    """Read task state without enqueueing; reissue bounded owner capabilities.

    Jobs retain filenames and provider references, never the original bearer
    token (the capability registry stores only its hash). Reissue for the
    authenticated owner's current session without extending the saved TTL.
    No provider request or change to the original job is made here.
    """
    with _lock_jobs:
        job = _jobs.get(str(job_id or ''))
        if not job or not session_owns_record(session_id, job):
            raise LookupError('任务不存在')
        if job.get('style_id') != page:
            raise ValueError('请在原任务所属工作台重做')
        if not video_redoable(job):
            raise ValueError('正在运行或核对中的任务暂不能重做')
        snapshot = dict(job)
        thumbnails = public_video_thumbnails(job)
    workflow_id = str(snapshot.get('workflow') or '')
    w = WORKFLOWS.get(workflow_id)
    if not w or w.get('kind') != 'video' or w.get('backend') != 'runninghub':
        raise ValueError('未知的视频工作流')
    params = public_job_params(snapshot)
    prompt = str(snapshot.get('prompt') or params.get('prompt') or '')
    negative_prompt = str(snapshot.get('negative_prompt') or params.get('negative') or '')
    raw_media = snapshot.get('media') if isinstance(snapshot.get('media'), dict) else {}
    public_media = public_job_media(raw_media)
    provider_media = snapshot.get('provider_media') if isinstance(snapshot.get('provider_media'), dict) else {}
    created = float(snapshot.get('created') or 0)
    expires = float(snapshot.get('queue_media_expires') or (created + UPLOAD_CAPABILITY_TTL))
    now = time.time()
    media = {}
    for key, mapping in (w.get('rh_media') or {}).items():
        if key not in raw_media and key not in provider_media:
            continue
        filename = public_media.get(key) or '素材'
        provider_name = str(provider_media.get(key) or '').strip()
        media_type = str(mapping.get('type') or '').lower()
        valid = bool(now < expires and provider_name and key in public_media)
        token = (issue_upload_capability(provider_name, workflow_id, key, media_type,
                                         filename, session_id, expires=expires)
                 if valid else None)
        entry = {
            'filename': filename,
            'token': token,
            'valid': valid,
            'expired': not valid,
            'expires': expires,
        }
        if key in thumbnails:
            entry['thumbnail'] = thumbnails[key]
        media[key] = entry
    return {
        'job_id': snapshot['id'],
        'workflow': workflow_id,
        'wf_name': snapshot.get('wf_name') or w.get('name') or '',
        'prompt': prompt,
        'negative_prompt': negative_prompt,
        'params': params,
        'media': media,
        'thumbnails': thumbnails,
        'expires': expires,
        'expired': any(not item['valid'] for item in media.values()),
    }


def edit_video_queue(session_id, body, page='video'):
    """Only the owner can edit a not-yet-dispatched job; races fail closed."""
    with _admission_lock, _lock_jobs:
        job = _jobs.get(str(body.get('job_id', '')))
        if not job or not job.get('video_queued') or job.get('style_id') != page or not session_owns_record(session_id, job):
            raise LookupError('任务不存在')
        if body.get('action') == 'cancel_running':
            if job.get('generation_backend') != 'cloud' or job.get('status') not in ('running','recovering'):
                raise ValueError('任务已结束或不支持云端取消，请刷新查看结果')
            if job.get('cancel_requested'):
                return
            if body.get('revision') != job.get('queue_revision', 0):
                raise ValueError('任务已更新，请刷新后重试')
            before = dict(job)
            job.update(cancel_requested=True, cancel_requested_at=time.time(),
                       cancel_note='等待云端确认取消；确认前仍占用并发名额',
                       queue_revision=job.get('queue_revision', 0)+1)
            try:
                save_jobs()
            except Exception:
                job.clear(); job.update(before)
                raise
            return
        if job['status'] != 'queued':
            raise ValueError('任务已经开始或结束，不能再编辑或取消排队')
        if body.get('revision') != job.get('queue_revision', 0):
            raise ValueError('任务已更新，请刷新队列后重试')
        before = {j['id']: dict(j) for j in _video_waiting()}
        action = body.get('action')
        if action == 'cancel':
            job.update(status='cancelled', provider_status='CANCELLED', error=None)
        elif action in ('top', 'up', 'down'):
            # Reassign only this owner's existing slots, leaving every other
            # account's position and optimistic revision untouched.
            rows = [row for row in _video_waiting() if row.get('style_id') == page and session_owns_record(session_id, row)]
            slots = [(row.get('queue_order', row['created']), row.get('queue_slot_created', row['created']),
                      row.get('queue_slot_id', row['id'])) for row in rows]
            index = rows.index(job)
            target = 0 if action == 'top' else max(0, index-1) if action == 'up' else min(len(rows)-1, index+1)
            rows.insert(target, rows.pop(index))
            for slot, row in zip(slots, rows):
                previous_slot = (row.get('queue_order', row['created']), row.get('queue_slot_created', row['created']),
                                 row.get('queue_slot_id', row['id']))
                if previous_slot == slot:
                    continue
                row['queue_order'], row['queue_slot_created'], row['queue_slot_id'] = slot
                if row is not job:
                    row['queue_revision'] = row.get('queue_revision', 0) + 1
        elif action == 'edit':
            w = WORKFLOWS[job['workflow']]
            proposed = body.get('params')
            if not isinstance(proposed, dict):
                raise ValueError('参数必须是对象')
            _, params = normalize_rh_workflow_inputs(w, job['media'], proposed)
            prompt = str(next((params[key] for key in ('prompt', 'instruction', 'requirements', 'text', 'positive')
                               if params.get(key) not in (None, '')), body.get('prompt', job['prompt']))).strip()
            if not prompt and page == 'video':
                raise ValueError('提示词不能为空')
            job.update(params=params, prompt=prompt, negative_prompt=str(params.get('negative', job.get('negative_prompt', ''))))
            job['selection_snapshot'] = upload_bound_snapshot(w, job['media'], params, None, page)
        else:
            raise ValueError('未知的队列操作')
        job['queue_revision'] = job.get('queue_revision', 0) + 1
        try:
            save_jobs()
        except Exception:
            for jid, previous in before.items():
                _jobs[jid].clear()
                _jobs[jid].update(previous)
            raise


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
    except ProviderTaskCancelled:
        job.update(status='cancelled', provider_status='CANCELLED', queue_hold=False,
                   cancel_confirmed_at=time.time(), error=None)
    except ProviderTaskFailed as error:
        job.update(status='error', provider_status='FAILED', queue_hold=False,
                   provider_failure_confirmed_at=time.time(), provider_finished=time.time(),
                   error=str(error)[:500])
    except ProviderStateUncertain:
        job["status"] = "recovering"
        job["provider_status"] = "RECOVERING"
        job["error"] = None
        if job.get('rh_task_id'):
            schedule_cloud_recovery(job)
        elif job.get('video_queued'):
            job.update(status='error', queue_hold=True, error='提交结果未确认，正在核对云端占位')
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:500]
        if job.get('generation_backend') == 'local' and str(e).startswith('ComfyUI execution error:'):
            job['provider_failure_confirmed_at'] = time.time()
        if job.get('video_queued') and job.get('submit_started') and not job.get('rh_task_id') and not isinstance(e, ProviderTaskFailed):
            job['queue_hold'] = True
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
        self._media_owner_slots = MediaOwnerSlots(limit=2)
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


def membership_reservations(actor, body=None):
    """Administrator reconciliation never submits, cancels or edits cloud work."""
    def can_settle(job, reservation):
        if not job:
            return bool(reservation) and time.time() - reservation['created_at'] > 300
        return (job.get('status') == 'error' and not job.get('queue_hold')
                and not _dreamapi_pending(job) and not _cloud_slot_used(job))

    with _admission_lock, _lock_jobs:
        if body is not None:
            job = _jobs.get(body['job_id'])
            reservation = _membership.store.get_reservation(body['job_id'])
            if not can_settle(job, reservation):
                raise MembershipError('job_not_settleable', '任务仍在执行或核对中，不能手工结算', 409)
            result = _membership.store.admin_settle_job(actor, body['job_id'], body.get('success'), body.get('note'))
            _membership._settled_jobs.add(body['job_id'])
            return {'reservation': result}
        rows = []
        for reservation in _membership.store.list_unsettled_reservations(limit=1000):
            job = _jobs.get(reservation['job_id']) or {}
            reason = ('任务账本缺失，请先核对云端记录' if not job else
                      '任务仍在排队' if job.get('status') == 'queued' else
                      '任务正在执行或核对' if job.get('status') in ('running', 'recovering') or job.get('queue_hold') else
                      '云端已返回结果，但结果保存未完成' if job.get('provider_result_received_at') else
                      '提交或结果未确认，请核对后处理' if job.get('status') == 'error' else '等待状态核对')
            rows.append({key: reservation[key] for key in ('job_id', 'user_id', 'kind', 'units', 'state', 'created_at')} | {
                'job_status': job.get('status') or 'error', 'reason': reason, 'can_settle': can_settle(job, reservation)})
        return {'reservations': rows}


_membership.reservations_callback = membership_reservations
_membership.showcase_callback = showcase_admin


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a): pass

    def end_headers(self):
        _membership.security_headers(self)
        super().end_headers()

    def _upload_session(self, create=False):
        if _membership.enabled:
            return _membership.owner_key(self), None
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
        if status:
            _membership.reply(self, status.get('status', 403), {
                'error': status['error'], 'code': status.get('code', 'quota_exhausted')})
            return True
        return False

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

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None, *, media_lease=None):
        if _membership.enabled and urllib.parse.urlsplit(self.path).path.startswith('/api/'):
            headers = dict(headers or {})
            headers['Cache-Control'] = 'private, no-store'
            vary = [item.strip() for item in headers.get('Vary', '').split(',') if item.strip()]
            if not any(item.lower() == 'cookie' for item in vary):
                vary.append('Cookie')
            headers['Vary'] = ', '.join(vary)
        is_large = len(body) >= LARGE_RESPONSE_THRESHOLD
        large_slot_acquired = False
        if is_large and not media_lease:
            large_slot_acquired = acquire_media_slot(self)
        if is_large and not (large_slot_acquired or media_lease):
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
            self._write_body(body, large_slot_acquired=large_slot_acquired or media_lease)
        finally:
            if large_slot_acquired:
                release_media_slot(large_slot_acquired)

    def _write_stream(self, path, ctype, download_name=None, cache_control="private, no-store", allow_range=False):
        path = pathlib.Path(path)
        # Open first so a stat/open race cannot produce a 200 header followed
        # by a second 404 response.
        with path.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            start, end, code = 0, size - 1, 200
            requested = self.headers.get('Range') if allow_range else None
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
                try:
                    if not match or not any(match.groups()) or not size:
                        raise ValueError('invalid range')
                    first, last = match.groups()
                    if first:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    else:
                        suffix = int(last)
                        if suffix <= 0: raise ValueError('invalid suffix')
                        start = max(0, size - suffix)
                    if start >= size or end < start: raise ValueError('unsatisfiable range')
                    code = 206
                except ValueError:
                    return self._send(416, b'', ctype, {'Content-Range': f'bytes */{size}', 'Accept-Ranges': 'bytes'})
            length = max(0, end - start + 1)
            is_large = length >= LARGE_RESPONSE_THRESHOLD
            slot = False
            if is_large:
                slot = acquire_media_slot(self)
            if is_large and not slot:
                return self._send(503, b'{"error":"large response capacity busy"}', headers={"Retry-After": "2"})
            deadline = None
            if is_large:
                with self.server._metrics_lock:
                    self.server._active_large_responses += 1
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                if allow_range:
                    self.send_header('Accept-Ranges', 'bytes')
                if code == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                if download_name:
                    self.send_header("Content-Disposition", f'inline; filename="{download_name}"')
                self.send_header("Cache-Control", cache_control)
                self.send_header("Vary", "Cookie")
                self.end_headers()
                if is_large:
                    self.connection.settimeout(RESPONSE_SOCKET_TIMEOUT)
                    timeout = min(
                        RESPONSE_BODY_MAX_TIMEOUT,
                        RESPONSE_BODY_BASE_TIMEOUT + length / RESPONSE_BODY_MIN_BYTES_PER_SECOND,
                    )
                    deadline = self._start_absolute_deadline(timeout)
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            finally:
                self._cancel_absolute_deadline(deadline)
                if is_large:
                    try:
                        self.connection.settimeout(CLIENT_SOCKET_TIMEOUT)
                    finally:
                        with self.server._metrics_lock:
                            self.server._active_large_responses -= 1
                        release_media_slot(slot)

    def _send_static(self, fp, ctype):
        """Serve text assets with validator caching and bounded gzip."""
        raw = fp.read_bytes()
        etag = '"' + hashlib.sha256(raw).hexdigest()[:24] + '"'
        cache = "no-cache, must-revalidate" if fp.suffix == ".html" else "public, max-age=3600, must-revalidate"
        _, cookie_header = self._upload_session(create=True) if fp.suffix == ".html" else ("", None)
        request = urllib.parse.urlparse(self.path)
        if request.path.startswith("/static/previews/") and fp.suffix == ".webp" and re.fullmatch(r"v=[0-9a-f]{12}", request.query):
            cache = "public, max-age=31536000, immutable"
        if (fp.suffix == ".json"
                and re.fullmatch(r"style-configs\.[0-9a-f]{12}\.json", fp.name)):
            cache = "public, max-age=31536000, immutable"
        if (request.path.startswith("/static/assets/")
                and re.fullmatch(r"[\w-]+\.[0-9a-f]{12}\.[\w]+", fp.name)):
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
        if "gzip" in accepted and len(raw) >= 1024 and ctype.startswith(("text/", "application/javascript", "application/json")):
            body = gzip.compress(raw, compresslevel=6, mtime=0)
            response_headers["Content-Encoding"] = "gzip"
        self._send(200, body, ctype, response_headers)

    def _auth(self):
        return not _membership.enabled or bool(_membership.session(self))

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
        value = json.loads(raw.decode())
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _read_upload_to_temp_file(self, byte_count):
        """Read exactly one bounded raw upload into a private temporary file."""
        byte_count = int(byte_count)
        if byte_count < 1:
            raise ValueError("empty file")
        if byte_count > 60 * 1024 * 1024:
            raise OverflowError("file too large (>60MB)")
        upload_dir = DATA_DIR / "upload_tmp"
        upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix="upload-", suffix=".part", dir=upload_dir)
        path = pathlib.Path(raw_path)
        deadline = self._start_absolute_deadline(min(
            REQUEST_BODY_MAX_TIMEOUT,
            REQUEST_BODY_BASE_TIMEOUT + byte_count / REQUEST_BODY_MIN_BYTES_PER_SECOND,
        ))
        remaining = byte_count
        try:
            with os.fdopen(fd, "wb") as target:
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError("incomplete request body")
                    target.write(chunk)
                    remaining -= len(chunk)
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            self._cancel_absolute_deadline(deadline)

    def _handle_direct_upload(self, action):
        if not self._auth(): return self._send(401)
        if _release_draining: return self._release_in_progress()
        session_id = self._require_session()
        if not session_id: return
        try:
            body = self._read_json(8192)
            if not isinstance(body, dict): raise ValueError('bad json')
            if action == 'start':
                wid, key = str(body.get('workflow', '')), str(body.get('input_key', ''))
                workflow = WORKFLOWS.get(wid, {})
                mapping = workflow.get('rh_media', {}).get(key)
                if workflow.get('kind') != 'video' or not mapping:
                    raise ValueError('无效的上传位置')
                name = _safe_upload_filename(body.get('filename', ''))
                size = int(body.get('size', 0))
                if not 0 < size <= 60*1024*1024: raise ValueError('文件必须在 60MB 以内')
                media_type = mapping.get('type')
                suffix = pathlib.Path(name).suffix.lower()
                allowed = {'.mp4','.mov','.webm','.avi','.mkv'} if media_type == 'video' else {'.png','.jpg','.jpeg','.webp'}
                if suffix not in allowed: raise ValueError('文件类型与上传位置不匹配')
                # Personal uploads send bytes directly to RunningHub. The
                # server-proxy bandwidth quota does not apply to this receipt.
                token = direct_uploads.challenge(SESSION_SECRET, _session_hash(session_id),
                    dict(workflow=wid, input_key=key, filename=name, media_type=media_type, size=size))
                result = {'challenge': token}
            else:
                if action not in ('verify','register'): return self._send(404)
                provider_name = body.get('provider_name', '') if action == 'register' else ''
                scope = direct_uploads.verify(SESSION_SECRET, RH_KEY, _session_hash(session_id),
                    body.get('challenge'), body.get('proof'), provider_name)
                if action == 'verify': result = {'ok': True}
                else:
                    if not provider_name: raise ValueError('缺少云端文件标识')
                    token = issue_upload_capability(provider_name, scope['workflow'], scope['input_key'],
                        scope['media_type'], scope['filename'], session_id)
                    result = {'uploadToken': token, 'filename': scope['filename']}
            return self._send(200, json.dumps(result, ensure_ascii=False).encode(),
                              headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError, OverflowError) as error:
            return self._send(400, json.dumps({'error': str(error)}, ensure_ascii=False).encode())

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if _membership.guard(self, path):
            return
        if path.startswith('/api/result-media/'):
            if not self._auth():
                return self._send(401, b'{"error":"unauthorized"}')
            match = re.fullmatch(r'/api/result-media/([0-9a-f]{12})/(\d{1,4})', path)
            if not match:
                return self._send(404, b'{"error":"not found"}')
            session_id, _ = self._upload_session()
            with _lock_jobs:
                job = _jobs.get(match[1])
                images = (job or {}).get('images') or []
                index = int(match[2])
                if not job or not session_owns_record(session_id, job) or index >= len(images) or not images[index].get('remote'):
                    return self._send(404, b'{"error":"not found"}')
                item = dict(images[index])
            filename = safe_output_filename(item.get('file') or 'result.mp4')
            # Vary by the session cookie; login/logout also clear the browser cache.
            # Keep originals intact and allow Chromium to reuse completed byte ranges.
            is_video = pathlib.Path(filename).suffix.lower() in ('.mp4', '.webm', '.mov', '.mkv')
            if is_video:
                etag = '"' + hashlib.sha256((job['id'] + ':' + str(index) + ':' + item['url']).encode()).hexdigest() + '"'
                cache = 'private, max-age=3600'
                if self.headers.get('If-None-Match') == etag:
                    return self._send(304, b'', headers={'ETag': etag, 'Cache-Control': cache, 'Vary': 'Cookie'})
                return stream_media(self, item['url'], filename, cache_control=cache, etag=etag)
            return stream_media(self, item['url'], filename)
        if path == '/api/media-library':
            return self._send(410, json.dumps({'error': '临时素材库已取消，请刷新页面使用个人直传'}, ensure_ascii=False).encode())
        if path.startswith('/api/video-thumbnail/'):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            match = re.fullmatch(r'/api/video-thumbnail/([0-9a-f]{12})/([0-9a-f]{32})\.jpg', path)
            if not match: return self._send(404)
            jid, digest = match.groups()
            session_id, _ = self._upload_session(create=False)
            with _lock_jobs:
                job = _jobs.get(jid)
                allowed = job and session_owns_record(session_id, job) and digest in job.get('input_thumbnails', {}).values()
            target = JOBS_DIR / jid / ('input-thumb-'+digest+'.jpg')
            if not allowed or not target.is_file(): return self._send(404)
            return self._send(200, target.read_bytes(), 'image/jpeg',
                              {'Cache-Control': 'private, no-store', 'Vary': 'Cookie', 'X-Content-Type-Options': 'nosniff'})
        if path in ('/api/video-queue', '/api/image-edit-queue'):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id, _ = self._upload_session(create=False)
            page = 'realism' if path == '/api/image-edit-queue' else 'video'
            return self._send(200, json.dumps(video_queue_snapshot(session_id, page), ensure_ascii=False).encode())
        if path == '/api/video-redo-draft' or path.startswith('/api/video-redo-draft/'):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id, _ = self._upload_session(create=False)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            job_id = path.split('/api/video-redo-draft/', 1)[1] if path.startswith('/api/video-redo-draft/') else (query.get('job_id') or [''])[0]
            try:
                draft = video_redo_draft(session_id, job_id, 'video')
            except LookupError:
                return self._send(404, b'{"error":"job not found"}')
            except ValueError as error:
                return self._send(409, json.dumps({'error': str(error)}, ensure_ascii=False).encode())
            return self._send(200, json.dumps(draft, ensure_ascii=False).encode(),
                              headers={'Cache-Control': 'private, no-store', 'Vary': 'Cookie'})
        if path == "/api/live":
            payload = {"ok": True, "service": "comfy-panel", **self.server.liveness_snapshot()}
            self._send(200, json.dumps(payload, separators=(",", ":")).encode())
        elif path == "/api/health":
            ok, msg = comfy_ok()
            dreamapi_status = dreamapi_transport_status()
            self._send(200, json.dumps({"ok": ok, "comfy": bool(ok), "local_comfy_ok": ok,
                                        "dreamapi_configured": bool(DREAMAPI_KEY),
                                        **dreamapi_status,
                                        "dreamapi_contract_sha256": DREAMAPI_CONTRACT_SHA256,
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
            self._send(200, preview.read_bytes(), "image/jpeg", {"Cache-Control": "private, no-store", "Vary": "Cookie"})
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
            with p.open('rb') as source:
                data = source.read(64)
            ctype = fav.get("favorite_media_type") or image_content_type(data, p.name) or "application/octet-stream"
            self._write_stream(p, ctype, allow_range=ctype.startswith('video/'),
                               cache_control='private, max-age=3600' if ctype.startswith('video/') else 'private, no-store')
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
                    "api_dispatch_profile", "dreamapi_contract_sha256", "api_action_mode",
                    "api_transport", "api_geometry_normalized", "api_image_reencoded",
                    "api_response_shape",
                    "api_prompt_compacted", "api_upstream_prompt_chars",
                    "api_upstream_model", "api_upstream_quality", "api_upstream_size",
                    "api_provider_size",
                    "media", "params", "history_cleared", "task_cleared", "gallery_cleared",
                    "client_request_id",
                    "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                )
                j = {k: src.get(k) for k in allowed}
                j['images'] = public_job_images(src)
                j["error"] = public_job_error(src)
                j["media"] = public_job_media(src.get("media"))
                j["params"] = public_job_params(src)
                j["selection_snapshot"] = public_job_selection_snapshot(src.get("selection_snapshot"))
                j["redoable"] = video_redoable(src)
            self._send(200, json.dumps(j, ensure_ascii=False).encode())
        elif path.startswith("/api/job-prompt/"):
            # Owner-only full prompt for the result stream's 复用 action; the
            # list endpoint only carries a short excerpt.
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            jid = path.split("/api/job-prompt/", 1)[1]
            with _lock_jobs:
                src = _jobs.get(jid)
                session_id, _ = self._upload_session(create=False)
                if not src or not session_owns_record(session_id, src):
                    return self._send(404, b'{"error":"job not found"}')
                body = {"id": jid, "prompt": str(src.get("prompt") or ""), "prompt_mode": src.get("prompt_mode")}
            self._send(200, json.dumps(body, ensure_ascii=False).encode(),
                       headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})
        elif path == "/api/showcase":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            self._send(200, json.dumps({"items": public_showcase()}, ensure_ascii=False).encode())
        elif path.startswith("/api/showcase-image/"):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            name = path.split("/api/showcase-image/", 1)[1]
            if not re.fullmatch(r'[0-9a-f]{32}\.(?:png|jpg|webp)', name) or not (SHOWCASE_DIR / name).is_file():
                return self._send(404, b'{"error":"not found"}')
            self._send(200, (SHOWCASE_DIR / name).read_bytes(), SHOWCASE_TYPES[name.rsplit('.', 1)[1]],
                       headers={"X-Content-Type-Options": "nosniff"})
        elif path == "/api/library-counts":
            # Sidebar badges: how many history records and favourites the page's own lists hold.
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            scope = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("scope") or [None])[0]
            if scope not in LIBRARY_SCOPES:
                return self._send(400, b'{"error":"invalid library scope"}')
            session_id, _ = self._upload_session(create=False)
            with _lock_jobs:
                body = {"history": len(scoped_history_jobs(owned_history_sources(session_id), scope, limit=None)),
                        "favorites": sum(1 for item in _favorites.values()
                                         if session_owns_record(session_id, item, "owner_session_hash")
                                         and favorite_in_scope(item, scope))}
            self._send(200, json.dumps(body).encode())
        elif path == "/api/jobs":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            with _lock_jobs:
                # Lightweight copies: full prompts can be many KB, so the list
                # carries only a short excerpt (240 characters); the full
                # text is fetched on demand from /api/job-prompt/<id>.
                items = []
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                scope = (query.get("scope") or [None])[0]
                style = (query.get("style") or [None])[0]
                session_id, _ = self._upload_session(create=False)
                owned_sources = owned_history_sources(session_id)
                limit, before = 12, None
                # 2026-11-11: the creator's library pages through its history like the other two.
                if scope in ('video', 'realism') or (scope == 'creator' and (query.get('limit') or query.get('before'))):
                    try:
                        limit = max(1, min(30, int((query.get('limit') or ['12'])[0])))
                        if query.get('before'):
                            value = json.loads(query['before'][0])
                            before = (float(value[0]), str(value[1]))
                            if not math.isfinite(before[0]): raise ValueError('bad cursor')
                    except (ValueError, TypeError, IndexError, KeyError):
                        return self._send(400, b'{"error":"invalid history cursor"}')
                sources = scoped_history_jobs(owned_sources, scope, style, limit=limit, before=before)
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
                        "api_dispatch_profile", "dreamapi_contract_sha256", "api_action_mode",
                        "api_transport", "api_geometry_normalized", "api_image_reencoded",
                        "api_response_shape",
                        "api_prompt_compacted", "api_upstream_prompt_chars",
                        "api_upstream_model", "api_upstream_quality", "api_upstream_size",
                        "api_provider_size",
                        "client_request_id", "history_cleared", "task_cleared", "gallery_cleared",
                        "transfer_index", "transfer_total", "transfer_started", "transfer_finished",
                    )
                    j = {k: src.get(k) for k in allowed}
                    j['images'] = public_job_images(src)
                    j["error"] = public_job_error(src)
                    j["media"] = public_job_media(src.get("media"))
                    j["selection_snapshot"] = public_job_selection_snapshot(src.get("selection_snapshot"))
                    prompt_text = str(src.get("prompt") or "")
                    j["prompt_excerpt"] = prompt_text[:240]
                    j["prompt_truncated"] = len(prompt_text) > 240
                    if scope in ('video', 'realism'):
                        j['thumbnails'] = public_video_thumbnails(src)
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
                self._send(200, data, "image/webp", {"Cache-Control": "private, no-store", "Vary": "Cookie"})
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
                self._send(200, data, "image/jpeg", {"Cache-Control": "private, no-store", "Vary": "Cookie"})
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
            lease = None
            sending = False
            try:
                match = re.fullmatch(r'/api/rh-preview/([0-9a-f]{12})/(\d{1,4})', path)
                if not match:
                    return self._send(404, b'{"error":"remote image not found"}')
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
                if set(query) - {'size'} or len(query.get('size', ['view'])) != 1:
                    return self._send(400, b'{"error":"invalid preview size"}')
                size = query.get('size', ['view'])[0]
                if size not in {'thumb', 'view'}:
                    return self._send(400, b'{"error":"invalid preview size"}')
                jobid, idx = match[1], int(match[2])
                session_id, _ = self._upload_session(create=False)
                with _lock_jobs:
                    job = _jobs.get(jobid)
                    images = (job or {}).get("images") or []
                    if (not job or not session_owns_record(session_id, job) or idx >= len(images)
                            or not images[idx].get("remote") or not remote_output_is_image(images[idx])):
                        return self._send(404, b'{"error":"remote image not found"}')
                    item = dict(images[idx])
                owner = _session_hash(session_id)
                data = _result_image_cache.lookup(owner, jobid, idx, item['url'], size)
                if data is not None:
                    # Small cached images follow the existing ordinary HTTP
                    # budget, so slow video/original streams cannot block the
                    # gallery. _send still leases a media slot for large views.
                    sending = True
                    return self._send(200, data, 'image/jpeg', {'Cache-Control': 'private, no-store', 'Vary': 'Cookie'})
                # Cache misses share the original-media transfer budget. Every
                # hit and miss is authenticated and owner-checked above.
                lease = acquire_media_slot(self)
                if lease is None:
                    return self._send(503, b'{"error":"media capacity busy"}', headers={'Retry-After': '2'})
                def fetch_source(max_bytes):
                    suffix = pathlib.PurePosixPath(str(item.get('file') or urllib.parse.urlsplit(item['url']).path)).suffix.lower()
                    suffix = suffix if suffix in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'} else '.png'
                    descriptor, name = tempfile.mkstemp(prefix='source-', suffix=suffix, dir=_result_image_cache.root)
                    os.close(descriptor)
                    source = pathlib.Path(name)
                    try:
                        download_media(item['url'], source, timeout=25, max_bytes=max_bytes)
                        return source.read_bytes()
                    finally:
                        source.unlink(missing_ok=True)
                data = _result_image_cache.get_or_create(owner, jobid, idx, item['url'], fetch_source)[size]
                sending = True
                self._send(200, data, 'image/jpeg', {'Cache-Control': 'private, no-store', 'Vary': 'Cookie'}, media_lease=lease)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except (PreviewError, ValueError):
                self._send(415, b'{"error":"image preview unavailable"}')
            except Exception:
                if not sending:
                    self._send(502, b'{"error":"preview temporarily unavailable"}', headers={'Retry-After': '2'})
            finally:
                if lease:
                    release_media_slot(lease)
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
            if path in ("/", "/realism", "/video"):
                return self._send_static(root / "app.html", "text/html; charset=utf-8")
            if _membership.enabled:
                # The directory also holds archived standalone prototypes and
                # past hashed builds. Only the current release is public.
                public_paths = {'/static/app.html', '/static/app-manifest.json', '/static/favicon.png'}
                try:
                    manifest = json.loads((root / 'app-manifest.json').read_text(encoding='utf-8'))
                    public_paths.update(item for item in manifest['assets']
                                        if isinstance(item, str) and re.fullmatch(
                                            r'/static/assets/[\w-]+\.[0-9a-f]{12}\.[a-z0-9]+', item))
                except (OSError, ValueError, KeyError, TypeError):
                    return self._send(503, b'{"error":"release assets unavailable"}')
                if path not in public_paths:
                    return self._send(404, b'not found')
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
                if (j.get("status") in ("running", "recovering") or j.get('queue_hold') or _dreamapi_pending(j)) and (generation_backend is None or j.get("generation_backend", "cloud") == generation_backend):
                    return j["id"]
        return None

    def do_POST(self):
        global _release_draining
        request_target = urllib.parse.urlparse(self.path)
        path = request_target.path
        if _membership.guard(self, path, write=True):
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._send(400, b'{"error":"invalid content length"}')
        body_limit = json_body_limit(path)
        if content_length < 0 or content_length > body_limit:
            return self._send(413, b'{"error":"request body too large"}')
        if path.startswith('/api/media-library/'):
            return self._send(410, json.dumps({'error': '临时素材库已取消，请刷新页面使用个人直传'}, ensure_ascii=False).encode())
        if path.startswith('/api/upload-direct-'):
            return self._handle_direct_upload(path.rsplit('-', 1)[-1])
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
                return self._send(502, json.dumps({"error": "云端上传失败，请稍后重试"}, ensure_ascii=False).encode())
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
                    w, body.get("media") or {}, session_id, body.get('params') or {})
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
                return self._send(502, json.dumps({"error": "云端上传失败，请稍后重试"}, ensure_ascii=False).encode())
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
                    w, submitted_media, session_id, params)
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
        if path in ('/api/upload-start', '/api/upload-chunk', '/api/upload-finish'):
            if not self._auth(): return self._send(401)
            if _release_draining: return self._release_in_progress()
            session_id = self._require_session()
            if not session_id: return
            owner = _session_hash(session_id)
            try:
                if path == '/api/upload-start':
                    body = self._read_json(4096)
                    if not isinstance(body,dict): raise ValueError('bad json')
                    w = WORKFLOWS.get(str(body.get('workflow', '')), {})
                    key = str(body.get('input_key', ''))
                    name = _safe_upload_filename(body.get('filename', ''))
                    size = int(body.get('size', 0))
                    if (w.get('kind') not in ('video', 'rh_workflow', 'ai_app')
                            or w.get('backend') != 'runninghub'
                            or key not in w.get('rh_media', {})):
                        raise ValueError('无效的上传位置')
                    quota = reserve_upload_attempt(session_id, size)
                    if self._upload_quota_rejection(quota): return
                    uid = _video_upload_staging.start(DATA_DIR, owner, (w['id'], key, name), size)
                    return self._send(200, json.dumps({'upload_id':uid}).encode())
                if path == '/api/upload-chunk':
                    values = urllib.parse.parse_qs(request_target.query)
                    uid = values.get('id',[''])[0]
                    offset = int(values.get('offset',['-1'])[0])
                    _video_upload_staging.get(uid, owner)
                    if not 0 < content_length <= 512*1024: raise ValueError('无效的分块大小')
                    # An idle limit plus a generous per-chunk deadline: a slow
                    # but progressing large file no longer loses all its bytes.
                    self.connection.settimeout(60)
                    deadline = self._start_absolute_deadline(120)
                    try: raw = self.rfile.read(content_length)
                    finally:
                        self._cancel_absolute_deadline(deadline)
                        self.connection.settimeout(CLIENT_SOCKET_TIMEOUT)
                    if len(raw) != content_length: raise ValueError('分块未传完')
                    offset = _video_upload_staging.chunk(uid, owner, offset, raw)
                    return self._send(200, json.dumps({'offset':offset}).encode())
                body = self._read_json(4096)
                if not isinstance(body,dict): raise ValueError('bad json')
                def process(row):
                    wid, key, name = row['scope']; w = WORKFLOWS[wid]
                    name, ctype, media_type = validate_workflow_upload_file(w,key,name,row['path'])
                    started = time.monotonic()
                    remote_name = rh_upload_temp_file(row['path'],name,ctype)
                    token = issue_upload_capability(remote_name,wid,key,media_type,name,session_id)
                    print('VIDEO_UPLOAD_OK bytes='+str(row['size'])+' provider_seconds='+str(round(time.monotonic()-started,2)),flush=True)
                    return {'uploadToken':token,'filename':name,'mediaType':ctype,'input_key':key}
                result = _video_upload_staging.finish(str(body.get('upload_id','')),owner,process)
                return self._send(200,json.dumps(result,ensure_ascii=False).encode())
            except LookupError as error:
                return self._send(404,json.dumps({'error':str(error)},ensure_ascii=False).encode())
            except (ValueError, TypeError, OverflowError) as error:
                return self._send(400,json.dumps({'error':str(error)},ensure_ascii=False).encode())
        if path == "/api/upload":
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type == "application/octet-stream":
                if self.headers.get("Content-Length") is None:
                    return self._send(411, b'{"error":"content length required"}')
                values = urllib.parse.parse_qs(request_target.query, keep_blank_values=True)
                workflow_id = str((values.get("workflow") or [""])[0])
                input_key = str((values.get("input_key") or [""])[0])
                filename = str((values.get("filename") or [""])[0])
                w = WORKFLOWS.get(workflow_id)
                if not w or w.get("kind") != "video" or w.get("backend") != "runninghub":
                    return self._send(400, b'{"error":"unknown workflow"}')
                temp_path = None
                try:
                    temp_path = self._read_upload_to_temp_file(content_length)
                    filename, ctype, media_type = validate_workflow_upload_file(
                        w, input_key, filename, temp_path)
                except OverflowError as error:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
                    return self._send(413, json.dumps({"error": str(error)}).encode())
                except ValueError as error:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
                    return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
                except Exception:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
                    return self._send(400, b'{"error":"invalid upload body"}')
                try:
                    session_id, cookie_header = self._upload_session(create=True)
                    upload_quota = reserve_upload_attempt(session_id, content_length)
                    if self._upload_quota_rejection(upload_quota):
                        return
                    remote_name = rh_upload_temp_file(temp_path, filename, ctype)
                    upload_token = issue_upload_capability(
                        remote_name, workflow_id, input_key, media_type, filename, session_id)
                    headers = {"Set-Cookie": cookie_header} if cookie_header else None
                    return self._send(200, json.dumps({
                        "uploadToken": upload_token, "filename": filename,
                        "mediaType": ctype, "input_key": input_key,
                    }, ensure_ascii=False).encode(), headers=headers)
                except Exception:
                    return self._send(502, json.dumps({"error": "云端上传失败，请稍后重试"}, ensure_ascii=False).encode())
                finally:
                    if temp_path:
                        temp_path.unlink(missing_ok=True)
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
                return self._send(502, json.dumps({"error": "云端上传失败，请稍后重试"}, ensure_ascii=False).encode())
            headers = {"Set-Cookie": cookie_header} if cookie_header else None
            return self._send(200, json.dumps({
                "uploadToken": upload_token, "filename": filename,
                "mediaType": ctype, "input_key": input_key,
            }, ensure_ascii=False).encode(), headers=headers)
        if path == '/api/video-thumbnail':
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id = self._require_session()
            if not session_id: return
            try:
                body = self._read_json(48000)
                if not isinstance(body, dict): raise ValueError('bad json')
                jid, key = str(body.get('job_id', '')), str(body.get('key', ''))
                with _lock_jobs:
                    job = _jobs.get(jid)
                    if not job or not re.fullmatch(r'[0-9a-f]{12}', jid) or not session_owns_record(session_id, job):
                        return self._send(404)
                    mapping = WORKFLOWS.get(job.get('workflow'), {}).get('rh_media', {}).get(key, {})
                    if job.get('style_id') not in ('video', 'realism') or key not in job.get('media', {}) or mapping.get('type') not in ('video', 'image'):
                        return self._send(400, b'{"error":"invalid video slot"}')
                    if key in job.get('input_thumbnails', {}): return self._send(200, b'{"ok":true}')
                data = normalize_video_thumbnail(body.get('data'))
                digest = hashlib.sha256(key.encode()+data).hexdigest()[:32]
                with _lock_jobs:
                    if key not in job.get('input_thumbnails', {}):
                        folder = JOBS_DIR / jid
                        folder.mkdir(parents=True, exist_ok=True)
                        target = folder / ('input-thumb-'+digest+'.jpg')
                        temporary = target.with_suffix('.tmp')
                        temporary.write_bytes(data)
                        temporary.replace(target)
                        job.setdefault('input_thumbnails', {})[key] = digest
                        save_jobs()
                return self._send(200, b'{"ok":true}')
            except (ValueError, TypeError, OSError):
                return self._send(400, b'{"error":"invalid thumbnail"}')
        if path == '/api/creator-clear':
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id = self._require_session()
            if not session_id: return
            origin = self.headers.get('Origin')
            if (self.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or (origin and (urllib.parse.urlparse(origin).scheme not in ('http', 'https')
                                    or urllib.parse.urlparse(origin).netloc.lower()
                                    != str(self.headers.get('Host') or '').lower()))):
                return self._send(403, b'{"error":"same-origin request required"}')
            try:
                body = self._read_json(8192)
                if not isinstance(body, dict) or set(body) - {'scope', 'ids'}: raise ValueError('请求字段不正确')
                result = clear_creator_ui(session_id, body.get('scope'), body.get('ids'))
            except (ValueError, TypeError, OverflowError) as error:
                return self._send(400, json.dumps({'error': str(error)}, ensure_ascii=False).encode())
            except Exception:
                return self._send(503, json.dumps({'error': '清除未保存，请稍后重试'}, ensure_ascii=False).encode())
            return self._send(200, json.dumps(result, ensure_ascii=False).encode(),
                              headers={'Cache-Control': 'no-store'})
        if path in ('/api/video-clear', '/api/image-edit-clear'):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id = self._require_session()
            if not session_id: return
            origin = self.headers.get('Origin')
            if (self.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or (origin and (urllib.parse.urlparse(origin).scheme not in ('http', 'https')
                                    or urllib.parse.urlparse(origin).netloc.lower()
                                    != str(self.headers.get('Host') or '').lower()))):
                return self._send(403, b'{"error":"same-origin request required"}')
            try:
                body = self._read_json(1024)
                if not isinstance(body, dict): raise ValueError('bad json')
                result = clear_video_ui(session_id, body.get('scope'), 'realism' if path == '/api/image-edit-clear' else 'video')
            except (ValueError, TypeError, OverflowError) as error:
                return self._send(400, json.dumps({'error': str(error)}, ensure_ascii=False).encode())
            except Exception:
                return self._send(503, json.dumps({'error': '清除未保存，请稍后重试'}, ensure_ascii=False).encode())
            return self._send(200, json.dumps(result, ensure_ascii=False).encode(),
                              headers={'Cache-Control': 'no-store'})
        if path in ('/api/video-queue', '/api/image-edit-queue'):
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            session_id = self._require_session()
            if not session_id: return
            try:
                body = self._read_json()
                if not isinstance(body, dict): raise ValueError('bad json')
                edit_video_queue(session_id, body, 'realism' if path == '/api/image-edit-queue' else 'video')
            except LookupError as error:
                return self._send(404, json.dumps({'error': str(error)}, ensure_ascii=False).encode())
            except (ValueError, TypeError) as error:
                return self._send(409, json.dumps({'error': str(error)}, ensure_ascii=False).encode())
            return self._send(200, b'{"ok":true}')
        if path in ("/api/video-generate", "/api/image-edit-generate"):
            task_page = 'realism' if path == '/api/image-edit-generate' else 'video'
            if not self._auth(): return self._send(401, b'{"error":"unauthorized"}')
            try: body = self._read_json()
            except Exception: return self._send(400, b'{"error":"bad json"}')
            session_id = self._require_session()
            if not session_id: return
            try:
                client_request_id = normalize_client_request_id(body.get("client_request_id"))
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}).encode())
            redo = None
            if body.get('redo_job_id'):
                with _lock_jobs:
                    original = _jobs.get(str(body['redo_job_id']))
                    if not original or not session_owns_record(session_id, original):
                        return self._send(404, b'{"error":"job not found"}')
                    if original.get('style_id') != task_page:
                        return self._send(409, json.dumps({'error':'请在原任务所属工作台重做'},ensure_ascii=False).encode())
                    if not video_redoable(original):
                        return self._send(409, json.dumps({'error':'正在运行或核对中的任务暂不能重做'},ensure_ascii=False).encode())
                    redo = dict(original)
                params = dict(redo.get('params') or {})
                w = WORKFLOWS.get(redo.get('workflow'), {})
                seed_control = (w.get('rh_params') or {}).get('seed')
                if seed_control:
                    minimum, maximum = int(seed_control.get('min', 0)), int(seed_control.get('max', 2**31-1))
                    # A new click varies the sample; an uncertain network retry
                    # must reproduce the same effective request for deduplication.
                    digest = hmac.new(SESSION_SECRET, ('video-redo:'+_session_hash(session_id)+':'+redo['id']+':'+client_request_id).encode(), hashlib.sha256).digest()
                    seed = minimum + int.from_bytes(digest[:8], 'big') % (maximum-minimum+1)
                    if seed == params.get('seed') and maximum > minimum:
                        seed = minimum + (seed-minimum+1) % (maximum-minimum+1)
                    params['seed'] = seed
                body = {'workflow':redo.get('workflow'), 'prompt':redo.get('prompt'),
                        'negative_prompt':redo.get('negative_prompt', ''), 'params':params,
                        'selection_snapshot':redo.get('selection_snapshot')}
            wf = body.get("workflow")
            if wf not in WORKFLOWS:
                return self._send(400, b'{"error":"unknown workflow"}')
            w = WORKFLOWS[wf]
            allowed_kinds = ('rh_workflow', 'ai_app') if task_page == 'realism' else ('video',)
            if w.get("kind") not in allowed_kinds or w.get("backend") != "runninghub":
                return self._send(400, b'{"error":"not a video workflow"}')
            prompt = str(body.get("prompt", "")).strip()
            if not prompt and task_page == 'video':
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
            try:
                if redo:
                    provider_media, _ = normalize_rh_workflow_inputs(w, redo.get('provider_media') or {}, schema_params)
                    public_media, _ = normalize_rh_workflow_inputs(w, redo.get('media') or {}, schema_params)
                else:
                    provider_media, public_media = resolve_upload_capabilities(w, submitted_media, session_id, schema_params)
                _, params = normalize_rh_workflow_inputs(w, public_media, schema_params)
            except ValueError as error:
                return self._send(400, json.dumps({"error": str(error)}, ensure_ascii=False).encode())
            prompt = str(next((params[key] for key in ('prompt', 'instruction', 'requirements', 'text', 'positive')
                               if params.get(key) not in (None, '')), prompt)).strip()
            negative_prompt = str(params.get("negative", negative_prompt)).strip()
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
                original_expires = (redo.get('queue_media_expires', redo.get('created', 0) + UPLOAD_CAPABILITY_TTL)
                                    if redo else None)
                if redo and public_media and time.time() >= original_expires:
                    return self._send(410, json.dumps({'error':'原素材已过期，请重新上传素材后生成；原提示词和 LoRA 配置仍可查看'},ensure_ascii=False).encode())
                with _lock_jobs:
                    waiting = _video_waiting()
                    own_waiting = sum(session_owns_record(session_id, j) for j in waiting)
                    next_order = max((j.get('queue_order', j['created']) for j in waiting), default=-1) + 1
                if len(waiting) >= VIDEO_QUEUE_LIMIT or own_waiting >= VIDEO_QUEUE_SESSION_LIMIT:
                    return self._send(429, json.dumps({
                        "error": "等待队列已满，请完成或取消部分任务后再提交",
                    }, ensure_ascii=False).encode())
                if redo:
                    media_expires = original_expires if public_media else time.time()+UPLOAD_CAPABILITY_TTL
                else:
                    with _upload_capabilities_lock:
                        media_expires = min((_upload_capabilities.get(
                            _upload_token_hash(str(submitted_media[key])), {}).get('expires', 0)
                            for key in public_media), default=time.time()+UPLOAD_CAPABILITY_TTL)
                job = {"id": uuid.uuid4().hex[:12], "workflow": wf, "prompt": prompt,
                   "negative_prompt": negative_prompt, "prompt_mode": "manual",
                   "media": public_media, "provider_media": provider_media,
                   "params": params,
                   "width": 0, "height": 0, "batch": max(1, int(params.get('batch') or 1)) if task_page == 'realism' else 1, "hd": 0,
                   "seed": 0, "seed_mode": "random", "loras": {}, "lora_strengths": {},
                   "trigger": None, "translate": False,
                   "status": "queued", "provider_status": "QUEUED", "video_queued": True,
                   "queue_order": next_order, "queue_revision": 0, "queue_media_expires": media_expires,
                   "progress": 0, "progress_pct": 0, "images": [],
                   "prompt_ids": [], "error": None, "elapsed": None,
                   "created": time.time(), "wf_name": w["name"],
                   "submit_started": None, "provider_started": None,
                   "provider_finished": None, "download_started": None,
                   "download_finished": None, "style_id": task_page, "mode": "original",
                   "generation_backend": "cloud",
                   "sequence_mode": "off", "selection_snapshot": upload_bound_snapshot(
                       w, public_media, params, body.get("selection_snapshot"), task_page),
                   "client_request_id": client_request_id,
                   "request_session_hash": session_hash,
                   "effective_request_sha256": request_sha256}
                if redo:
                    job['redo_of'] = redo['id']
                    job['input_thumbnails'] = dict(redo.get('input_thumbnails') or {})
                    job['thumbnail_source_job'] = redo.get('thumbnail_source_job') or redo['id']
                quota_status = register_billable_job(job, session_id)
                if self._billable_quota_rejection(quota_status):
                    return
                return self._send(200, json.dumps({"job_id": job["id"], "status": "queued"}).encode())
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
                    with _lock_jobs:
                        if existing_favorite.get('archive_status') == 'error':
                            previous = dict(existing_favorite)
                            existing_favorite.update(archive_status='saving', archive_error=None)
                            try: save_favorites()
                            except Exception:
                                existing_favorite.clear(); existing_favorite.update(previous)
                                raise
                    return self._send(202 if existing_favorite.get('archive_status') == 'saving' else 200, json.dumps(public_favorite(existing_favorite), ensure_ascii=False).encode())
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
                video_mimes = {'.mp4':'video/mp4','.mov':'video/quicktime','.webm':'video/webm','.avi':'video/x-msvideo','.mkv':'video/x-matroska'}
                if im.get('remote') and suffix in video_mimes:
                    with _lock_jobs:
                        if sum(session_owns_record(session_id,f,'owner_session_hash') for f in _favorites.values()) >= MAX_FAVORITES:
                            return self._send(409, json.dumps({'error':'收藏数量已达上限，请先整理已有收藏'},ensure_ascii=False).encode())
                    fav = {'id':fid,'created':time.time(),'job_id':jid,'image_index':idx,
                           'image_url':f'/api/favorite-image/{fid}', 'original_url':im['url'],
                           'image_path':str(dest), 'favorite_media_type':video_mimes[suffix],
                           'owner_session_hash':_session_hash(session_id), 'archive_status':'saving',
                           'prompt':job.get('prompt',''), 'style_id':job.get('style_id'),
                           'selection_snapshot':job.get('selection_snapshot') or {}}
                    with _lock_jobs:
                        # Never evict an existing favorite for a pending archive.
                        _favorites[fid] = fav
                        try: save_favorites()
                        except Exception:
                            _favorites.pop(fid,None)
                            raise
                    return self._send(202, json.dumps(public_favorite(fav),ensure_ascii=False).encode())
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
                   "api_transport": "images" if generation_backend == "api" else None,
                   "api_dispatch_profile": (
                       "native_images" if generation_backend == "api" else None),
                   "dreamapi_contract_sha256": (
                       DREAMAPI_CONTRACT_SHA256 if generation_backend == "api" else None),
                   "api_action_mode": "direct" if generation_backend == "api" else None,
                   "api_geometry_normalized": None,
                   "api_image_reencoded": None,
                   "api_response_id": None,
                   "api_response_shape": None,
                   "seed_supported": generation_backend != "api",
                   "comfy_prompt_id": None, "transfer_index": 0, "transfer_total": 0,
                   "transfer_started": None, "transfer_finished": None,
                   "selection_snapshot": public_selection_snapshot({
                       **(body.get("selection_snapshot") if isinstance(body.get("selection_snapshot"), dict) else {}),
                       "source_page": "creator", "workflow": "anima02",
                       "generation_backend": generation_backend,
                       **({"api_model": api_model, "api_quality": api_quality,
                           "api_fit": api_fit, "api_ratio": api_ratio}
                          if generation_backend == "api" else {}),
                    })}
            if _membership.enabled or generation_backend in ("cloud", "api"):
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
        print("[panel] no legacy PANEL_TOKEN configured", flush=True)
    load_jobs()
    load_favorites()
    load_upload_capabilities()
    load_upload_usage()
    _membership.reconcile_startup(_jobs)
    def clean_media_libraries():
        while True:
            try: _media_library.cleanup()
            except OSError: pass
            time.sleep(60)
    threading.Thread(target=clean_media_libraries, daemon=True).start()
    threading.Thread(target=video_queue_loop, daemon=True).start()
    threading.Thread(target=video_favorite_archive_loop, daemon=True).start()
    for job in list(_jobs.values()):
        if job.get("status") == "recovering" and job.get("rh_task_id"):
            threading.Thread(target=resume_cloud_job, args=(job,), daemon=True).start()
    threading.Thread(target=backfill_completed_rh_coins, daemon=True).start()
    ok, msg = comfy_ok()
    print(f"[panel] comfy {COMFY_URL}: ok={ok} {msg}", flush=True)
    print(f"[panel] listening {BIND_HOST}:{PORT} data={DATA_DIR}", flush=True)
    BoundedHTTPServer((BIND_HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
