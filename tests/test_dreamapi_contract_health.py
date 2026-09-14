import hashlib
import http.client
import http.server
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONTRACT_SHA256 = "665d283bd420f76f031d9530f1d757f022d6cc16a5c9e9bc315e4966da797959"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_contract_document():
    standard_instructions = (
        "You are an image generation dispatcher. Call the provided image_generation "
        "tool exactly once. Do not return or rewrite a prompt. Return no text."
    )
    strict_instructions = standard_instructions.replace(". Call the", ". You must call the", 1)
    common = ["auto", "high", "low", "medium"]
    extended = ["auto", "high", "low", "max", "medium", "xhigh"]
    return {
        "contract_version": 2,
        "dispatcher": {
            "instructions_by_image_model": {
                "gpt-image-2": standard_instructions,
                "gpt-image-2.5-flare": standard_instructions,
                "gpt-image-2.5-sunburst": strict_instructions,
            },
            "model": "gpt-5.6-luna",
            "stream": False,
        },
        "image_tool": {
            "models": {
                "gpt-image-2": {"action": "omitted", "qualities": common},
                "gpt-image-2.5-flare": {"action": "generate", "qualities": extended},
                "gpt-image-2.5-sunburst": {"action": "generate", "qualities": extended},
            },
            "sizes": ["1024x1024", "1024x1536", "1536x1024", "1536x864", "864x1536"],
            "type": "image_generation",
        },
        "request_keys": ["input", "instructions", "model", "stream", "tools"],
        "runtime_safety": {
            "kill_worker_on_parent_exit": True,
            "persistent_uncertainty_fence": True,
        },
        "tool_count": 1,
    }


def test_server_and_watchdog_compute_the_reviewed_contract_hash():
    server = load_module("dreamapi_contract_server", ROOT / "server.py")
    watchdog = load_module("dreamapi_contract_watchdog", ROOT / "comfy_watchdog.py")
    expected = expected_contract_document()
    canonical = json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")

    assert hashlib.sha256(canonical).hexdigest() == EXPECTED_CONTRACT_SHA256
    assert server._dreamapi_contract_document() == expected
    assert watchdog._dreamapi_contract_document() == expected
    assert server.DREAMAPI_CONTRACT_SHA256 == EXPECTED_CONTRACT_SHA256
    assert watchdog.DREAMAPI_CONTRACT_SHA256 == EXPECTED_CONTRACT_SHA256
    assert (
        set(server.DREAMAPI_DISPATCH_PROFILE_BY_MODEL)
        == set(server.DREAMAPI_DISPATCH_INSTRUCTIONS_BY_MODEL)
        == set(server.DREAMAPI_IMAGE_QUALITIES)
    )


def test_watchdog_status_and_cli_expose_only_the_public_contract_hash(monkeypatch):
    watchdog = load_module("dreamapi_contract_status", ROOT / "comfy_watchdog.py")
    monkeypatch.setattr(watchdog, "comfy_running", lambda: False)
    monkeypatch.setattr(watchdog, "dreamapi_uncertainty_fence_active", lambda: False)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), watchdog.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        connection.request("GET", "/status")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)

    assert response.status == 200
    assert payload == {
        "comfy_running": False,
        "dreamapi_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "dreamapi_uncertainty_fence": False,
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "comfy_watchdog.py"), "--contract-sha256"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    assert result.stdout.strip() == EXPECTED_CONTRACT_SHA256
    assert result.stderr == ""


def test_configured_workstation_egress_requires_live_matching_status(monkeypatch):
    server = load_module("dreamapi_contract_probe", ROOT / "server.py")
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "http://127.0.0.1:8198/dreamapi/responses")
    monkeypatch.setattr(server, "CONTROL_URL", "http://127.0.0.1:8198")
    calls = []

    def matching(url, data=None, timeout=300):
        calls.append((url, data, timeout))
        return {
            "dreamapi_contract_sha256": EXPECTED_CONTRACT_SHA256,
            "dreamapi_uncertainty_fence": False,
        }

    monkeypatch.setattr(server, "http_json", matching)
    assert server.dreamapi_workstation_egress_status() == (True, True, False)
    assert calls == [("http://127.0.0.1:8198/status", None, 5)]

    monkeypatch.setattr(
        server, "http_json", lambda *args, **kwargs: {"dreamapi_contract_sha256": "0" * 64},
    )
    assert server.dreamapi_workstation_egress_status() == (False, False, True)

    monkeypatch.setattr(
        server, "http_json",
        lambda *args, **kwargs: {"dreamapi_contract_sha256": EXPECTED_CONTRACT_SHA256},
    )
    assert server.dreamapi_workstation_egress_status() == (False, True, True)

    def unavailable(*args, **kwargs):
        raise OSError("fixture unavailable")

    monkeypatch.setattr(server, "http_json", unavailable)
    assert server.dreamapi_workstation_egress_status() == (False, False, True)

    monkeypatch.setattr(server, "http_json", matching)
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "http://127.0.0.1:8197/dreamapi/responses")
    assert server.dreamapi_workstation_egress_status() == (False, False, False)


