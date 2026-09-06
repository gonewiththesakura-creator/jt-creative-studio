import ast
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SCRIPT = ROOT / "tools" / "verify_private_realism_runninghub.py"
TEXT = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)


def test_verifier_checkpoints_task_id_before_polling():
    assert 'task_id = record.get("taskId")' in TEXT
    assert 'if not task_id:' in TEXT
    assert 'record.update({"taskId": task_id' in TEXT
    assert 'save(state)' in TEXT
    assert '"urls": urls' in TEXT


def test_ambiguous_submit_state_is_fail_closed_on_resume():
    assert 'if record.get("status") == "SUBMIT_OUTCOME_UNKNOWN":' in TEXT
    assert "manual provider check required" in TEXT


def test_explicit_provider_validation_failure_is_not_ambiguous():
    assert '"VALIDATION_FAILED"' in TEXT
    assert 'result.get("errorCode")' in TEXT
    assert 'if not task_id:' in TEXT


def test_launcher_runs_only_the_six_workflows_after_krea_smoke():
    launcher = (ROOT / "tools" / "launch_private_realism_verifier.py").read_text(encoding="utf-8")
    expected = [
        "realism_2511", "realism_multisample", "realism_qwen_zi",
        "realism_4k_text", "realism_3in1", "realism_zi_flowmatch",
    ]
    assert all(f'"{item}"' in launcher for item in expected)
    order_block = launcher.split("ORDER = [", 1)[1].split("]", 1)[0]
    assert "realism_krea2" not in order_block
    assert '"instance_type": workflow.get("rh_instance_type", "default")' in launcher
    assert 'item.get("instance_type", "default")' in TEXT


def test_verifier_never_logs_or_persists_api_key():
    assert 'KEY = os.environ["RUNNINGHUB_API_KEY"]' in TEXT
    assert 'Authorization' in TEXT
    assert 'print(KEY)' not in TEXT
    assert 'state["apiKey"]' not in TEXT
    assert 'record["apiKey"]' not in TEXT
    assert "STATE.write_text" not in TEXT
