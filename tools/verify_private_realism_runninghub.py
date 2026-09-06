"""Serial real-E2E verifier for the seven private RunningHub workflows.

Runs on the relay host where RUNNINGHUB_API_KEY already exists. A durable state
file is written before polling: an existing taskId is always resumed and never
submitted again. No API key is printed or stored in the state file.
"""
import json, os, pathlib, time, urllib.parse, urllib.request, uuid

BASE = "https://www.runninghub.ai/openapi/v2"
UPLOAD = "https://www.runninghub.cn/task/openapi/upload"
STATE = pathlib.Path("/tmp/private_realism_e2e_state.json")
SOURCE = pathlib.Path("/tmp/private_realism_input.png")
PAYLOADS = json.loads(os.environ["PRIVATE_REALISM_PAYLOADS"])
KEY = os.environ["RUNNINGHUB_API_KEY"]


def save(state):
    tmp = STATE.with_suffix(".new")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def upload_once(state):
    if state.get("uploaded_file"):
        return state["uploaded_file"]
    boundary = "----rh" + uuid.uuid4().hex
    def field(name, value):
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    def filepart(name, filename):
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n').encode()
    body = b"".join([field("apiKey", KEY), field("fileType", "input"), filepart("file", SOURCE.name), SOURCE.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode()])
    request = urllib.request.Request(UPLOAD, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    if result.get("code") != 0 or not (result.get("data") or {}).get("fileName"):
        raise RuntimeError(f"upload failed: {result.get('code')} {result.get('msg')}")
    state["uploaded_file"] = result["data"]["fileName"]
    save(state)
    return state["uploaded_file"]


def query(task_id):
    request = urllib.request.Request(BASE + "/query", data=json.dumps({"taskId": task_id}).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def result_urls(result):
    data = result.get("results") or result.get("data") or []
    if isinstance(data, dict):
        data = data.get("results") or data.get("outputs") or []
    urls = []
    for row in data if isinstance(data, list) else []:
        if isinstance(row, dict):
            url = row.get("url") or row.get("fileUrl")
            if url: urls.append(url)
    return urls


def run_one(item, state, uploaded):
    record = state.setdefault("workflows", {}).setdefault(item["internal_id"], {})
    if record.get("status") == "SUCCESS":
        print(json.dumps({"event": "skip_success", "internal_id": item["internal_id"], "taskId": record.get("taskId")})); return
    if record.get("status") == "SUBMIT_OUTCOME_UNKNOWN":
        raise RuntimeError(
            f"manual provider check required before retrying {item['internal_id']}; "
            "the previous submit may already have been billed"
        )
    task_id = record.get("taskId")
    if not task_id:
        nodes = json.loads(json.dumps(item["nodes"]))
        for node in nodes:
            if node.get("fieldValue") == "__UPLOADED__": node["fieldValue"] = uploaded
        body = {"addMetadata": False, "nodeInfoList": nodes,
                "instanceType": item.get("instance_type", "default"), "usePersonalQueue": "false"}
        request = urllib.request.Request(BASE + "/run/workflow/" + item["workflow_id"], data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response: result = json.load(response)
        except Exception as error:
            record.update({"status": "SUBMIT_OUTCOME_UNKNOWN", "error": f"{type(error).__name__}: {str(error)[:240]}"}); save(state); raise
        task_id = result.get("taskId")
        record.update({"taskId": task_id, "status": str(result.get("status") or "UNKNOWN"), "errorCode": result.get("errorCode"), "errorMessage": result.get("errorMessage")})
        if not task_id and result.get("errorCode"):
            record["status"] = "VALIDATION_FAILED"
        save(state)
        print(json.dumps({"event": "submitted", "internal_id": item["internal_id"], "taskId": task_id, "status": record["status"], "errorCode": record["errorCode"]}, ensure_ascii=False), flush=True)
        if not task_id: raise RuntimeError(f"no taskId: {record}")
    deadline = time.time() + 2400; last = None
    while time.time() < deadline:
        result = query(task_id); status = str(result.get("status") or "").upper()
        if status != last:
            print(json.dumps({"event": "poll", "internal_id": item["internal_id"], "taskId": task_id, "status": status, "errorCode": result.get("errorCode"), "errorMessage": result.get("errorMessage")}, ensure_ascii=False), flush=True); last = status
        if status == "SUCCESS":
            urls = result_urls(result)
            record.update({"status": status, "result_count": len(urls), "urls": urls,
                           "result_hosts": sorted({urllib.parse.urlparse(url).hostname for url in urls})}); save(state)
            if not urls: raise RuntimeError("SUCCESS without result URL")
            return
        if status in {"FAILED", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT"}:
            record.update({"status": status, "errorCode": result.get("errorCode"), "errorMessage": result.get("errorMessage")}); save(state); raise RuntimeError(f"task failed: {record}")
        time.sleep(10)
    record["status"] = "POLL_TIMEOUT"; save(state); raise RuntimeError(f"poll timeout: {task_id}")


state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"workflows": {}}
uploaded = upload_once(state)
for payload in PAYLOADS:
    run_one(payload, state, uploaded)
print(json.dumps({"event": "complete", "completed": len([x for x in state["workflows"].values() if x.get("status") == "SUCCESS"])}, ensure_ascii=False))
