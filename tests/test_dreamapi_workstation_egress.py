import importlib.util
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_dreamapi_uncertainty_fence(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "COMFY_PANEL_DREAMAPI_FENCE", str(tmp_path / "dreamapi-inflight.json"),
    )


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_payload(image_model="gpt-image-2", quality="low"):
    return {
        "model": image_model,
        "prompt": "A blue sphere on a clean studio background.",
        "size": "864x1536",
        "quality": quality,
        "n": 1,
        "output_format": "png",
    }


def test_watchdog_accepts_only_the_panels_bounded_image_request_contract():
    watchdog = load_module("watchdog_dreamapi_contract", ROOT / "comfy_watchdog.py")
    assert watchdog.validate_dreamapi_payload(valid_payload()) == valid_payload()
    assert watchdog.validate_dreamapi_payload(
        valid_payload("gpt-image-2.5-flare")
    ) == valid_payload("gpt-image-2.5-flare")
    assert watchdog.validate_dreamapi_payload(
        valid_payload("gpt-image-2.5-sunburst")
    ) == valid_payload("gpt-image-2.5-sunburst")
    assert watchdog.validate_dreamapi_payload(
        valid_payload("gpt-image-2.5-flare", "max")
    ) == valid_payload("gpt-image-2.5-flare", "max")

    mutations = [
        {**valid_payload(), "model": "other"},
        {**valid_payload(), "model": "gpt-5.6-luna"},
        {**valid_payload(), "stream": True},
        {**valid_payload(), "tools": [{"type": "image_generation"}]},
        {**valid_payload(), "prompt": "x" * 2001},
        {**valid_payload(), "unexpected": True},
        {**valid_payload(), "n": 2},
        {**valid_payload(), "size": "2048x2048"},
        {**valid_payload(), "quality": "max"},
        {**valid_payload(), "output_format": "jpeg"},
    ]
    for payload in mutations:
        with pytest.raises(ValueError):
            watchdog.validate_dreamapi_payload(payload)


