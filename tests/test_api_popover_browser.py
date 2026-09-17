import base64
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

import pytest
import requests

websocket = pytest.importorskip("websocket")

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Cdp:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, origin="http://localhost")
        self.next_id = 1

    def call(self, method, params=None):
        call_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == call_id:
                assert "error" not in message, message["error"]
                return message.get("result", {})

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        assert "exceptionDetails" not in result, result["exceptionDetails"]
        return result["result"].get("value")

    def close(self):
        self.ws.close()


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for browser state")


@pytest.fixture(scope="module")
def browser():
    if not CHROME.exists():
        pytest.skip("Chrome is unavailable")
    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    debug_port = free_port()
    with tempfile.TemporaryDirectory(prefix="comfy-api-popover-") as profile:
        process = subprocess.Popen(
            [
                str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*",
                f"--user-data-dir={profile}", "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        version_url = f"http://127.0.0.1:{debug_port}/json/version"
        wait_until(lambda: requests.get(version_url, timeout=0.2).ok)
        browser_cdp = Cdp(requests.get(version_url, timeout=1).json()["webSocketDebuggerUrl"])
        try:
            yield browser_cdp, f"http://127.0.0.1:{server.server_port}/static/index.html", debug_port
        finally:
            browser_cdp.close()
            process.terminate()
            process.wait(timeout=5)
    server.shutdown()


def open_creator(browser_cdp, url, debug_port, width, height):
    target_id = browser_cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
    targets = requests.get(f"http://127.0.0.1:{debug_port}/json/list", timeout=1).json()
    target = next(item for item in targets if item["id"] == target_id)
    page = Cdp(target["webSocketDebuggerUrl"])
    page.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
    )
    page.call("Page.navigate", {"url": url})
    wait_until(lambda: page.evaluate("document.readyState === 'complete'"))
    wait_until(lambda: page.evaluate("Boolean(document.getElementById('apiDrawerOpen'))"))
    return page


@pytest.mark.parametrize("width,height", [(390, 844), (1280, 720), (1440, 900)])
def test_api_popover_stays_visible_and_operable_in_real_browser(browser, width, height):
    browser_cdp, url, debug_port = browser
    page = open_creator(browser_cdp, url, debug_port, width, height)
    try:
        page.evaluate("document.getElementById('apiDrawerOpen').scrollIntoView({block:'end'})")
        before_scroll = page.evaluate("scrollY")
        page.evaluate("document.getElementById('apiDrawerOpen').click()")
        wait_until(lambda: page.evaluate("!document.getElementById('apiDrawer').hidden"))
        time.sleep(0.25)
        layout = page.evaluate(
            "(() => { const rect = ({ top, right, bottom, left }) => ({ top, right, bottom, left }); const panel = apiDrawer.getBoundingClientRect(), trigger = apiDrawerOpen.getBoundingClientRect(), pane = document.querySelector('.creation-pane').getBoundingClientRect(); return { panel: rect(panel), trigger: rect(trigger), pane: rect(pane), width: innerWidth, scrollWidth: document.documentElement.scrollWidth, pageY: scrollY, active: document.activeElement.id, panelClientHeight: apiDrawer.clientHeight, panelScrollHeight: apiDrawer.scrollHeight }; })()"
        )
        assert layout["panel"]["top"] >= max(8, layout["pane"]["top"] + 8) - 1
        assert layout["panel"]["bottom"] <= layout["trigger"]["top"] - 7
        assert layout["panel"]["left"] >= 0
        assert layout["panel"]["right"] <= layout["width"] + 1
        assert layout["scrollWidth"] <= layout["width"]
        assert layout["active"] == "apiModel"
        assert abs(layout["pageY"] - before_scroll) <= 1
        page.evaluate("apiDrawer.scrollTop = apiDrawer.scrollHeight")
        at_bottom = page.evaluate("apiDrawer.scrollTop + apiDrawer.clientHeight >= apiDrawer.scrollHeight - 1")
        assert at_bottom
        page.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape"})
        page.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape"})
        wait_until(lambda: page.evaluate("apiDrawer.hidden"))
        assert page.evaluate("document.activeElement.id") == "apiDrawerOpen"
        if os.getenv("CAPTURE_BROWSER_EVIDENCE") and (width, height) in {(390, 844), (1440, 900)}:
            page.evaluate("document.getElementById('apiDrawerOpen').click()")
            wait_until(lambda: page.evaluate("apiDrawer.classList.contains('open')"))
            time.sleep(0.25)
            shot = page.call("Page.captureScreenshot", {"format": "png"})["data"]
            (ROOT / "evidence" / f"api-popover-{width}x{height}.png").write_bytes(base64.b64decode(shot))
    finally:
        page.close()