def test_unconfigured_workstation_egress_does_not_probe_control(monkeypatch):
    server = load_module("dreamapi_contract_direct", ROOT / "server.py")
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "")
    monkeypatch.setattr(
        server, "http_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )
    assert server.dreamapi_workstation_egress_status() == (False, False, False)


@pytest.mark.parametrize("remote_hash,ready", [
    (EXPECTED_CONTRACT_SHA256, True),
    ("0" * 64, False),
])
def test_api_health_reports_verified_workstation_contract(monkeypatch, remote_hash, ready):
    server = load_module(f"dreamapi_contract_http_{ready}", ROOT / "server.py")
    monkeypatch.setattr(server, "DREAMAPI_KEY", "fixture-secret-never-serialize")
    monkeypatch.setattr(server, "DREAMAPI_EGRESS_URL", "http://127.0.0.1:8198/dreamapi/responses")
    monkeypatch.setattr(server, "CONTROL_URL", "http://127.0.0.1:8198")
    monkeypatch.setattr(server, "comfy_ok", lambda: (True, "ok"))
    monkeypatch.setattr(server, "http_json", lambda *args, **kwargs: {
        "dreamapi_contract_sha256": remote_hash,
        "dreamapi_uncertainty_fence": False,
    })
    monkeypatch.setattr(server, "_jobs", {})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        raw = response.read()
        payload = json.loads(raw)
        connection.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)

    assert response.status == 200
    assert payload["dreamapi_configured"] is True
    assert payload["dreamapi_workstation_egress"] is ready
    assert payload["dreamapi_contract_match"] is ready
    assert payload["dreamapi_contract_sha256"] == EXPECTED_CONTRACT_SHA256
    assert payload["dreamapi_uncertainty_fence"] is False
    assert b"fixture-secret-never-serialize" not in raw


def test_release_acceptance_requires_the_reviewed_runtime_contract():
    deploy = load_module("dreamapi_contract_deploy", ROOT / "tools" / "deploy_realism_release.py")
    ready = {
        "dreamapi_configured": True,
        "dreamapi_workstation_egress": True,
        "dreamapi_contract_match": True,
        "dreamapi_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "dreamapi_uncertainty_fence": False,
    }
    assert deploy.require_dreamapi_release_health(ready) is ready
    assert deploy.DREAMAPI_CONTRACT_SHA256 == EXPECTED_CONTRACT_SHA256

    for field in (
        "dreamapi_configured", "dreamapi_workstation_egress", "dreamapi_contract_match",
    ):
        drifted = dict(ready)
        drifted[field] = False
        with pytest.raises(RuntimeError, match="not ready"):
            deploy.require_dreamapi_release_health(drifted)
    drifted = dict(ready, dreamapi_contract_sha256="0" * 64)
    with pytest.raises(RuntimeError, match="hash"):
        deploy.require_dreamapi_release_health(drifted)
    for value in (True, None):
        drifted = dict(ready, dreamapi_uncertainty_fence=value)
        with pytest.raises(RuntimeError, match="uncertain"):
            deploy.require_dreamapi_release_health(drifted)

    source = (ROOT / "tools" / "deploy_realism_release.py").read_text(encoding="utf-8")
    deploy_body = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert 'fetch_json(public_base, "/api/health")' in deploy_body
    assert "require_dreamapi_release_health" in deploy_body
    assert deploy_body.index("require_dreamapi_release_health") < deploy_body.index(
        'write_transaction_phase(client, transaction, "committed")'
    )


