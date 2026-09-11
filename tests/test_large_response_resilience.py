import importlib.util
import socket
import threading
import time
import tempfile
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
spec = importlib.util.spec_from_file_location("large_response_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class FakeConnection:
    def __init__(self, initial_timeout):
        self.timeout = initial_timeout
        self.timeouts = [initial_timeout]
        self.shutdown_called = False

    def settimeout(self, value):
        self.timeout = value
        self.timeouts.append(value)

    def shutdown(self, how):
        self.shutdown_called = True


class RecordingWriter:
    def __init__(self, connection, delay=0, entered=None, release=None):
        self.connection = connection
        self.delay = delay
        self.entered = entered
        self.release = release
        self.data = bytearray()

    def write(self, data):
        if self.entered:
            self.entered.set()
        if self.release:
            if not self.release.wait(3):
                raise TimeoutError("test writer was not released")
        elif self.delay:
            if self.connection.timeout is not None and self.delay > self.connection.timeout:
                time.sleep(self.connection.timeout)
                raise socket.timeout("simulated write idle timeout")
            time.sleep(self.delay)
        self.data.extend(data)
        return len(data)

    def flush(self):
        return None


class FailingWriter(RecordingWriter):
    def write(self, data):
        raise ConnectionResetError("client disconnected")


class HarnessHandler(server.Handler):
    def __init__(self, server_obj, writer, connection):
        self.server = server_obj
        self.wfile = writer
        self.connection = connection
        self.request_version = "HTTP/1.1"
        self.command = "GET"
        self.path = "/"
        self.requestline = "GET / HTTP/1.1"
        self.statuses = []
        self.headers_sent = []

    def send_response(self, code, message=None):
        self.statuses.append(code)

    def send_header(self, key, value):
        self.headers_sent.append((key, str(value)))

    def end_headers(self):
        return None


class ResponseState:
    def __init__(self, slots):
        self._large_response_slots = threading.BoundedSemaphore(slots)
        self._metrics_lock = threading.Lock()
        self._active_large_responses = 0


def globals_snapshot():
    return {
        "CLIENT_SOCKET_TIMEOUT": server.CLIENT_SOCKET_TIMEOUT,
        "MAX_LARGE_RESPONSE_WORKERS": server.MAX_LARGE_RESPONSE_WORKERS,
        "RESPONSE_SOCKET_TIMEOUT": server.RESPONSE_SOCKET_TIMEOUT,
        "RESPONSE_BODY_BASE_TIMEOUT": server.RESPONSE_BODY_BASE_TIMEOUT,
        "RESPONSE_BODY_MIN_BYTES_PER_SECOND": server.RESPONSE_BODY_MIN_BYTES_PER_SECOND,
        "RESPONSE_BODY_MAX_TIMEOUT": server.RESPONSE_BODY_MAX_TIMEOUT,
    }


def restore_globals(old):
    for key, value in old.items():
        setattr(server, key, value)


def test_large_response_uses_a_separate_write_timeout():
    old = globals_snapshot()
    server.CLIENT_SOCKET_TIMEOUT = 0.05
    server.RESPONSE_SOCKET_TIMEOUT = 0.5
    server.RESPONSE_BODY_BASE_TIMEOUT = 1
    server.RESPONSE_BODY_MIN_BYTES_PER_SECOND = 1024 * 1024
    server.RESPONSE_BODY_MAX_TIMEOUT = 2
    state = ResponseState(1)
    connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
    writer = RecordingWriter(connection, delay=0.1)
    handler = HarnessHandler(state, writer, connection)
    body = b"x" * server.LARGE_RESPONSE_THRESHOLD
    try:
        handler._send(200, body)
        assert handler.statuses == [200]
        assert bytes(writer.data) == body
        assert server.RESPONSE_SOCKET_TIMEOUT in connection.timeouts
        assert connection.timeouts[-1] == server.CLIENT_SOCKET_TIMEOUT
        assert state._active_large_responses == 0
    finally:
        restore_globals(old)


def test_production_large_response_timeouts_cover_slow_public_links():
    assert server.RESPONSE_SOCKET_TIMEOUT >= 180
    assert server.RESPONSE_BODY_MAX_TIMEOUT >= 300


def test_large_responses_are_bounded_and_small_responses_keep_capacity():
    old = globals_snapshot()
    server.MAX_LARGE_RESPONSE_WORKERS = 2
    server.RESPONSE_SOCKET_TIMEOUT = 2
    server.RESPONSE_BODY_BASE_TIMEOUT = 2
    server.RESPONSE_BODY_MAX_TIMEOUT = 3
    state = ResponseState(2)
    release = threading.Event()
    entered = [threading.Event(), threading.Event()]
    handlers = []
    threads = []
    body = b"x" * server.LARGE_RESPONSE_THRESHOLD
    try:
        for event in entered:
            connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
            writer = RecordingWriter(connection, entered=event, release=release)
            handler = HarnessHandler(state, writer, connection)
            handlers.append(handler)
            thread = threading.Thread(target=handler._send, args=(200, body), daemon=True)
            thread.start()
            threads.append(thread)
        assert all(event.wait(1) for event in entered)
        assert state._active_large_responses == 2

        rejected_connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
        rejected_writer = RecordingWriter(rejected_connection)
        rejected = HarnessHandler(state, rejected_writer, rejected_connection)
        rejected._send(200, body)
        assert rejected.statuses == [503]
        assert b"large response capacity busy" in rejected_writer.data

        live_connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
        live_writer = RecordingWriter(live_connection)
        live = HarnessHandler(state, live_writer, live_connection)
        live._send(200, b'{"ok":true,"service":"comfy-panel"}')
        assert live.statuses == [200]
        assert b'"service":"comfy-panel"' in live_writer.data
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=2)
        restore_globals(old)
    assert state._active_large_responses == 0


