import http.client
import http.server
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SPEC = importlib.util.spec_from_file_location("generic_workflow_http", ROOT / "server.py")
server_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server_module)

fixture = {
    "id": "fixture_3in1",
    "name": "Fixture 3in1",
    "desc": "test only",
    "kind": "rh_workflow",
    "backend": "runninghub",
    "rh_workflow_id": "9007199254740990",
    "rh_media": {
        "source_image": {"node": "101", "field": "image", "type": "image", "label": "二次元原图", "required": True, "group": "common"}
    },
    "rh_params": {
        "route_a": {"node": "102", "field": "enabled", "type": "boolean", "label": "写实A", "default": True, "group": "common"},
        "result_mode": {"node": "103", "field": "value", "type": "select", "label": "结果模式", "default": "three", "options": ["one", "two", "three"], "group": "common"},
        "steps": {"node": "104", "field": "steps", "type": "int", "label": "步数", "default": 20, "min": 1, "max": 60, "group": "advanced"},
        "denoise": {"node": "105", "field": "denoise", "type": "float", "label": "重绘幅度", "default": 0.55, "min": 0, "max": 1, "group": "advanced"},
    },
    "params_defaults": {},
}
server_module.WORKFLOWS = {**server_module.WORKFLOWS, fixture["id"]: fixture}
root = Path(tempfile.mkdtemp())
server_module.DATA_DIR = root
server_module.JOBS_DIR = root / "jobs"
server_module.JOBS_DIR.mkdir()
server_module.JOBS_FILE = root / "jobs.json"
server_module.FAVORITES_DIR = root / "favorites"
server_module.FAVORITES_DIR.mkdir()
server_module.FAVORITES_FILE = root / "favorites.json"
server_module._jobs = {}
server_module._favorites = {}
server_module.run_job = lambda job: None

httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
thread = threading.Thread(target=httpd.serve_forever, daemon=True)
thread.start()


def request(method, path, payload=None):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    body = None if payload is None else json.dumps(payload).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    raw = response.read()
    data = json.loads(raw or b"{}")
    status = response.status
    connection.close()
    return status, data


def oversized_request():
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    connection.putrequest("POST", "/api/workflow-generate")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(server_module.MAX_JSON_BYTES + 1))
    connection.endheaders()
    response = connection.getresponse()
    raw = response.read()
    result = response.status, json.loads(raw or b"{}")
    connection.close()
    return result


try:
    status, oversized = oversized_request()
    assert status == 413 and "too large" in oversized["error"], (status, oversized)

    status, workflows = request("GET", "/api/workflows")
    shown = next(item for item in workflows if item["id"] == "fixture_3in1")
    assert status == 200
    assert shown["kind"] == "rh_workflow"
    assert shown["rh_media"] == fixture["rh_media"]
    assert shown["rh_params"] == fixture["rh_params"]
    assert "rh_workflow_id" not in shown

    payload = {
        "workflow": "fixture_3in1",
        "media": {"source_image": "api/input.png", "evil": "drop"},
        "params": {"route_a": False, "result_mode": "two", "steps": "28", "denoise": "0.65", "evil": "drop"},
        "client_request_id": "generic-same",
        "workflowId": "attacker-id",
        "nodeInfoList": [{"nodeId": "999", "fieldName": "evil", "fieldValue": "evil"}],
        "selection_snapshot": {
            "source_page": "attacker-page",
            "workflow": "attacker-workflow",
            "params": {"steps": 28, "evil": "keep-me"},
            "media": {"source_image": "attacker.png", "evil": "keep-me"},
            "media_names": {"source_image": "input.png", "evil": "keep-me"},
            "evil": "keep-me",
        },
    }
    no_request_id = dict(payload)
    no_request_id.pop("client_request_id")
    status, missing_id = request("POST", "/api/workflow-generate", no_request_id)
    assert status == 400 and "client_request_id" in missing_id["error"], (status, missing_id)

    status, first = request("POST", "/api/workflow-generate", payload)
    assert status == 200 and first.get("job_id"), (status, first)
    job = server_module._jobs[first["job_id"]]
    assert job["workflow"] == "fixture_3in1"
    assert job["media"] == {"source_image": "api/input.png"}
    assert job["params"] == {"route_a": False, "result_mode": "two", "steps": 28, "denoise": 0.65}
    assert "workflowId" not in job and "nodeInfoList" not in job
    assert job["selection_snapshot"] == {
        "source_page": "realism",
        "workflow": "fixture_3in1",
        "params": {"route_a": False, "result_mode": "two", "steps": 28, "denoise": 0.65},
        "media": {"source_image": "api/input.png"},
        "media_names": {"source_image": "input.png"},
    }

    status, second = request("POST", "/api/workflow-generate", payload)
    assert status == 200 and second["job_id"] == first["job_id"] and second["deduplicated"] is True

    job["status"] = "done"
    status, missing = request("POST", "/api/workflow-generate", {**payload, "media": {}, "client_request_id": "missing"})
    assert status == 400 and "二次元原图" in missing["error"], (status, missing)

    status, unknown = request("POST", "/api/workflow-generate", {**payload, "workflow": "not-real", "client_request_id": "unknown"})
    assert status == 400 and "unknown workflow" in unknown["error"], (status, unknown)

    real = server_module.WORKFLOWS["realism_3in1"]
    real_media = {key: f"api/{key}.png" for key in real["rh_media"]}
    real_params = {key: row["default"] for key, row in real["rh_params"].items()}
    boolean_false = next(key for key, row in real["rh_params"].items() if row["type"] == "boolean" and row["default"] is False)
    integer_zero = next(key for key, row in real["rh_params"].items() if row["type"] == "int" and row["default"] == 0)
    blank_text = next(key for key, row in real["rh_params"].items() if row["type"] in ("text", "textarea") and row["default"] == "")
    status, real_result = request("POST", "/api/workflow-generate", {
        "workflow": "realism_3in1", "media": real_media, "params": real_params,
        "client_request_id": "real-3in1-http",
        "workflowId": "attacker-id", "nodeInfoList": [{"nodeId": "999"}],
        "selection_snapshot": {"media_names": {key: f"{key}.png" for key in real_media}},
    })
    assert status == 200 and real_result.get("job_id"), (status, real_result)
    real_job = server_module._jobs[real_result["job_id"]]
    assert real_job["workflow"] == "realism_3in1"
    assert real_job["media"] == real_media
    assert set(real_job["params"]) == set(real["rh_params"])
    assert real_job["params"][boolean_false] is False
    assert real_job["params"][integer_zero] == 0
    assert real_job["params"][blank_text] == ""
    assert "workflowId" not in real_job and "nodeInfoList" not in real_job

    print("GENERIC_WORKFLOW_HTTP_OK", {"workflow": job["workflow"], "deduplicated": second["deduplicated"]})
finally:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)
