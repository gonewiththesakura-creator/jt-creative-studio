import importlib.util
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overload_delivery_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_complete_overload_requests_receive_stable_503_without_unbounded_threads():
    old_workers = server.BoundedHTTPServer.max_workers
    server.BoundedHTTPServer.max_workers = 2
    httpd = server.BoundedHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    blockers = []
    try:
        for _ in range(2):
            sock = socket.create_connection(("127.0.0.1", httpd.server_port), timeout=2)
            sock.sendall(b"GET /api/live HTTP/1.1\r\nHost: x\r\nX-Slow: ")
            blockers.append(sock)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and httpd.liveness_snapshot()["active_workers"] < 2:
            time.sleep(0.01)
        assert httpd.liveness_snapshot()["active_workers"] == 2

        results = []
        bodies = []
        for _ in range(200):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{httpd.server_port}/api/live", timeout=1
                )
                results.append(200)
            except urllib.error.HTTPError as error:
                bodies.append(error.read())
                results.append(error.code)
            except OSError as error:
                results.append(type(error).__name__)

        assert results == [503] * 200, {
            value: results.count(value) for value in set(results)
        }
        assert bodies == [b'{"ok":false,"service":"comfy-panel","overloaded":true}'] * 200
        snapshot = httpd.liveness_snapshot()
        assert snapshot["active_rejections"] <= snapshot["max_rejection_workers"]
        assert snapshot["overload_rejections"] >= 200
    finally:
        for sock in blockers:
            try:
                sock.close()
            except OSError:
                pass
        httpd.shutdown()
        httpd.server_close()
        server.BoundedHTTPServer.max_workers = old_workers