def test_streamed_files_use_the_same_bounded_large_response_writer():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    image_branch = source.split('elif path.startswith("/api/image/"):', 1)[1].split(
        'elif path == "/realcomic":', 1
    )[0]
    assert "_write_stream" in image_branch
    assert "self.wfile.write(chunk)" not in image_branch


def test_large_response_slot_is_released_after_client_disconnect():
    state = ResponseState(1)
    body = b"x" * server.LARGE_RESPONSE_THRESHOLD
    failed_connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
    failed = HarnessHandler(state, FailingWriter(failed_connection), failed_connection)
    try:
        failed._send(200, body)
    except ConnectionResetError:
        pass
    assert state._active_large_responses == 0

    next_connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
    next_writer = RecordingWriter(next_connection)
    next_handler = HarnessHandler(state, next_writer, next_connection)
    next_handler._send(200, body)
    assert next_handler.statuses == [200]
    assert bytes(next_writer.data) == body
    assert state._active_large_responses == 0


def test_image_stream_timeout_never_appends_a_second_http_response(monkeypatch):
    state = ResponseState(1)
    connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
    handler = HarnessHandler(state, RecordingWriter(connection), connection)
    handler.path = "/api/image/job/image.png"
    handler._auth = lambda: True
    handler._write_stream = lambda *args, **kwargs: (_ for _ in ()).throw(socket.timeout("slow client"))
    server.JOBS_DIR = Path(tempfile.mkdtemp())
    path = server.JOBS_DIR / "job" / "image.png"
    path.parent.mkdir()
    path.write_bytes(b"png")
    handler.do_GET()
    assert handler.statuses == []


def test_stream_opens_file_before_sending_200(monkeypatch, tmp_path):
    state = ResponseState(1)
    connection = FakeConnection(server.CLIENT_SOCKET_TIMEOUT)
    handler = HarnessHandler(state, RecordingWriter(connection), connection)
    path = tmp_path / "vanished.png"
    path.write_bytes(b"x" * server.LARGE_RESPONSE_THRESHOLD)
    original_open = Path.open

    def vanish_on_open(self, *args, **kwargs):
        if self == path:
            self.unlink(missing_ok=True)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", vanish_on_open)
    try:
        handler._write_stream(path, "image/png")
    except FileNotFoundError:
        pass
    assert handler.statuses == []
