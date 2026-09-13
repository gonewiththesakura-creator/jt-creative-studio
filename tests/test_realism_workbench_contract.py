from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "static" / "realism.html"
BUILDER = ROOT / "build_realism_workbench.py"
SERVER = (ROOT / "server.py").read_text(encoding="utf8")
HTML = PAGE.read_text(encoding="utf8") if PAGE.exists() else ""
SCRIPT = BUILDER.read_text(encoding="utf8") if BUILDER.exists() else ""

checks = {
    "durable portable page and builder": PAGE.exists() and BUILDER.exists() and "P.read_text" not in SCRIPT and "Path(__file__).resolve().parent" in SCRIPT and 'Path(r"D:/' not in SCRIPT,
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
    "ambiguous submit reuses durable request id": all(x in HTML for x in ["pendingSubmitKey", "localStorage.getItem(pendingSubmitKey", "localStorage.setItem(pendingSubmitKey", "localStorage.removeItem(pendingSubmitKey"]),
    "only definitive 4xx clears pending id": all(x in HTML for x in ["error.status=response.status", "error.status>=400&&error.status<500", "if(definitiveRejection)localStorage.removeItem(pendingSubmitKey)"]),
    "independent task cards": all(x in HTML for x in ["const tasks=new Map()", "addTaskCard", "task-time", "setInterval"]),
    "refresh restoration": "sessionStorage" in HTML and "restoreTasks" in HTML,
    "history and favorites": all(x in HTML for x in ["/api/jobs", "/api/favorites", "applySnapshot", "selection_snapshot"]),
    "server filters realism history before limit": "REALISM_HISTORY_LIMIT" in SERVER and "realism_history_jobs" in SERVER,
    "two drawers preserve grouping": all(x in HTML for x in ["mapping.group", "common", "advanced"]),
    "dependent controls follow native toggle": all(x in HTML for x in ["mapping.depends_on", "updateDependencies", "control.disabled"]),
    "mobile touch and no overflow": all(x in HTML for x in ["@media(max-width:820px)", "min-height:44px", "overflow-x:hidden"]),
    "actionable errors without leaking other jobs": "任务号" in HTML and '"running_job":' not in SERVER and '"running_jobs":' not in SERVER,
    "RH coin cost shown on task and history": all(x in HTML for x in ["coinText", "RH币：", "job.rh_coins"]),
    "non-image results use download card": all(x in HTML for x in ["isPreviewableImage", "结果文件", "file-result", "canPreview", "if(canPreview)"]) and "galleryMain.appendChild(file)" in HTML,
    "provider strings never interpolate into html": all(x in HTML for x in ["createResultItem", "createTaskCard", "createHistoryItem", "createFavoriteItem", "safeRemoteUrl", "textContent=", "image.src="]) and all(x not in HTML for x in ["card.innerHTML=", "item.innerHTML=", "d.innerHTML=", "innerHTML='<img"]),
    "load errors render as text": "showWorkflowLoadError" in HTML and "commonControls.innerHTML='<div class=\"config-state error\">'" not in HTML,
    "navigation exposes one unified console": all('href="/realism"' in (ROOT / "static" / name).read_text(encoding="utf8") and 'href="/realcomic"' not in (ROOT / "static" / name).read_text(encoding="utf8") for name in ["index.html", "promptgen.html", "video.html"]),
    "legacy realcomic page redirects": '/realism?workflow=realcomic' in (ROOT / "static" / "realcomic.html").read_text(encoding="utf8"),
}
for name, passed in checks.items():
    print(name, passed)
raise SystemExit(0 if all(checks.values()) else 1)
