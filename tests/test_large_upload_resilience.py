import importlib.util
import socket
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
spec = importlib.util.spec_from_file_location("large_upload_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def open_slow_upload(port):
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.sendall(
        b"POST /api/generate HTTP/1.1\r\n"
        b"Host: local\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {server.LARGE_REQUEST_THRESHOLD}\r\n".encode()
        + b"Connection: close\r\n\r\n"
    )
    return client


def test_large_upload_slots_reject_third_without_blocking_normal_get():
    httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    slow = []
    try:
        for _ in range(server.MAX_LARGE_REQUESTS):
            slow.append(open_slow_upload(httpd.server_port))
        time.sleep(0.2)

        third = socket.create_connection(("127.0.0.1", httpd.server_port), timeout=2)
        third.sendall(
            b"POST /api/generate HTTP/1.1\r\nHost: local\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {server.LARGE_REQUEST_THRESHOLD}\r\n".encode()
            + b"Connection: close\r\n\r\n"
        )
        started = time.perf_counter()
        response = third.recv(4096)
        elapsed = time.perf_counter() - started
        third.close()
        assert b" 503 " in response
        assert b"Retry-After: 10" in response
        assert elapsed < 1

        started = time.perf_counter()
        with urllib.request.urlopen(
            f"http://127.0.0.1:{httpd.server_port}/api/live", timeout=2
        ) as response:
            assert response.status == 200
        assert time.perf_counter() - started < 1
    finally:
        for client in slow:
            client.close()
        httpd.shutdown()
        httpd.server_close()
