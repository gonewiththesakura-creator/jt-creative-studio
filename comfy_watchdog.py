# -*- coding: utf-8 -*-
"""
本机 ComfyUI 守护进程（配合远程面板使用）

职责：
1. 在 127.0.0.1:8198 提供 ComfyUI 控制和受限 DreamAPI 出口
2. 维护 SSH 反向隧道：服务器 8199→本机 8188(ComfyUI)、服务器 8198→本机 8198(控制口)，断开自动重连
3. 面板服务器通过隧道触达本机控制口和本机网络出口

用内嵌 pythonw.exe 运行（无窗口），由「启动面板.bat」拉起。
"""
import hashlib, json, math, os, socket, subprocess, sys, threading, time, http.server, urllib.error, urllib.request

COMFY_PY   = r"D:/ComfyUI_Mie/python_embeded/python.exe"
COMFY_MAIN = r"D:/ComfyUI_Mie/ComfyUI/main.py"
COMFY_CWD  = r"D:/ComfyUI_Mie"
SSH_EXE    = os.environ.get("COMFY_PANEL_SSH_EXE", r"C:\Windows\System32\OpenSSH\ssh.exe")
SSH_KEY    = os.environ.get("COMFY_PANEL_SSH_KEY", r"D:\LAN-Share\lora\_work\comfy_panel\tools\id_ed25519")
SERVER     = os.environ.get("COMFY_PANEL_SSH_SERVER", "admin@8.210.125.65")
SSH_PORT   = os.environ.get("COMFY_PANEL_SSH_PORT", "22")
CONTROL_PORT = 8198
DREAMAPI_RESPONSES_URL = "https://dreamapi.club/responses"
DREAMAPI_REQUEST_LIMIT = 64 * 1024
DREAMAPI_RESPONSE_LIMIT = 96 * 1024 * 1024
DREAMAPI_TIMEOUT = 600
DREAMAPI_WORKER_START_GRACE = 2
DREAMAPI_WORKER_HEADER_LIMIT = 4096
DREAMAPI_WORKER_INPUT_LIMIT = DREAMAPI_REQUEST_LIMIT + 16 * 1024
DREAMAPI_FENCE_RECORD_LIMIT = 4096
DREAMAPI_FENCE_TTL = DREAMAPI_TIMEOUT + DREAMAPI_WORKER_START_GRACE + 60
DREAMAPI_FENCE_PATH = os.environ.get(
    "COMFY_PANEL_DREAMAPI_FENCE",
    os.path.join(
        os.environ.get("LOCALAPPDATA", COMFY_CWD),
        "JTComfyPanel", "dreamapi-inflight.json",
    ),
)
DREAMAPI_TEXT_MODEL = "gpt-5.6-luna"
DREAMAPI_STANDARD_DISPATCH_INSTRUCTIONS = (
    "You are an image generation dispatcher. Call the provided image_generation "
    "tool exactly once. Do not return or rewrite a prompt. Return no text."
)
DREAMAPI_STRICT_DISPATCH_INSTRUCTIONS = (
    "You are an image generation dispatcher. You must call the provided image_generation "
    "tool exactly once. Do not return or rewrite a prompt. Return no text."
)
DREAMAPI_DISPATCH_INSTRUCTIONS_BY_MODEL = {
    "gpt-image-2": DREAMAPI_STANDARD_DISPATCH_INSTRUCTIONS,
    "gpt-image-2.5-flare": DREAMAPI_STANDARD_DISPATCH_INSTRUCTIONS,
    "gpt-image-2.5-sunburst": DREAMAPI_STRICT_DISPATCH_INSTRUCTIONS,
}
DREAMAPI_IMAGE_QUALITIES = {
    "gpt-image-2": {"low", "medium", "high", "auto"},
    "gpt-image-2.5-flare": {"low", "medium", "high", "xhigh", "max", "auto"},
    "gpt-image-2.5-sunburst": {"low", "medium", "high", "xhigh", "max", "auto"},
}
DREAMAPI_IMAGE_ACTION_MODELS = {
    "gpt-image-2.5-flare",
    "gpt-image-2.5-sunburst",
}
DREAMAPI_SIZES = {"1024x1024", "1024x1536", "1536x1024", "864x1536", "1536x864"}


