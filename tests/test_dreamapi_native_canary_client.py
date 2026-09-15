import importlib.util
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
