# -*- coding: utf-8 -*-
"""
本机 ComfyUI 守护进程（配合远程面板使用）

职责：
1. 在 127.0.0.1:8198 提供控制服务：GET /status 检测 ComfyUI，POST /start 一键启动 ComfyUI
2. 维护 SSH 反向隧道：服务器 8199→本机 8188(ComfyUI)、服务器 8198→本机 8198(控制口)，断开自动重连
3. 面板服务器通过隧道触达本机控制口，实现"远程一键启动 ComfyUI"

用内嵌 pythonw.exe 运行（无窗口），由「启动面板.bat」拉起。
"""
import subprocess, threading, time, json, http.server, urllib.request

COMFY_PY   = r"D:/ComfyUI_Mie/python_embeded/python.exe"
COMFY_MAIN = r"D:/ComfyUI_Mie/ComfyUI/main.py"
COMFY_CWD  = r"D:/ComfyUI_Mie"
SSH_EXE    = r"C:\Windows\System32\OpenSSH\ssh.exe"
SSH_KEY    = r"D:\LAN-Share\lora\_work\comfy_panel\tools\id_ed25519"
SERVER     = "admin@8.210.125.65"
CONTROL_PORT = 8198

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

def comfy_running():
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2)
        return True
    except Exception:
        return False

def start_comfy():
    if comfy_running():
        return "already_running"
    try:
        subprocess.Popen(
            [COMFY_PY, "-s", COMFY_MAIN, "--windows-standalone-build", "--fast-disk"],
            cwd=COMFY_CWD,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
        return "starting"
    except Exception as e:
        return "error: " + str(e)

def tunnel_loop():
    while True:
        try:
            proc = subprocess.Popen(
                [SSH_EXE, "-i", SSH_KEY, "-N",
                 "-R", "8199:127.0.0.1:8188",
                 "-R", f"{CONTROL_PORT}:127.0.0.1:{CONTROL_PORT}",
                 "-o", "ServerAliveInterval=30",
                 "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes",
                 "-o", "StrictHostKeyChecking=accept-new",
                 SERVER],
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
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
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
