import base64
import itertools
import json
import os
import re
import time
import urllib.request

import websocket

PORT = int(os.environ.get("POLISH_CDP_PORT", "9233"))
BASE = os.environ.get("POLISH_PUBLIC_BASE", "http://8.210.125.65:8189")
TARGETS = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list"))
TARGET = next(item for item in TARGETS if item["type"] == "page")
WS = websocket.create_connection(TARGET["webSocketDebuggerUrl"], timeout=60)
SEQ = itertools.count(1)
EXCEPTIONS = []


def call(method, params=None):
    call_id = next(SEQ)
    WS.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
    while True:
        reply = json.loads(WS.recv())
        if reply.get("method") == "Runtime.exceptionThrown":
            EXCEPTIONS.append(reply)
        if reply.get("id") == call_id:
            return reply


def evaluate(expression):
    reply = call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
    )
    if reply.get("result", {}).get("exceptionDetails"):
        raise RuntimeError(reply)
    return reply.get("result", {}).get("result", {}).get("value")


def viewport(width, height):
    call(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": width <= 480,
            "screenWidth": width,
            "screenHeight": height,
        },
    )


def navigate(route, ready, width=1200, height=820):
    viewport(width, height)
    separator = "&" if "?" in route else "?"
    url = f"{BASE}{route}{separator}polish={time.time_ns()}"
    evaluate(f"location.href={json.dumps(url)}")
    for _ in range(120):
        try:
            if evaluate("document.readyState==='complete'&&(" + ready + ")"):
                break
        except Exception:
            pass
        time.sleep(0.35)
    else:
        raise RuntimeError("page not ready: " + url)
    EXCEPTIONS.clear()
    time.sleep(0.25)


def screenshot(name):
    reply = call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    path = os.path.expandvars(f"$LOCALAPPDATA/Temp/polish_public_{name}.png")
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(reply["result"]["data"]))
    return path


def layout(route, ready, active, width, height, name):
    navigate(route, ready, width, height)
    data = evaluate(
        """(()=>{
          const footerButtons=[...document.querySelectorAll('.creation-footer button')];
          const current=document.querySelector('.topnav-link.active');
          return {
            documentWidth:document.documentElement.scrollWidth,
            viewportWidth:document.documentElement.clientWidth,
            active:current?.innerText||'',
            columns:getComputedStyle(document.querySelector('.studio-grid')).gridTemplateColumns,
            buttonHeights:footerButtons.map(x=>Math.round(x.getBoundingClientRect().height)),
            toolLabels:[...document.querySelectorAll('.topbar-action')].map(x=>x.innerText.trim()),
            homeLinks:[document.querySelector('.brand')?.getAttribute('href'),[...document.querySelectorAll('.topnav-link')].find(x=>x.innerText==='创作台')?.getAttribute('href')],
            legacyLinks:[...document.querySelectorAll('a')].filter(x=>x.getAttribute('href')==='/promptgen').length,
            shell:!!document.querySelector('.app-shell'),
            preview:!!document.querySelector('.preview-pane')
          }
        })()"""
    )
    print("LAYOUT", name, data)
    assert data["shell"] and data["preview"]
    assert data["documentWidth"] <= data["viewportWidth"] + 1
    assert data["active"] == active
    assert all(value >= 44 for value in data["buttonHeights"])
    assert all(label for label in data["toolLabels"])
    assert data["homeLinks"] == ["/", "/"] and data["legacyLinks"] == 0
    return screenshot(name)


call("Runtime.enable")
call("Page.enable")

# Read the live APIs before relying on any overlay or video UI.
navigate("/promptgen", "typeof importGeneratedPromptToManual==='function'")
canonical_state = evaluate(
    """({path:location.pathname,canonical:document.querySelector('link[rel=canonical]')?.getAttribute('href')||'',brand:document.querySelector('.brand').getAttribute('href'),creator:document.querySelector('.topnav-link.active').getAttribute('href')})"""
)
print("CANONICAL_HOME", canonical_state)
assert canonical_state == {"path": "/", "canonical": "/", "brand": "/", "creator": "/"}
api_state = evaluate(
    """(async()=>{
      const read=async path=>{const r=await fetch(path);const d=await r.json();if(!r.ok)throw new Error(path+': '+(d.error||r.status));return d};
      const [favorites,jobs,workflows]=await Promise.all([read('/api/favorites'),read('/api/jobs'),read('/api/workflows')]);
      return {favorites:Array.isArray(favorites),favoriteCount:favorites.length,jobs:Array.isArray(jobs),jobCount:jobs.length,workflowCount:workflows.length,videoWorkflowCount:workflows.filter(x=>x.kind==='video').length};
    })()"""
)
print("PUBLIC_APIS", api_state)
assert api_state["favorites"] and api_state["jobs"]
assert api_state["videoWorkflowCount"] == 5

