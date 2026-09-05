import http.client
import http.server
import importlib.util
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SPEC = importlib.util.spec_from_file_location("cold_branch_http", ROOT / "server.py")
server_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server_module)

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


def post(payload):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
    body = json.dumps(payload).encode()
    connection.request("POST", "/api/generate", body, {"Content-Type": "application/json"})
    response = connection.getresponse()
    data = json.loads(response.read() or b"{}")
    status = response.status
    connection.close()
    return status, data


try:
    base = {
        "workflow": "anima02",
        "prompt": "adult man, black hair, long coat",
        "negative_prompt": "text, watermark",
        "prompt_mode": "manual",
        "width": 768,
        "height": 1024,
        "batch": 1,
        "hd": 0,
        "seed": 24681357,
        "seed_mode": "fixed",
        "style_id": "cold",
        "mode": "original",
        "sequence_mode": "off",
        "generation_backend": "cloud",
    }

    first = {**base, "style_variant": "style_only", "client_request_id": "cold-style-only"}
    status, response = post(first)
    assert status == 200 and response.get("job_id"), (status, response)
    job = server_module._jobs[response["job_id"]]
    assert job["style_variant"] == "style_only"
    assert job["loras"] == {
        "LORA1": "05_style3_v2_step1600.safetensors",
        "LORA2": "05_style3_v2_step1600.safetensors",
    }
    assert job["lora_strengths"] == {"LORA1": 0.6, "LORA2": 0.0}
    assert job["trigger"] == "jt_style3_v2"

    job["status"] = "done"
    second = {**base, "style_variant": "character_bound", "mode": "character",
              "client_request_id": "cold-character-bound"}
    status, response = post(second)
    assert status == 200 and response.get("job_id"), (status, response)
    bound = server_module._jobs[response["job_id"]]
    assert bound["style_variant"] == "character_bound"
    assert bound["loras"]["LORA2"] == "04_style3_step800.safetensors"
    assert bound["mode"] == "character"

    bound["status"] = "done"
    status, bad = post({**base, "style_variant": "attacker", "client_request_id": "cold-bad"})
    assert status == 400 and bad["error"] == "unknown style_variant", (status, bad)

    status, noncold_bad = post({**base, "style_id": "sketch", "style_variant": "style_only",
                                "client_request_id": "sketch-bad"})
    assert status == 400 and noncold_bad["error"] == "unknown style_variant", (status, noncold_bad)

    print("COLD_STYLE_BRANCH_HTTP_OK", {
        "style_only": job["style_variant"],
        "bound": bound["style_variant"],
        "invalid": status,
    })
finally:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)
