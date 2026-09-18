#!/usr/bin/env python3
"""Run one fail-closed DreamAPI canary against a loopback panel instance."""

import argparse
import http.cookiejar
import json
import os
import pathlib
import time
import urllib.error
import urllib.request


MODEL = "gpt-image-2.5-flare"
QUALITY = "low"
RATIO = "9:16"
EXPECTED_SIZE = "864x1536"
PROMPT = (
    "Studio portrait photograph of one adult woman, age 25, neutral expression, "
    "simple black shirt, soft daylight, plain gray background, no text, no logo."
)


def request_payload(client_request_id, model=MODEL):
    return {
        "workflow": "anima02",
        "generation_backend": "api",
        "prompt": PROMPT,
        "negative_prompt": "text, logo, watermark",
        "prompt_mode": "manual",
        "batch": 1,
        "hd": 0,
        "seed_mode": "random",
        "style_id": "sketch",
        "mode": "original",
        "api_model": model,
        "api_quality": QUALITY,
        "api_fit": "contain",
        "api_ratio": RATIO,
        "client_request_id": client_request_id,
        "selection_snapshot": {
            "source_page": "creator",
            "generation_backend": "api",
            "api_model": model,
            "api_quality": QUALITY,
            "api_fit": "contain",
            "api_ratio": RATIO,
        },
    }


def _atomic_json(path, value):
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _json_request(base, path, cookie="", method="GET", payload=None, timeout=15):
    headers = {"Accept": "application/json"}
    body = None
    if cookie:
        headers["Cookie"] = cookie
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _new_cookie(base):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(base + "/", timeout=15) as response:
        response.read(1)
    cookie = "; ".join(f"{item.name}={item.value}" for item in jar)
    if not cookie:
        raise RuntimeError("candidate panel did not issue a session cookie")
    return cookie


def _find_existing_job(base, cookie, client_request_id):
    jobs = _json_request(base, "/api/jobs", cookie=cookie)
    matches = [job for job in jobs if job.get("client_request_id") == client_request_id]
    if len(matches) > 1:
        raise RuntimeError("multiple jobs share the canary client_request_id")
    return matches[0] if matches else None


def submit_once(base, state_path, client_request_id, model=MODEL):
    state_path = pathlib.Path(state_path)
    if state_path.exists():
        raise RuntimeError("canary state already exists; use collect, never resubmit")
    cookie = _new_cookie(base)
    state = {
        "phase": "submitting",
        "client_request_id": client_request_id,
        "cookie": cookie,
        "submit_attempts": 1,
        "submitted_at": time.time(),
    }
    _atomic_json(state_path, state)
    response = _json_request(
        base, "/api/generate", cookie=cookie, method="POST",
        payload=request_payload(client_request_id, model), timeout=30,
    )
    job_id = str(response.get("job_id") or "")
    if not job_id:
        raise RuntimeError("candidate panel did not return a job id")
    state.update({"phase": "accepted", "job_id": job_id, "accepted_at": time.time()})
    _atomic_json(state_path, state)
    return state


def collect(base, state_path, result_path, image_path, timeout=660):
    state_path = pathlib.Path(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    cookie = str(state.get("cookie") or "")
    client_request_id = str(state.get("client_request_id") or "")
    job_id = str(state.get("job_id") or "")
    if not job_id:
        existing = _find_existing_job(base, cookie, client_request_id)
        if not existing:
            raise RuntimeError("submission outcome is uncertain; no retry is permitted")
        job_id = str(existing.get("id") or "")
        state.update({"phase": "accepted", "job_id": job_id, "recovered_by_query": True})
        _atomic_json(state_path, state)
    deadline = time.monotonic() + timeout
    while True:
        job = _json_request(base, "/api/job/" + job_id, cookie=cookie, timeout=15)
        status = str(job.get("status") or "")
        if status in {"done", "error", "failed", "cancelled"}:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("canary job is still running; use collect later, never resubmit")
        time.sleep(2)
    result = {
        "status": status,
        "job": job,
        "client_request_id": client_request_id,
        "submit_attempts": int(state.get("submit_attempts") or 0),
        "submitted_at": state.get("submitted_at"),
        "accepted_at": state.get("accepted_at"),
        "collected_at": time.time(),
    }
    if status != "done":
        _atomic_json(result_path, result)
        raise RuntimeError("DreamAPI canary failed: " + str(job.get("error") or "unknown error"))
    images = job.get("images") or []
    if len(images) != 1 or not str(images[0].get("url") or "").startswith("/api/image/"):
        raise RuntimeError("canary did not expose exactly one local image")
    request = urllib.request.Request(base + images[0]["url"], headers={"Cookie": cookie})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("canary artifact is not a bounded PNG")
    image_path = pathlib.Path(image_path)
    image_path.write_bytes(raw)
    result["artifact_file"] = image_path.name
    result["artifact_bytes"] = len(raw)
    _atomic_json(result_path, result)
    state["phase"] = "collected"
    _atomic_json(state_path, state)
    print(json.dumps({"status": status, "job_id": job_id, "artifact_bytes": len(raw)}))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("submit", "collect"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--client-request-id", required=True)
    parser.add_argument("--model", choices=("gpt-image-2", "gpt-image-2.5-flare"), default=MODEL)
    args = parser.parse_args(argv)
    if args.mode == "submit":
        submit_once(args.base, args.state, args.client_request_id, args.model)
    collect(args.base, args.state, args.result, args.image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
