import importlib.util
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("absolute_deadline_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def start_dripper(port, prefix):
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.sendall(prefix)
    stopped = threading.Event()

    def drip():
        while not stopped.wait(0.08):
            try:
                sock.sendall(b"x")
            except OSError:
                return

    thread = threading.Thread(target=drip, daemon=True)
    thread.start()
    return sock, stopped, thread


def wait_for_workers(httpd, count, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if httpd.liveness_snapshot()["active_workers"] == count:
            return
        time.sleep(0.01)
    raise AssertionError(httpd.liveness_snapshot())


def wait_for_live(port, timeout=3):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/live", timeout=0.5
            ) as response:
                status = response.status
                response.read()
            if status == 200:
                return status
        except (urllib.error.HTTPError, OSError) as error:
            last = error
        time.sleep(0.02)
    raise AssertionError(f"server did not recover: {last!r}")


def wait_for_workers_at_most(httpd, count, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if httpd.liveness_snapshot()["active_workers"] <= count:
            return
        time.sleep(0.01)
    raise AssertionError(httpd.liveness_snapshot())


def close_clients(clients):
    for sock, stopped, thread in clients:
        stopped.set()
        try:
            sock.close()
        except OSError:
            pass
        thread.join(timeout=1)


def test_absolute_header_deadline_releases_workers_despite_continuous_bytes():
    old_workers = server.BoundedHTTPServer.max_workers
    old_timeout = server.REQUEST_HEADER_TIMEOUT
    server.BoundedHTTPServer.max_workers = 2
    server.REQUEST_HEADER_TIMEOUT = 1.5
    httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    clients = []
    try:
        for _ in range(2):
            clients.append(
                start_dripper(
                    httpd.server_port,
                    b"GET /api/live HTTP/1.1\r\nHost: x\r\nX-Drip: ",
                )
            )
        wait_for_workers(httpd, 2)
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{httpd.server_port}/api/live", timeout=1
            )
            initial = 200
        except urllib.error.HTTPError as error:
            initial = error.code
        assert initial == 503
        assert wait_for_live(httpd.server_port) == 200
        wait_for_workers_at_most(httpd, 0)
    finally:
        close_clients(clients)
        httpd.shutdown()
        httpd.server_close()
        server.BoundedHTTPServer.max_workers = old_workers
        server.REQUEST_HEADER_TIMEOUT = old_timeout


def test_absolute_body_deadline_releases_small_post_drippers():
    old_workers = server.BoundedHTTPServer.max_workers
    old_base_timeout = server.REQUEST_BODY_BASE_TIMEOUT
    old_max_timeout = server.REQUEST_BODY_MAX_TIMEOUT
    server.BoundedHTTPServer.max_workers = 2
    server.REQUEST_BODY_BASE_TIMEOUT = 1.5
    server.REQUEST_BODY_MAX_TIMEOUT = 1.5
    httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    clients = []
    try:
        header = (
            b"POST /api/generate HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\nContent-Length: 1000\r\n\r\n{"
        )
        for _ in range(2):
            clients.append(start_dripper(httpd.server_port, header))
        wait_for_workers(httpd, 2)
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{httpd.server_port}/api/live", timeout=1
            )
            initial = 200
        except urllib.error.HTTPError as error:
            initial = error.code
        assert initial == 503
        assert wait_for_live(httpd.server_port) == 200
        wait_for_workers_at_most(httpd, 0)
    finally:
        close_clients(clients)
        httpd.shutdown()
        httpd.server_close()
        server.BoundedHTTPServer.max_workers = old_workers
        server.REQUEST_BODY_BASE_TIMEOUT = old_base_timeout
        server.REQUEST_BODY_MAX_TIMEOUT = old_max_timeout
