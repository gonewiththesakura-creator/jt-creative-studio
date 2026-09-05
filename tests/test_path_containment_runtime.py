import importlib.util
import http.client
import http.server
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SPEC = importlib.util.spec_from_file_location("path_safety", ROOT / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def test_safe_child_path_accepts_a_real_descendant():
    root = Path(tempfile.mkdtemp()) / "job"
    root.mkdir()
    result = server.safe_child_path(root, "nested", "result.png")
    assert result == (root / "nested" / "result.png").resolve()


def test_safe_child_path_rejects_same_prefix_sibling_escape():
    parent = Path(tempfile.mkdtemp())
    root = parent / "job"
    root.mkdir()
    with pytest.raises(ValueError, match="bad path"):
        server.safe_child_path(root, "..", "job2", "secret.png")


def test_safe_child_path_rejects_absolute_override():
    root = Path(tempfile.mkdtemp()) / "job"
    root.mkdir()
    outside = root.parent / "outside.png"
    with pytest.raises(ValueError, match="bad path"):
        server.safe_child_path(root, outside)


def test_all_served_file_routes_use_safe_child_path():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    assert source.count("safe_child_path(") >= 5
    assert "str(p).startswith" not in source
    assert "str(src).startswith" not in source
    assert "str(fp).startswith" not in source


def test_file_routes_return_explicit_denials_for_sibling_escape():
    parent = Path(tempfile.mkdtemp())
    server.JOBS_DIR = parent / "jobs"
    server.JOBS_DIR.mkdir()
    (server.JOBS_DIR / "job").mkdir()
    (server.JOBS_DIR / "job2").mkdir()
    (server.JOBS_DIR / "job2" / "secret.png").write_bytes(b"SECRET")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        def status(path):
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            code = response.status
            connection.close()
            return code

        assert status("/api/local-preview/job/../job2/secret.png") == 403
        assert status("/api/preview/job/../job2/secret.png") == 403
        assert status("/api/image/job/../job2/secret.png") == 403
        assert status("/static/../server.py") == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
