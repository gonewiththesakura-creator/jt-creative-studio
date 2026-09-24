import importlib.util
import json
import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dreamapi_native_canary_client", ROOT / "tools" / "dreamapi_native_canary_client.py"
)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)

PREPARE_SPEC = importlib.util.spec_from_file_location(
    "prepare_dreamapi_native_canary", ROOT / "tools" / "prepare_dreamapi_native_canary.py"
)
PREPARE = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_SPEC.loader.exec_module(PREPARE)


def test_canary_uses_one_native_flare_low_portrait_request():
    payload = CANARY.request_payload("native-canary-request")
    assert payload["generation_backend"] == "api"
    assert payload["api_model"] == "gpt-image-2.5-flare"
    assert payload["api_quality"] == "low"
    assert payload["api_ratio"] == "9:16"
    assert payload["batch"] == 1
    assert payload["client_request_id"] == "native-canary-request"


def test_existing_state_refuses_a_second_paid_submit(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    try:
        CANARY.submit_once("http://127.0.0.1:1", state, "native-canary-request")
    except RuntimeError as error:
        assert "never resubmit" in str(error)
    else:
        raise AssertionError("a second paid submit was not rejected")


def test_candidate_overrides_the_legacy_egress_path_and_binds_loopback():
    command = PREPARE.candidate_launch_command(
        "/home/admin/.comfy-panel-canary/20260915T000000Z-0123456789",
        "comfy-panel-canary-20260915t000000z-0123456789",
    )
    assert "PANEL_BIND=127.0.0.1" in command
    assert "DREAMAPI_EGRESS_URL=http://127.0.0.1:8198/dreamapi/images/generations" in command


def test_candidate_key_is_loaded_from_private_env_file_never_command_line():
    root = '/home/admin/.comfy-panel-canary/20260917T000000Z-0123456789'
    command = PREPARE.candidate_launch_command(root, 'fixture', candidate_key=True)
    env = '--property=EnvironmentFile=' + root + '/dreamapi-canary.env'
    assert command.index(env) > command.index('--property=EnvironmentFile=/home/admin/comfy-panel/panel.env')
    assert command.index(env) < command.index('/usr/bin/env')
    assert not any('DREAMAPI_KEY=' in item for item in command)


def test_internal_canary_uses_host_service_without_changing_credentials():
    command = PREPARE.candidate_launch_command('/tmp/candidate', 'fixture',
                                              connection_mode='direct', internal_service=True)
    assert 'DREAMAPI_BASE_URL=http://127.0.0.1:8080/v1' in command
    assert 'DREAMAPI_CONNECTION_MODE=direct' in command
    assert not any('DREAMAPI_KEY=' in item for item in command)


@pytest.mark.parametrize('failure', [None, 'verify', 'rollback'])
def test_internal_switch_rolls_back_under_drain_and_keeps_lock_if_uncertain(monkeypatch, failure):
    import sys
    import types
    spec = importlib.util.spec_from_file_location('internal_switch', ROOT / 'tools/switch_dreamapi_internal.py')
    switch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(switch)
    calls = []
    class Client:
        def close(self): calls.append(('close',))
    def command(client, text):
        import shlex
        if text.startswith('sudo python3 -c '):
            text = shlex.split(text)[3]
        calls.append(('command', text))
        if "'/models'" in text and failure:
            raise RuntimeError('verification failed')
        if "action='rollback'" in text and failure == 'rollback':
            raise RuntimeError('rollback uncertain')
        return '{}'
    names = ['require_public_idle', 'acquire_release_lock', 'release_release_lock',
             'require_persistent_release_drain_contract', 'require_release_start_draining_unset',
             'set_release_start_draining', 'enable_remote_release_drain', 'isolate_watchdog',
             'require_loopback_idle', 'wait_for_loopback_live', 'wait_for_remote_release_drain',
             'require_dreamapi_release_health', 'set_remote_release_drain', 'restore_watchdog_state']
    fake = types.SimpleNamespace(BASE=ROOT, DEPLOY_SSH_KEY_PATH='fixture', PUBLIC_BASE='fixture',
                                 new_release_transaction=lambda: {}, capture_watchdog_state=lambda c: {},
                                 fetch_json=lambda *a: {}, command=command)
    for name in names:
        setattr(fake, name, lambda *a, _name=name, **k: calls.append((_name, *a[1:])))
    monkeypatch.setattr(switch, 'release', fake)
    monkeypatch.setattr(switch, '_connect', lambda *a: Client())
    monkeypatch.setattr(sys, 'argv', ['switch', '--execute'])
    if failure:
        with pytest.raises(RuntimeError): switch.main()
    else:
        switch.main()
    commands = [row[1] for row in calls if row[0] == 'command']
    assert any("action='install'" in c for c in commands)
    assert any(row[0] == 'enable_remote_release_drain' for row in calls)
    assert any("action='rollback'" in c for c in commands) == bool(failure)
    assert any(row[0] == 'release_release_lock' for row in calls) == (failure != 'rollback')
    if failure == 'rollback':
        assert not any(row[:2] == ('set_remote_release_drain', False) for row in calls)


def test_collect_archives_terminal_error_without_polling_or_resubmitting(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"job_id": "known", "cookie": "test", "submit_attempts": 1}), encoding="utf-8")
    calls = []
    def request(base, path, **kwargs):
        calls.append(path)
        return {"id": "known", "status": "error", "error": "provider rejected"}
    monkeypatch.setattr(CANARY, "_json_request", request)
    monkeypatch.setattr(CANARY.time, "sleep", lambda _: pytest.fail("terminal error must not poll"))
    result = tmp_path / "result.json"
    with pytest.raises(RuntimeError, match="provider rejected"):
        CANARY.collect("http://127.0.0.1:1", state, result, tmp_path / "image.png")
    assert calls == ["/api/job/known"]
    assert json.loads(result.read_text(encoding="utf-8"))["submit_attempts"] == 1
