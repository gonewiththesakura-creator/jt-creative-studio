import concurrent.futures
import importlib.util
import json
import re
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watchdog_start_is_single_flight(monkeypatch):
    watchdog = load_module("watchdog_single_flight", ROOT / "comfy_watchdog.py")
    watchdog._comfy_start_process = None
    monkeypatch.setattr(watchdog, "comfy_running", lambda: False)
    popen_calls = []
    calls_lock = threading.Lock()

    class RunningProcess:
        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        with calls_lock:
            popen_calls.append((args, kwargs))
        return RunningProcess()

    monkeypatch.setattr(watchdog.subprocess, "Popen", fake_popen)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: watchdog.start_comfy(), range(16)))

    assert results == ["starting"] * 16
    assert len(popen_calls) == 1


def test_watchdog_tunnel_is_noninteractive_and_configurable(monkeypatch):
    monkeypatch.setenv("COMFY_PANEL_SSH_SERVER", "panel@example.invalid")
    monkeypatch.setenv("COMFY_PANEL_SSH_PORT", "49222")
    watchdog = load_module("watchdog_tunnel_options", ROOT / "comfy_watchdog.py")
    command = watchdog.tunnel_command()

    assert command[-1] == "panel@example.invalid"
    assert command[command.index("-p") + 1] == "49222"
    assert "BatchMode=yes" in command
    assert "ConnectTimeout=10" in command
    assert "ExitOnForwardFailure=yes" in command


CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SERVER = load_module("video_boundary_server", ROOT / "server.py")
VIDEO_WORKFLOWS = [
    workflow for workflow in CONFIG["workflows"]
    if workflow.get("kind") == "video" and workflow.get("backend") == "runninghub"
]
BOUNDED_KEYS = {"width", "height", "duration", "short_edge", "long_edge", "max_side"}


def numeric_controls(workflow):
    for key, mapping in workflow.get("rh_params", {}).items():
        control_type = mapping.get("vtype", mapping.get("type"))
        if control_type in {"int", "integer", "float", "number"}:
            yield key, mapping


def test_all_public_runninghub_video_dimensions_and_durations_are_bounded():
    assert VIDEO_WORKFLOWS
    for workflow in VIDEO_WORKFLOWS:
        for key, mapping in numeric_controls(workflow):
            assert {"min", "max", "step"} <= mapping.keys(), (workflow["id"], key)
            assert mapping["min"] <= mapping["max"], (workflow["id"], key)
            assert mapping["step"] > 0, (workflow["id"], key)
            default = mapping.get("default", workflow.get("params_defaults", {}).get(key))
            assert default is not None, (workflow["id"], key)
            assert mapping["min"] <= default <= mapping["max"], (workflow["id"], key)


@pytest.mark.parametrize(
    "workflow,key",
    [
        (workflow, key)
        for workflow in VIDEO_WORKFLOWS
        for key, _ in numeric_controls(workflow)
    ],
    ids=lambda value: value.get("id", "") if isinstance(value, dict) else value,
)
def test_video_boundaries_are_enforced_before_provider_submit(workflow, key):
    media = {
        name: f"api/{name}.{'mp4' if mapping.get('type') == 'video' else 'png'}"
        for name, mapping in workflow.get("rh_media", {}).items()
        if mapping.get("required")
    }
    mapping = workflow["rh_params"][key]
    defaults = workflow.get("params_defaults", {})
    params = {
        name: control.get("default", defaults.get(name))
        for name, control in workflow.get("rh_params", {}).items()
        if "default" in control or name in defaults
    }
    label = str(mapping.get("label") or mapping.get("field") or "参数")

    with pytest.raises(ValueError, match=re.escape(f"{label}超过最大值")):
        SERVER.normalize_rh_workflow_inputs(
            workflow,
            media,
            {**params, key: mapping["max"] + mapping["step"]},
        )
    with pytest.raises(ValueError, match=re.escape(f"{label}低于最小值")):
        SERVER.normalize_rh_workflow_inputs(
            workflow,
            media,
            {**params, key: mapping["min"] - mapping["step"]},
        )