def _dreamapi_contract_document():
    """Return the public request-shape contract shared with the panel server."""
    models = {}
    for model in sorted(DREAMAPI_IMAGE_QUALITIES):
        models[model] = {
            "action": "generate" if model in DREAMAPI_IMAGE_ACTION_MODELS else "omitted",
            "qualities": sorted(DREAMAPI_IMAGE_QUALITIES[model]),
        }
    return {
        "contract_version": 2,
        "dispatcher": {
            "instructions_by_image_model": {
                model: DREAMAPI_DISPATCH_INSTRUCTIONS_BY_MODEL[model]
                for model in sorted(DREAMAPI_IMAGE_QUALITIES)
            },
            "model": DREAMAPI_TEXT_MODEL,
            "stream": False,
        },
        "image_tool": {
            "models": models,
            "sizes": sorted(DREAMAPI_SIZES),
            "type": "image_generation",
        },
        "request_keys": ["input", "instructions", "model", "stream", "tools"],
        "runtime_safety": {
            "kill_worker_on_parent_exit": True,
            "persistent_uncertainty_fence": True,
        },
        "tool_count": 1,
    }


def _dreamapi_contract_sha256():
    canonical = json.dumps(
        _dreamapi_contract_document(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


DREAMAPI_CONTRACT_SHA256 = _dreamapi_contract_sha256()

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_comfy_start_lock = threading.Lock()
_comfy_start_process = None
_dreamapi_lock = threading.Lock()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


_dreamapi_opener = urllib.request.build_opener(_NoRedirectHandler())


def _dreamapi_urlopen(request, timeout):
    return _dreamapi_opener.open(request, timeout=timeout)


def _dreamapi_timeout_error():
    return TimeoutError(f"DreamAPI upstream hard timeout after {DREAMAPI_TIMEOUT}s")


def _dreamapi_remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _dreamapi_timeout_error()
    return remaining


def _dreamapi_response_socket(response):
    """Find urllib's underlying socket without depending on one wrapper shape."""
    pending, seen = [response], set()
    while pending:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if callable(getattr(current, "settimeout", None)):
            return current
        for name in ("fp", "raw", "_sock"):
            try:
                nested = getattr(current, name, None)
            except Exception:
                nested = None
            if nested is not None:
                pending.append(nested)
    return None


def _dreamapi_read(response, size, deadline):
    remaining = _dreamapi_remaining(deadline)
    response_socket = _dreamapi_response_socket(response)
    if response_socket is not None:
        try:
            response_socket.settimeout(max(0.001, remaining))
        except (OSError, TypeError, ValueError):
            # The outer hard-deadline worker remains authoritative for adapters
            # whose socket is already closing or does not accept float timeouts.
            pass

    # HTTPResponse.read1 performs at most one underlying buffered read. This
    # lets a continuously dripping peer return control so the monotonic budget
    # is checked again instead of keeping read(size) alive indefinitely.
    reader = getattr(response, "read1", None)
    if not callable(reader):
        reader = getattr(getattr(response, "fp", None), "read1", None)
    if not callable(reader):
        reader = response.read
    chunk = reader(size)
    _dreamapi_remaining(deadline)
    return chunk


def _dreamapi_read_at_most(response, limit, deadline):
    chunks, total = [], 0
    while total < limit:
        chunk = _dreamapi_read(response, min(65536, limit - total), deadline)
        if not chunk:
            break
        total += len(chunk)
        chunks.append(chunk)
    return b"".join(chunks)


def _dreamapi_read_limited(response, max_bytes, deadline):
    body = _dreamapi_read_at_most(response, max_bytes + 1, deadline)
    if len(body) > max_bytes:
        raise RuntimeError("DreamAPI response is too large")
    return body


def _dreamapi_abort_response(response):
    if response is None:
        return
    response_socket = _dreamapi_response_socket(response)
    if response_socket is not None:
        try:
            response_socket.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        try:
            response_socket.close()
        except (OSError, AttributeError):
            pass
    try:
        response.close()
    except (OSError, AttributeError):
        pass


def validate_dreamapi_payload(payload):
    """Accept only the image-generation request shape emitted by panel server.py."""
    if not isinstance(payload, dict) or set(payload) != {
            "model", "instructions", "input", "stream", "tools"}:
        raise ValueError("invalid DreamAPI request shape")
    if payload.get("model") != DREAMAPI_TEXT_MODEL or payload.get("stream") is not False:
        raise ValueError("invalid DreamAPI dispatcher model or stream mode")
    prompt = payload.get("input")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("invalid DreamAPI prompt")
    tools = payload.get("tools")
    if not isinstance(tools, list) or len(tools) != 1 or not isinstance(tools[0], dict):
        raise ValueError("invalid DreamAPI image tool")
    tool = tools[0]
    model = tool.get("model")
    expected_instructions = DREAMAPI_DISPATCH_INSTRUCTIONS_BY_MODEL.get(model)
    if expected_instructions is None or payload.get("instructions") != expected_instructions:
        raise ValueError("invalid DreamAPI dispatch instructions")
    expected_keys = {"type", "model", "size", "quality"}
    if model in DREAMAPI_IMAGE_ACTION_MODELS:
        expected_keys.add("action")
    if set(tool) != expected_keys:
        raise ValueError("invalid DreamAPI image tool shape")
    if tool.get("type") != "image_generation":
        raise ValueError("invalid DreamAPI image tool type")
    if model in DREAMAPI_IMAGE_ACTION_MODELS and tool.get("action") != "generate":
        raise ValueError("invalid DreamAPI image action")
    quality = tool.get("quality")
    if model not in DREAMAPI_IMAGE_QUALITIES or quality not in DREAMAPI_IMAGE_QUALITIES[model]:
        raise ValueError("unsupported DreamAPI model or quality")
    if tool.get("size") not in DREAMAPI_SIZES:
        raise ValueError("unsupported DreamAPI image size")
    return payload


def _dreamapi_proxy_request_until(payload, authorization, deadline, state):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        DREAMAPI_RESPONSES_URL,
        data=data,
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        response = _dreamapi_urlopen(request, timeout=_dreamapi_remaining(deadline))
    except urllib.error.HTTPError as error:
        state["response"] = error
        with error:
            body = _dreamapi_read_at_most(error, 8193, deadline)
        if len(body) > 8192:
            body = b'{"error":"DreamAPI error response is too large"}'
        return error.code, body, "application/json"
    state["response"] = response
    with response:
        body = _dreamapi_read_limited(response, DREAMAPI_RESPONSE_LIMIT, deadline)
        content_type = response.headers.get_content_type()
        return response.status, body, content_type


def _validate_dreamapi_authorization(authorization):
    if (
        not isinstance(authorization, str)
        or not authorization.startswith("Bearer ")
        or not (16 <= len(authorization) <= 8192)
        or "\r" in authorization
        or "\n" in authorization
    ):
        raise ValueError("DreamAPI authorization required")
    return authorization


def _validate_dreamapi_content_type(content_type):
    token_chars = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$&^_.+-"
    )
    if not isinstance(content_type, str) or len(content_type) > 255:
        raise RuntimeError("invalid DreamAPI worker content type")
    parts = content_type.split("/")
    if len(parts) != 2 or not all(part and set(part) <= token_chars for part in parts):
        raise RuntimeError("invalid DreamAPI worker content type")
    return content_type


def _dreamapi_worker_input(payload, authorization):
    document = {
        "authorization": _validate_dreamapi_authorization(authorization),
        "payload": validate_dreamapi_payload(payload),
    }
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > DREAMAPI_WORKER_INPUT_LIMIT:
        raise ValueError("DreamAPI worker input is too large")
    return raw


def _dreamapi_worker_header(status, body, content_type):
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise RuntimeError("invalid DreamAPI worker status")
    if not isinstance(body, bytes) or len(body) > DREAMAPI_RESPONSE_LIMIT:
        raise RuntimeError("invalid DreamAPI worker body")
    document = {
        "body_length": len(body),
        "content_type": _validate_dreamapi_content_type(content_type),
        "status": status,
    }
    header = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")
    if len(header) > DREAMAPI_WORKER_HEADER_LIMIT:
        raise RuntimeError("DreamAPI worker header is too large")
    return header + b"\n"


def _decode_dreamapi_worker_output(raw):
    if not isinstance(raw, bytes):
        raise RuntimeError("invalid DreamAPI worker output")
    if len(raw) > DREAMAPI_WORKER_HEADER_LIMIT + 1 + DREAMAPI_RESPONSE_LIMIT:
        raise RuntimeError("DreamAPI worker output is too large")
    header_end = raw.find(b"\n", 0, DREAMAPI_WORKER_HEADER_LIMIT + 1)
    if header_end < 0:
        raise RuntimeError("invalid DreamAPI worker output")
    try:
        header = json.loads(raw[:header_end].decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("invalid DreamAPI worker output") from error
    if not isinstance(header, dict) or set(header) != {
            "body_length", "content_type", "status"}:
        raise RuntimeError("invalid DreamAPI worker output")
    status = header["status"]
    body_length = header["body_length"]
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise RuntimeError("invalid DreamAPI worker status")
    if (
        isinstance(body_length, bool)
        or not isinstance(body_length, int)
        or not 0 <= body_length <= DREAMAPI_RESPONSE_LIMIT
    ):
        raise RuntimeError("invalid DreamAPI worker body length")
    content_type = _validate_dreamapi_content_type(header["content_type"])
    body = raw[header_end + 1:]
    if len(body) != body_length:
        raise RuntimeError("invalid DreamAPI worker body length")
    return status, body, content_type


def _dreamapi_worker_main(input_stream=None, output_stream=None):
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    raw = input_stream.read(DREAMAPI_WORKER_INPUT_LIMIT + 1)
    if len(raw) > DREAMAPI_WORKER_INPUT_LIMIT:
        raise ValueError("DreamAPI worker input is too large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid DreamAPI worker input") from error
    if not isinstance(document, dict) or set(document) != {"authorization", "payload"}:
        raise ValueError("invalid DreamAPI worker input")
    authorization = _validate_dreamapi_authorization(document["authorization"])
    payload = validate_dreamapi_payload(document["payload"])
    deadline = time.monotonic() + DREAMAPI_TIMEOUT
    status, body, content_type = _dreamapi_proxy_request_until(
        payload, authorization, deadline, {},
    )
    output_stream.write(_dreamapi_worker_header(status, body, content_type))
    output_stream.write(body)
    output_stream.flush()
    return 0


class DreamApiUncertaintyFenceActive(RuntimeError):
    pass


def _lock_dreamapi_fence(stream, blocking=False):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(stream.fileno(), mode, 1)
    else:
        import fcntl
        mode = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(stream.fileno(), mode)


def _unlock_dreamapi_fence(stream):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _open_dreamapi_fence():
    parent = os.path.dirname(os.path.abspath(DREAMAPI_FENCE_PATH))
    os.makedirs(parent, exist_ok=True)
    descriptor = os.open(DREAMAPI_FENCE_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    if os.fstat(descriptor).st_size == 0:
        stream.write(b"{}")
        os.fsync(descriptor)
    stream.seek(0)
    return stream


def _read_dreamapi_fence(stream):
    stream.seek(0)
    raw = stream.read(DREAMAPI_FENCE_RECORD_LIMIT + 1)
    if len(raw) > DREAMAPI_FENCE_RECORD_LIMIT:
        return {"expires_at": os.fstat(stream.fileno()).st_mtime + DREAMAPI_FENCE_TTL}
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"expires_at": os.fstat(stream.fileno()).st_mtime + DREAMAPI_FENCE_TTL}
    if not isinstance(record, dict):
        return {"expires_at": os.fstat(stream.fileno()).st_mtime + DREAMAPI_FENCE_TTL}
    return record


def _dreamapi_fence_expiry(stream, record):
    fallback = os.fstat(stream.fileno()).st_mtime + DREAMAPI_FENCE_TTL
    if record == {}:
        return 0.0
    if not isinstance(record, dict) or set(record) != {
            "contract_sha256", "expires_at", "owner_pid", "started_at"}:
        return fallback
    contract_sha256 = record["contract_sha256"]
    expires_at = record["expires_at"]
    owner_pid = record["owner_pid"]
    started_at = record["started_at"]
    if (not isinstance(contract_sha256, str) or len(contract_sha256) != 64
            or any(character not in "0123456789abcdef" for character in contract_sha256)
            or isinstance(owner_pid, bool) or not isinstance(owner_pid, int) or owner_pid <= 0
            or isinstance(expires_at, bool) or not isinstance(expires_at, (int, float))
            or isinstance(started_at, bool) or not isinstance(started_at, (int, float))
            or not math.isfinite(expires_at) or not math.isfinite(started_at)
            or expires_at < started_at
            or expires_at > started_at + DREAMAPI_FENCE_TTL + 1):
        return fallback
    return float(expires_at)


def _write_dreamapi_fence(stream, record):
    raw = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("ascii")
    if len(raw) > DREAMAPI_FENCE_RECORD_LIMIT:
        raise RuntimeError("DreamAPI uncertainty fence record is too large")
    stream.seek(0)
    stream.write(raw)
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def _acquire_dreamapi_fence(now=None):
    now = time.time() if now is None else float(now)
    stream = _open_dreamapi_fence()
    try:
        _lock_dreamapi_fence(stream)
    except (BlockingIOError, OSError) as error:
        stream.close()
        raise DreamApiUncertaintyFenceActive(
            "DreamAPI generation is already in progress or its outcome is uncertain"
        ) from error
    try:
        record = _read_dreamapi_fence(stream)
        expires_at = _dreamapi_fence_expiry(stream, record)
        if expires_at > now:
            raise DreamApiUncertaintyFenceActive(
                "DreamAPI generation is already in progress or its outcome is uncertain"
            )
        _write_dreamapi_fence(stream, {
            "contract_sha256": DREAMAPI_CONTRACT_SHA256,
            "expires_at": now + DREAMAPI_FENCE_TTL,
            "owner_pid": os.getpid(),
            "started_at": now,
        })
        return stream
    except BaseException:
        _unlock_dreamapi_fence(stream)
        stream.close()
        raise


def _release_dreamapi_fence(stream, definitive):
    try:
        if definitive:
            _write_dreamapi_fence(stream, {})
    finally:
        _unlock_dreamapi_fence(stream)
        stream.close()


def dreamapi_uncertainty_fence_active(now=None):
    now = time.time() if now is None else float(now)
    try:
        stream = _open_dreamapi_fence()
    except OSError:
        return True
    try:
        try:
            _lock_dreamapi_fence(stream)
        except (BlockingIOError, OSError):
            return True
        try:
            record = _read_dreamapi_fence(stream)
            expires_at = _dreamapi_fence_expiry(stream, record)
            return expires_at > now
        finally:
            _unlock_dreamapi_fence(stream)
    finally:
        stream.close()


def _terminate_dreamapi_worker(process):
    """Do not return until the paid-request worker is confirmed stopped."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        pass
    # A blocking wait is deliberate: releasing the single-flight lock while a
    # paid upstream request may still be alive would permit a duplicate charge.
    process.wait()


def _dreamapi_worker_executable():
    executable = sys.executable
    if os.name == "nt" and os.path.basename(executable).lower() == "pythonw.exe":
        console_executable = os.path.join(os.path.dirname(executable), "python.exe")
        if os.path.isfile(console_executable):
            return console_executable
    return executable


def _assign_windows_kill_on_close_job(process):
    """Tie a paid worker to this watchdog's lifetime on Windows."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        return job
    except BaseException:
        kernel32.CloseHandle(job)
        raise


def _close_windows_worker_job(process):
    job = getattr(process, "_dreamapi_job_handle", None)
    if not job:
        return
    process._dreamapi_job_handle = None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(job):
        error = ctypes.WinError(ctypes.get_last_error())
        _terminate_dreamapi_worker(process)
        raise error
    if process.poll() is None:
        process.wait()


def _dreamapi_worker_process():
    process = subprocess.Popen(
        [_dreamapi_worker_executable(), os.path.abspath(__file__), "--dreamapi-worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW if os.name == "nt" else 0,
        close_fds=True,
    )
    try:
        process._dreamapi_job_handle = _assign_windows_kill_on_close_job(process)
    except BaseException:
        _terminate_dreamapi_worker(process)
        raise
    return process


def dreamapi_proxy_request(payload, authorization):
    """Run exactly one paid upstream request inside a killable child process."""
    worker_input = _dreamapi_worker_input(payload, authorization)
    fence = _acquire_dreamapi_fence()
    process = None
    request_started = False
    definitive = False
    try:
        process = _dreamapi_worker_process()
        try:
            request_started = True
            raw, _ = process.communicate(
                input=worker_input,
                timeout=DREAMAPI_TIMEOUT + DREAMAPI_WORKER_START_GRACE,
            )
        except subprocess.TimeoutExpired as error:
            _terminate_dreamapi_worker(process)
            raise _dreamapi_timeout_error() from error
        except BaseException:
            _terminate_dreamapi_worker(process)
            raise
        if process.poll() is None:
            _terminate_dreamapi_worker(process)
            raise RuntimeError("DreamAPI worker did not exit")
        if process.returncode != 0:
            raise RuntimeError("DreamAPI worker failed")
        decoded = _decode_dreamapi_worker_output(raw)
        definitive = True
        return decoded
    finally:
        if process is not None:
            _close_windows_worker_job(process)
        _release_dreamapi_fence(fence, definitive or not request_started)

def comfy_running():
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2)
        return True
    except Exception:
        return False

def start_comfy():
    global _comfy_start_process
    with _comfy_start_lock:
        if comfy_running():
            _comfy_start_process = None
            return "already_running"
        if _comfy_start_process is not None and _comfy_start_process.poll() is None:
            return "starting"
        try:
            _comfy_start_process = subprocess.Popen(
                [COMFY_PY, "-s", COMFY_MAIN, "--windows-standalone-build", "--fast-disk"],
                cwd=COMFY_CWD,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
            return "starting"
        except Exception as e:
            _comfy_start_process = None
            return "error: " + str(e)

def tunnel_command():
    return [SSH_EXE, "-i", SSH_KEY, "-p", SSH_PORT, "-N",
            "-R", "8199:127.0.0.1:8188",
            "-R", f"{CONTROL_PORT}:127.0.0.1:{CONTROL_PORT}",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            SERVER]

def tunnel_loop():
    while True:
        try:
            proc = subprocess.Popen(
                tunnel_command(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
            proc.wait()
        except Exception:
            pass
        time.sleep(5)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, code)
    def _send_bytes(self, body, code=200, content_type="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/status":
            self._send({
                "comfy_running": comfy_running(),
                "dreamapi_contract_sha256": DREAMAPI_CONTRACT_SHA256,
                "dreamapi_uncertainty_fence": dreamapi_uncertainty_fence_active(),
            })
        else:
            self._send({"error": "not found"}, 404)
    def do_POST(self):
        if self.path == "/start":
            self._send({"result": start_comfy()})
        elif self.path == "/dreamapi/responses":
            authorization = self.headers.get("Authorization", "")
            try:
                _validate_dreamapi_authorization(authorization)
            except ValueError:
                return self._send({"error": "DreamAPI authorization required"}, 401)
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if not 1 <= length <= DREAMAPI_REQUEST_LIMIT:
                    raise ValueError("DreamAPI request body is too large")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("incomplete DreamAPI request body")
                payload = validate_dreamapi_payload(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                return self._send({"error": str(error)}, 400)
            if not _dreamapi_lock.acquire(blocking=False):
                return self._send(
                    {"error": "DreamAPI generation already in progress"}, 429,
                )
            try:
                status, body, content_type = dreamapi_proxy_request(payload, authorization)
                self._send_bytes(body, status, content_type)
            except DreamApiUncertaintyFenceActive:
                self._send({
                    "error": "DreamAPI prior request outcome is still uncertain",
                }, 429)
            except Exception:
                self._send({"error": "DreamAPI workstation egress failed"}, 502)
            finally:
                _dreamapi_lock.release()
        else:
            self._send({"error": "not found"}, 404)

def main():
    # 先 bind 控制口，确保隧道转发 8198 不会失败
    server = http.server.ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=tunnel_loop, daemon=True).start()
    threading.Event().wait()

if __name__ == "__main__":
    if sys.argv[1:] == ["--contract-sha256"]:
        print(DREAMAPI_CONTRACT_SHA256)
    elif sys.argv[1:] == ["--dreamapi-worker"]:
        try:
            raise SystemExit(_dreamapi_worker_main())
        except Exception:
            raise SystemExit(1)
    elif sys.argv[1:]:
        raise SystemExit("usage: comfy_watchdog.py [--contract-sha256]")
    else:
        main()