def test_double_click_helper_scopes_process_reuse_and_cleanup_to_exact_contracts():
    helper = (ROOT / "tools" / "start_comfy_watchdog.ps1").read_text(encoding="utf-8")
    launcher = (ROOT / "\u542f\u52a8\u9762\u677f.bat").read_text(encoding="utf-8")

    for marker in (
        "CommandLineToArgvW", "Test-ExactCommandLine", "Get-ExactWatchdogs",
        "Get-ExactDreamApiWorkers", "DreamAPI paid worker is active",
        "Get-ProjectTunnelArguments", "Get-ProjectTunnels",
        "8199:127.0.0.1:8188", "8198:127.0.0.1:8198",
        "BatchMode=yes", "ExitOnForwardFailure=yes", "admin@8.210.125.65",
        "--contract-sha256", "Get-WatchdogStatusHash", "-WindowStyle Hidden",
    ):
        assert marker in helper
    assert 'Stop-ExactProcesses $watchdogs "Outdated watchdog" `' in helper
    assert 'Stop-ExactProcesses @(Get-ProjectTunnels $sshExecutable $sshKey) `' in helper
    assert 'Stop-ExactProcesses @($started) "Failed watchdog startup" `' in helper
    assert "$watchdogs = @(Get-ExactWatchdogs $PythonwPath $WatchdogScript)" in helper
    assert "Stop-Process -Name" not in helper
    assert "taskkill" not in helper.lower()
    assert "start_comfy_watchdog.ps1" in launcher
    assert "pythonw.exe\" \"D:" not in launcher


def test_double_click_helper_revalidates_pid_identity_immediately_before_stop():
    helper = (ROOT / "tools" / "start_comfy_watchdog.ps1").read_text(encoding="utf-8")
    stop_body = helper.split("function Stop-ExactProcesses(", 1)[1].split(
        "$PythonwPath = Resolve-RequiredFile", 1
    )[0]

    lookup = 'Get-CimInstance Win32_Process `\n            -Filter "ProcessId = $candidateProcessId"'
    exact_match = "Test-ExactCommandLine $current[0] $ExpectedExecutable"
    stop = "Stop-Process -Id $candidateProcessId"
    assert lookup in stop_body
    assert exact_match in stop_body
    assert stop in stop_body
    assert stop_body.index(lookup) < stop_body.index(exact_match) < stop_body.index(stop)
    assert "$current.Count -eq 0" in stop_body
    assert "$current.Count -ne 1" in stop_body
    assert "identity changed" in stop_body
    assert helper.count("Stop-Process") == 1


def test_double_click_helper_skips_reused_or_exited_pid_at_stop_time():
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is required for the launcher behavior test")

    helper = (ROOT / "tools" / "start_comfy_watchdog.ps1").read_text(encoding="utf-8")
    stop_function = "function Stop-ExactProcesses(" + helper.split(
        "function Stop-ExactProcesses(", 1
    )[1].split("$PythonwPath = Resolve-RequiredFile", 1)[0]
    harness = r'''
$script:mode = "match"
$script:filters = [System.Collections.Generic.List[string]]::new()
$script:stopped = [System.Collections.Generic.List[int]]::new()
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [object]$ErrorAction)
    $script:filters.Add($Filter)
    if ($script:mode -eq "exited") { return }
    $queriedId = [int]($Filter -replace '^ProcessId = ', '')
    return [pscustomobject]@{ ProcessId = $queriedId; Marker = $script:mode }
}
function Test-ExactCommandLine {
    param($Process, $ExpectedExecutable, $ExpectedArguments, $PathArgumentIndexes)
    return $Process.Marker -eq "match"
}
function Stop-Process {
    param([int]$Id, [switch]$Force, [object]$ErrorAction)
    $script:stopped.Add($Id)
}
$stale = [pscustomobject]@{ ProcessId = 41; Marker = "stale-enumeration" }
Stop-ExactProcesses @($stale) "test" "pythonw.exe" @("watchdog.py") @(0, 1) > $null
$dotnetShape = [pscustomobject]@{ Id = 42 }
Stop-ExactProcesses @($dotnetShape) "test" "pythonw.exe" @("watchdog.py") @(0, 1) > $null
$script:mode = "reused"
Stop-ExactProcesses @($stale) "test" "pythonw.exe" @("watchdog.py") @(0, 1) > $null
$script:mode = "exited"
Stop-ExactProcesses @($stale) "test" "pythonw.exe" @("watchdog.py") @(0, 1) > $null
[pscustomobject]@{
    filters = @($script:filters)
    stopped = @($script:stopped)
} | ConvertTo-Json -Compress
'''
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", stop_function + harness],
        capture_output=True,
        check=True,
        text=True,
        timeout=15,
    )
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "filters": ["ProcessId = 41", "ProcessId = 42", "ProcessId = 41", "ProcessId = 41"],
        "stopped": [41, 42],
    }


def test_watchdog_launcher_resolves_defaults_after_parameter_binding(tmp_path):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is required for the launcher behavior test")

    missing_pythonw = tmp_path / "missing-pythonw.exe"
    result = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-File",
            str(ROOT / "tools" / "start_comfy_watchdog.ps1"),
            "-PythonwPath", str(missing_pythonw),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Embedded pythonw is missing" in combined
    assert "Cannot bind argument to parameter 'Path'" not in combined