def test_watchdog_forwards_authorization_only_to_fixed_https_dreamapi(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_forward", ROOT / "comfy_watchdog.py")
    captured = {}

    class Response:
        status = 200
        headers = types.SimpleNamespace(get_content_type=lambda: "application/json")

        def read(self, size):
            if captured.get("read"):
                return b""
            captured["read"] = True
            return b'{"data":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data)
        return Response()

    worker_input = watchdog._dreamapi_worker_input(
        valid_payload(), "Bearer local-test-token",
    )
    worker_output = io.BytesIO()
    monkeypatch.setattr(watchdog, "_dreamapi_urlopen", fake_urlopen)
    assert watchdog._dreamapi_worker_main(io.BytesIO(worker_input), worker_output) == 0
    status, body, content_type = watchdog._decode_dreamapi_worker_output(
        worker_output.getvalue(),
    )
    assert (status, body, content_type) == (200, b'{"data":[]}', "application/json")
    assert captured["url"] == "https://dreamapi.club/v1/images/generations"
    assert captured["authorization"] == "Bearer local-test-token"
    assert 0 < captured["timeout"] <= watchdog.DREAMAPI_TIMEOUT
    assert captured["payload"] == valid_payload()
    assert captured["read"] is True


def test_watchdog_parent_sends_secret_over_stdin_not_process_arguments(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_worker_boundary", ROOT / "comfy_watchdog.py")
    captured = {}
    body = b'{"data":[]}'

    class Process:
        returncode = 0

        def communicate(self, input, timeout):
            captured["input"] = input
            captured["timeout"] = timeout
            return watchdog._dreamapi_worker_header(200, body, "application/json") + body, None

        def poll(self):
            return self.returncode

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(watchdog.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(watchdog, "_assign_windows_kill_on_close_job", lambda _process: None)
    result = watchdog.dreamapi_proxy_request(valid_payload(), "Bearer local-test-token")
    assert result == (200, body, "application/json")
    assert captured["command"][-1] == "--dreamapi-worker"
    assert "local-test-token" not in " ".join(captured["command"])
    assert json.loads(captured["input"])["authorization"] == "Bearer local-test-token"
    assert captured["timeout"] == (
        watchdog.DREAMAPI_TIMEOUT + watchdog.DREAMAPI_WORKER_START_GRACE
    )
    assert captured["kwargs"]["stderr"] is subprocess.DEVNULL
    assert captured["kwargs"]["creationflags"] == (
        watchdog.NO_WINDOW if watchdog.os.name == "nt" else 0
    )


def test_watchdog_does_not_follow_redirects_with_the_authorization_header():
    watchdog = load_module("watchdog_dreamapi_redirects", ROOT / "comfy_watchdog.py")
    handler = next(
        item for item in watchdog._dreamapi_opener.handlers
        if isinstance(item, watchdog._NoRedirectHandler)
    )
    assert handler.redirect_request(None, None, 307, "redirect", {}, "https://elsewhere.invalid") is None


def test_watchdog_timeout_terminates_kills_and_waits_before_return(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_hard_stop", ROOT / "comfy_watchdog.py")
    events = []

    class Process:
        returncode = None

        def communicate(self, input, timeout):
            events.append(("communicate", timeout, bool(input)))
            raise subprocess.TimeoutExpired("dreamapi-worker", timeout)

        def poll(self):
            events.append(("poll",))
            return self.returncode

        def terminate(self):
            events.append(("terminate",))

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("dreamapi-worker", timeout)
            self.returncode = -9
            return self.returncode

        def kill(self):
            events.append(("kill",))

    monkeypatch.setattr(watchdog, "DREAMAPI_TIMEOUT", 0.06)
    monkeypatch.setattr(watchdog, "DREAMAPI_WORKER_START_GRACE", 0.01)
    monkeypatch.setattr(watchdog, "_dreamapi_worker_process", Process)
    with pytest.raises(TimeoutError, match="hard timeout"):
        watchdog.dreamapi_proxy_request(valid_payload(), "Bearer local-test-token")
    assert events[0][0] == "communicate"
    assert events[0][1] == pytest.approx(0.07)
    assert events[0][2] is True
    assert events[1:] == [
        ("poll",), ("terminate",), ("wait", 1), ("kill",), ("wait", None),
    ]


def test_watchdog_single_flight_keeps_uncertainty_fence_after_timed_out_worker(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_single_flight_exit", ROOT / "comfy_watchdog.py")
    communicate_started = threading.Event()
    allow_timeout = threading.Event()
    terminate_wait_started = threading.Event()
    allow_worker_exit = threading.Event()
    worker_stopped = threading.Event()
    processes = []
    body = b'{"data":[]}'

    class SlowProcess:
        returncode = None

        def communicate(self, input, timeout):
            assert input and timeout > 0
            communicate_started.set()
            assert allow_timeout.wait(1)
            raise subprocess.TimeoutExpired("dreamapi-worker", timeout)

        def poll(self):
            return self.returncode

        def terminate(self):
            pass

        def wait(self, timeout=None):
            assert timeout == 1
            terminate_wait_started.set()
            assert allow_worker_exit.wait(1)
            self.returncode = -15
            worker_stopped.set()
            return self.returncode

    class FastProcess:
        returncode = 0

        def communicate(self, input, timeout):
            assert input and timeout > 0
            return watchdog._dreamapi_worker_header(200, body, "application/json") + body, None

        def poll(self):
            return self.returncode

    def fake_worker_process():
        if not processes:
            process = SlowProcess()
        else:
            assert worker_stopped.is_set()
            process = FastProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(watchdog, "DREAMAPI_TIMEOUT", 0.06)
    monkeypatch.setattr(watchdog, "DREAMAPI_WORKER_START_GRACE", 0.01)
    monkeypatch.setattr(watchdog, "_dreamapi_worker_process", fake_worker_process)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), watchdog.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def post():
        raw = json.dumps(valid_payload()).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/dreamapi/images/generations",
            data=raw,
            headers={
                "Authorization": "Bearer local-test-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    first_result = []
    first_thread = threading.Thread(target=lambda: first_result.append(post()))
    try:
        first_thread.start()
        assert communicate_started.wait(1)
        assert post() == (
            429, b'{"error": "DreamAPI generation already in progress"}',
        )
        assert len(processes) == 1
        allow_timeout.set()
        assert terminate_wait_started.wait(1)
        assert post() == (
            429, b'{"error": "DreamAPI generation already in progress"}',
        )
        assert not worker_stopped.is_set()
        allow_worker_exit.set()
        first_thread.join(timeout=1)
        assert not first_thread.is_alive()
        assert first_result[0][0] == 502
        assert json.loads(first_result[0][1]) == {
            "error": "DreamAPI workstation egress failed",
        }
        assert worker_stopped.is_set()
        assert post() == (
            429, b'{"error": "DreamAPI prior request outcome is still uncertain"}',
        )
        assert len(processes) == 1
    finally:
        allow_timeout.set()
        allow_worker_exit.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1)
        first_thread.join(timeout=1)


def test_watchdog_persistent_fence_blocks_restart_until_expiry(tmp_path):
    watchdog = load_module("watchdog_dreamapi_persistent_fence", ROOT / "comfy_watchdog.py")
    watchdog.DREAMAPI_FENCE_PATH = str(tmp_path / "persistent-fence.json")
    watchdog.DREAMAPI_FENCE_TTL = 30

    first = watchdog._acquire_dreamapi_fence(now=100)
    assert watchdog.dreamapi_uncertainty_fence_active(now=101) is True
    watchdog._release_dreamapi_fence(first, definitive=False)

    with pytest.raises(watchdog.DreamApiUncertaintyFenceActive):
        watchdog._acquire_dreamapi_fence(now=120)
    second = watchdog._acquire_dreamapi_fence(now=131)
    watchdog._release_dreamapi_fence(second, definitive=True)
    assert watchdog.dreamapi_uncertainty_fence_active(now=132) is False


@pytest.mark.parametrize("raw", [
    b'{"expires_at":NaN}',
    b'{"expires_at":9999999999}',
    b'{"unexpected":true}',
    b'x' * 4097,
])
def test_watchdog_corrupt_fence_records_fail_closed(tmp_path, raw):
    watchdog = load_module("watchdog_dreamapi_corrupt_fence", ROOT / "comfy_watchdog.py")
    path = tmp_path / "corrupt-fence.json"
    path.write_bytes(raw)
    watchdog.DREAMAPI_FENCE_PATH = str(path)

    now = time.time()
    assert watchdog.dreamapi_uncertainty_fence_active(now=now) is True
    with pytest.raises(watchdog.DreamApiUncertaintyFenceActive):
        watchdog._acquire_dreamapi_fence(now=now)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")
def test_windows_job_object_kills_worker_when_parent_process_dies(tmp_path):
    module_path = ROOT / "comfy_watchdog.py"
    code = r'''
import importlib.util, subprocess, sys, time
spec = importlib.util.spec_from_file_location("job_parent_watchdog", sys.argv[1])
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
job = watchdog._assign_windows_kill_on_close_job(child)
print(child.pid, flush=True)
time.sleep(60)
'''
    parent = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(module_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "COMFY_PANEL_DREAMAPI_FENCE": str(tmp_path / "job-fence.json")},
    )
    child_pid = None
    try:
        line = parent.stdout.readline().strip()
        assert line, parent.stderr.read()
        child_pid = int(line)
        parent.terminate()
        parent.wait(timeout=5)

        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, child_pid)
        if handle:
            try:
                assert kernel32.WaitForSingleObject(handle, 5000) == 0
            finally:
                kernel32.CloseHandle(handle)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)


@pytest.mark.parametrize("response_kind", ["success", "http_error"])
def test_watchdog_tightens_socket_timeout_before_every_body_read(monkeypatch, response_kind):
    watchdog = load_module(
        f"watchdog_dreamapi_socket_budget_{response_kind}", ROOT / "comfy_watchdog.py",
    )
    socket_timeouts = []

    class FakeSocket:
        def settimeout(self, value):
            socket_timeouts.append(value)

    class Response:
        status = 200
        headers = types.SimpleNamespace(get_content_type=lambda: "application/json")

        def __init__(self):
            self.closed = False
            self.fp = types.SimpleNamespace(raw=types.SimpleNamespace(_sock=FakeSocket()))
            self.chunks = [b'{"data":[]}', b""]

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def close(self): self.closed = True
        def read1(self, _size=-1):
            time.sleep(0.02)
            return self.chunks.pop(0)

    monkeypatch.setattr(watchdog, "DREAMAPI_TIMEOUT", 0.2)
    body = Response()

    def fake_urlopen(*_args, **_kwargs):
        if response_kind == "http_error":
            raise urllib.error.HTTPError(
                "https://dreamapi.club/v1/images/generations", 502, "Bad Gateway", {}, body,
            )
        return body

    monkeypatch.setattr(watchdog, "_dreamapi_urlopen", fake_urlopen)
    status, raw, content_type = watchdog._dreamapi_proxy_request_until(
        valid_payload(), "Bearer local-test-token",
        time.monotonic() + watchdog.DREAMAPI_TIMEOUT, {},
    )
    assert (status, raw, content_type) == (
        502 if response_kind == "http_error" else 200,
        b'{"data":[]}',
        "application/json",
    )
    assert len(socket_timeouts) == 2
    assert 0 < socket_timeouts[1] < socket_timeouts[0] <= 0.201


def test_watchdog_rejects_unbounded_or_malformed_worker_output(monkeypatch):
    watchdog = load_module("watchdog_dreamapi_worker_bounds", ROOT / "comfy_watchdog.py")
    body = b"abc"
    valid = watchdog._dreamapi_worker_header(200, body, "application/json") + body
    assert watchdog._decode_dreamapi_worker_output(valid) == (
        200, body, "application/json",
    )

    bad_length = b'{"body_length":4,"content_type":"application/json","status":200}\nabc'
    with pytest.raises(RuntimeError, match="body length"):
        watchdog._decode_dreamapi_worker_output(bad_length)
    bad_type = b'{"body_length":0,"content_type":"text/plain\\r\\nX: y","status":200}\n'
    with pytest.raises(RuntimeError, match="content type"):
        watchdog._decode_dreamapi_worker_output(bad_type)

    monkeypatch.setattr(watchdog, "DREAMAPI_RESPONSE_LIMIT", 2)
    with pytest.raises(RuntimeError, match="body length"):
        watchdog._decode_dreamapi_worker_output(valid)


def test_watchdog_timeout_abort_closes_wrappers_without_an_exposed_socket():
    watchdog = load_module("watchdog_dreamapi_abort_wrapper", ROOT / "comfy_watchdog.py")

    class Response:
        closed = False

        def close(self):
            self.closed = True

    response = Response()
    watchdog._dreamapi_abort_response(response)
    assert response.closed is True


def test_server_egress_endpoint_is_optional_and_loopback_only(monkeypatch):
    server = load_module("server_dreamapi_egress", ROOT / "server.py")
    monkeypatch.setattr(server, "DREAMAPI_BASE_URL", "https://dreamapi.club")
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "")
    assert server._dreamapi_request_endpoint() == "https://dreamapi.club/v1/images/generations"

    monkeypatch.setattr(
        server, "DREAMAPI_EGRESS_URL", "http://127.0.0.1:8198/dreamapi/images/generations",
    )
    assert server._dreamapi_request_endpoint() == "http://127.0.0.1:8198/dreamapi/images/generations"

    for unsafe in (
        "https://127.0.0.1:8198/dreamapi/images/generations",
        "http://8.210.125.65:8198/dreamapi/images/generations",
        "http://user:pass@127.0.0.1:8198/dreamapi/images/generations",
        "http://127.0.0.1:8198/wrong-path",
        "http://127.0.0.1:8198/dreamapi/images/generations?next=elsewhere",
    ):
        monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", unsafe)
        with pytest.raises(RuntimeError, match="loopback"):
            server._dreamapi_request_endpoint()