# Exact random/options Prompt import plus distinct liquid states.
main_state = evaluate(
    """(async()=>{
      const expected=buildCorePrompt();
      importGeneratedPrompt.click();
      const imported=promptMode.value==='manual'&&manualPositive.value===expected&&manualNegative.value===cfg().negative;
      const idle={cloud:getComputedStyle(genCloudBtn).backgroundColor,local:getComputedStyle(genLocalBtn).backgroundColor};
      setLiquidLoading(genCloudBtn,true);setLiquidProgress(genCloudBtn,63);setLiquidLoading(genLocalBtn,true);setLiquidProgress(genLocalBtn,27);
      await Promise.all([waitLiquidSettled(genCloudBtn,63),waitLiquidSettled(genLocalBtn,27)]);
      const loading={cloud:getComputedStyle(genCloudBtn).getPropertyValue('--liquid-color').trim(),local:getComputedStyle(genLocalBtn).getPropertyValue('--liquid-color').trim(),cloudLevel:getComputedStyle(genCloudBtn).getPropertyValue('--liquid-level').trim(),localLevel:getComputedStyle(genLocalBtn).getPropertyValue('--liquid-level').trim()};
      setLiquidLoading(genCloudBtn,false);setLiquidLoading(genLocalBtn,false);
      return {imported,idle,loading};
    })()"""
)
print("MAIN_INTERACTIONS", main_state)
assert main_state["imported"]
assert main_state["idle"]["cloud"] == "rgb(255, 255, 255)"
assert main_state["idle"]["local"] == "rgb(255, 255, 255)"
assert main_state["loading"]["cloud"] != main_state["loading"]["local"]
def liquid_level_percent(value):
    match = re.fullmatch(r"calc\(100% - ([0-9]+(?:\.[0-9]+)?)%\)", value)
    assert match, value
    return float(match.group(1))

assert liquid_level_percent(main_state["loading"]["cloudLevel"]) == 63
assert liquid_level_percent(main_state["loading"]["localLevel"]) == 27

# Real favorites API rendering, fixed header geometry, close, and reopen-at-top.
library_state = evaluate(
    """(async()=>{
      favOpen.click();
      for(let i=0;i<300&&favList.querySelectorAll('.job').length<%s;i++)await new Promise(r=>setTimeout(r,100));
      const panel=favOverlay.querySelector('.library-panel'),head=favOverlay.querySelector('.library-header'),scroll=favOverlay.querySelector('.library-scroll');
      const before=head.getBoundingClientRect();scroll.scrollTop=scroll.scrollHeight;const after=head.getBoundingClientRect(),sr=scroll.getBoundingClientRect();
      const hit=document.elementFromPoint(after.left+30,after.top+30);
      const geometry={panelOverflow:getComputedStyle(panel).overflow,scrollOverflow:getComputedStyle(scroll).overflowY,headerStable:Math.abs(before.top-after.top)<1,edgesMeet:Math.abs(after.bottom-sr.top)<1,headerOwnsHit:head.contains(hit)};
      const renderedCards=favList.querySelectorAll('.job').length,renderedImages=favList.querySelectorAll('img').length,renderedText=favList.innerText.slice(0,80);
      favOverlay.querySelector('.close').click();const closed=!favOverlay.classList.contains('open');scroll.scrollTop=100;favOpen.click();const reopenedTop=scroll.scrollTop;favOverlay.querySelector('.close').click();
      return {geometry,closed,reopenedTop,cards:renderedCards,images:renderedImages,renderedText};
    })()""" % api_state["favoriteCount"]
)
print("PUBLIC_LIBRARY", library_state)
assert library_state["geometry"] == {
    "panelOverflow": "hidden",
    "scrollOverflow": "auto",
    "headerStable": True,
    "edgesMeet": True,
    "headerOwnsHit": True,
}
assert library_state["closed"] and library_state["reopenedTop"] == 0
assert library_state["cards"] == api_state["favoriteCount"]
assert library_state["images"] == api_state["favoriteCount"]

# Original pages retain import behavior on the live server.
for route, active in [("/original-sketch", "原始铅绘"), ("/original-graphic", "原始古风")]:
    navigate(route, "typeof importGeneratedPromptToManual==='function'")
    imported = evaluate(
        """(()=>{const expected=cloudStripStyleTokens(buildPositive());importGeneratedPrompt.click();return cloudPromptMode.value==='manual'&&manualPositive.value===expected&&manualNegative.value===NEGATIVE})()"""
    )
    print("ORIGINAL_IMPORT", route, imported)
    assert imported

# Public video route must render the real five workflows, not the local fallback.
navigate("/video", "typeof retryWorkflows==='function'&&(document.querySelectorAll('#wfSwitch button[data-wf]').length>0||!!document.querySelector('.config-error'))")
video_state = evaluate(
    """({workflowButtons:document.querySelectorAll('#wfSwitch button[data-wf]').length,names:[...document.querySelectorAll('#wfSwitch button[data-wf]')].map(x=>x.innerText.trim()),error:document.querySelector('.config-error')?.innerText||'',generateDisabled:genBtn.disabled,preview:document.querySelector('#videoEmpty')?.innerText||'',functions:[typeof uploadMedia,typeof generate,typeof pollTask]})"""
)
print("PUBLIC_VIDEO", video_state)
assert video_state["workflowButtons"] == 5
assert not video_state["error"] and not video_state["generateDisabled"]
assert all(item == "function" for item in video_state["functions"])
assert "视频将在这里播放" in video_state["preview"]

pages = [
    ("/promptgen", "typeof importGeneratedPromptToManual==='function'", "创作台", "main"),
    ("/original-sketch", "typeof importGeneratedPromptToManual==='function'", "原始铅绘", "sketch"),
    ("/original-graphic", "typeof importGeneratedPromptToManual==='function'", "原始古风", "graphic"),
    ("/video", "typeof retryWorkflows==='function'&&document.querySelectorAll('#wfSwitch button[data-wf]').length===5", "视频", "video"),
]
shots = []
for route, ready, active, name in pages:
    shots.append(layout(route, ready, active, 1200, 820, name + "_desktop"))
    shots.append(layout(route, ready, active, 393, 852, name + "_mobile"))

print("EXCEPTIONS", len(EXCEPTIONS))
assert not EXCEPTIONS
print("PUBLIC_UI_POLISH_E2E_OK", json.dumps(shots, ensure_ascii=False))
WS.close()
