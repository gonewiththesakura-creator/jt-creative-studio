from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
PAGE = ROOT / "static" / "realism.html"
BUILDER = ROOT / "build_realism_workbench.py"
SERVER = (ROOT / "server.py").read_text(encoding="utf8")
HTML = PAGE.read_text(encoding="utf8") if PAGE.exists() else ""
SCRIPT = BUILDER.read_text(encoding="utf8") if BUILDER.exists() else ""

checks = {
    "durable page and builder": PAGE.exists() and BUILDER.exists() and "P.read_text" not in SCRIPT,
    "realism route": '"/realism"' in SERVER and '"realism.html"' in SERVER,
    "workflow schema loaded": "/api/workflows" in HTML and "rh_workflow" in HTML and "ai_app" in HTML,
    "no client workflow id fields": "workflowId" not in HTML and "nodeInfoList" not in HTML,
    "exactly two configuration drawers": HTML.count('<section class="config-drawer"') == 2 and all(x in HTML for x in ["核心操作", "常用设置", "高级与输出"]),
    "all schema input types": all(x in HTML for x in ["renderImageControl", "renderTextControl", "renderBooleanControl", "renderSelectControl", "renderNumberControl"]),
    "boolean false survives serialization": "control.checked" in HTML and "params[key]=readControlValue" in HTML,
    "integer stays decimal text until server validation": "if(ref.type==='int')return ref.control.value" in HTML and "Number.parseInt(ref.control.value" not in HTML,
    "schema validation metadata rendered": all(x in HTML for x in ["mapping.min", "mapping.max", "mapping.step", "mapping.required"]),
    "generic upload and generate endpoints": all(x in HTML for x in ["/api/workflow-upload", "/api/workflow-generate"]),
    "idempotent client request": "client_request_id" in HTML,
    "independent task cards": all(x in HTML for x in ["const tasks=new Map()", "addTaskCard", "task-time", "setInterval"]),
    "refresh restoration": "sessionStorage" in HTML and "restoreTasks" in HTML,
    "history and favorites": all(x in HTML for x in ["/api/jobs", "/api/favorites", "applySnapshot", "selection_snapshot"]),
    "two drawers preserve grouping": all(x in HTML for x in ["mapping.group", "common", "advanced"]),
    "mobile touch and no overflow": all(x in HTML for x in ["@media(max-width:820px)", "min-height:44px", "overflow-x:hidden"]),
    "actionable errors": all(x in HTML for x in ["任务号", "running_job", "running_jobs"]),
    "provider strings never interpolate into html": all(x in HTML for x in ["createResultItem", "createTaskCard", "createHistoryItem", "createFavoriteItem", "safeRemoteUrl", "textContent=", "image.src="]) and all(x not in HTML for x in ["card.innerHTML=", "item.innerHTML=", "d.innerHTML=", "innerHTML='<img"]),
    "load errors render as text": "showWorkflowLoadError" in HTML and "commonControls.innerHTML='<div class=\"config-state error\">'" not in HTML,
    "navigation exposes console": all('href="/realism"' in (ROOT / "static" / name).read_text(encoding="utf8") for name in ["index.html", "promptgen.html", "original_sketch.html", "original_graphic.html", "realcomic.html", "video.html"]),
}
for name, passed in checks.items():
    print(name, passed)
raise SystemExit(0 if all(checks.values()) else 1)
