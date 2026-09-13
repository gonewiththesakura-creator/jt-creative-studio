# -*- coding: utf-8 -*-
"""
本机 ComfyUI 守护进程（配合远程面板使用）

职责：
1. 在 127.0.0.1:8198 提供 ComfyUI 控制和受限 DreamAPI 出口
2. 维护 SSH 反向隧道：服务器 8199→本机 8188(ComfyUI)、服务器 8198→本机 8198(控制口)，断开自动重连
3. 面板服务器通过隧道触达本机控制口和本机网络出口

用内嵌 pythonw.exe 运行（无窗口），由「启动面板.bat」拉起。
"""
import os, subprocess, threading, time, json, http.server, urllib.error, urllib.request

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
DREAMAPI_IMAGE_QUALITIES = {
    "gpt-image-2": {"low", "medium", "high", "auto"},
    "gpt-image-2.5-flare": {"low", "medium", "high", "xhigh", "max", "auto"},
    "gpt-image-2.5-sunburst": {"low", "medium", "high", "xhigh", "max", "auto"},
}
DREAMAPI_SIZES = {"1024x1024", "1024x1536", "1536x1024", "864x1536", "1536x864"}

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


def validate_dreamapi_payload(payload):
    """Accept only the image-generation request shape emitted by panel server.py."""
    if not isinstance(payload, dict) or set(payload) != {"model", "input", "stream", "tools"}:
        raise ValueError("invalid DreamAPI request shape")
    if payload.get("model") != "gpt-5.6-sol" or payload.get("stream") is not False:
        raise ValueError("invalid DreamAPI response model or stream mode")
    prompt = payload.get("input")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("invalid DreamAPI prompt")
    tools = payload.get("tools")
    if not isinstance(tools, list) or len(tools) != 1 or not isinstance(tools[0], dict):
        raise ValueError("invalid DreamAPI image tool")
    tool = tools[0]
    if set(tool) != {"type", "action", "model", "size", "quality"}:
        raise ValueError("invalid DreamAPI image tool shape")
    if tool.get("type") != "image_generation" or tool.get("action") != "generate":
        raise ValueError("invalid DreamAPI image action")
    model = tool.get("model")
    quality = tool.get("quality")
    if model not in DREAMAPI_IMAGE_QUALITIES or quality not in DREAMAPI_IMAGE_QUALITIES[model]:
        raise ValueError("unsupported DreamAPI model or quality")
    if tool.get("size") not in DREAMAPI_SIZES:
        raise ValueError("unsupported DreamAPI image size")
    return payload


def dreamapi_proxy_request(payload, authorization):
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
        response = _dreamapi_urlopen(request, timeout=DREAMAPI_TIMEOUT)
    except urllib.error.HTTPError as error:
        with error:
            body = error.read(8193)
        if len(body) > 8192:
            body = b'{"error":"DreamAPI error response is too large"}'
        return error.code, body, "application/json"
    with response:
        chunks, total = [], 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > DREAMAPI_RESPONSE_LIMIT:
                raise RuntimeError("DreamAPI response is too large")
            chunks.append(chunk)
        content_type = response.headers.get_content_type()
        return response.status, b"".join(chunks), content_type

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
            self._send({"comfy_running": comfy_running()})
        else:
            self._send({"error": "not found"}, 404)
    def do_POST(self):
        if self.path == "/start":
            self._send({"result": start_comfy()})
        elif self.path == "/dreamapi/responses":
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer ") or not (16 <= len(authorization) <= 8192):
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
    main()
