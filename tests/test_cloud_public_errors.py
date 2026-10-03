import json

import pytest

from test_server_review_regressions import panel


@pytest.mark.parametrize("error", [
    "RH submit rejected: " + json.dumps({
        "taskId": "", "status": "", "errorCode": "605",
        "errorMessage": "Your balance is insufficient. Please top up your account. | 您的账户余额不足，请充值。",
        "clientId": "private-account-id",
    }, ensure_ascii=False),
    "RH AI App submit rejected: " + json.dumps({
        "taskId": "", "status": "", "errorCode": "605",
        "errorMessage": "private upstream message https://private.example/api token=private-token",
    }),
    "RH submission rejected: code=605",
])
def test_cloud_balance_rejection_has_a_fixed_public_explanation(panel, error):
    public = panel.public_job_error({
        "id": "200f7525c662", "generation_backend": "cloud",
        "status": "error", "provider_status": "SUBMITTING", "error": error,
    })
    assert "余额不足" in public
    assert "200f7525c662" in public
    for private in ("RH", "RunningHub", "private", "https://", "605", "errorCode"):
        assert private not in public


def test_later_stage_balance_rejection_does_not_deny_the_existing_task(panel):
    public = panel.public_job_error({
        "id": "fixture", "generation_backend": "cloud", "rh_task_id": "private-task",
        "error": "RH submission rejected: code=605",
    })
    assert "余额不足" in public
    assert "后续提交失败" in public
    assert "任务未提交" not in public
    assert "private-task" not in public


@pytest.mark.parametrize("error", [
    'RH submit rejected: {"errorCode": "1605", "errorMessage": "private unknown"}',
    'RH submit rejected for taskId private-task: {"errorCode": "605"}',
    'RH submit rejected: {"errorCode": "605", "status": "QUEUED"}',
    "RH query failed: private unrelated message 605",
])
def test_other_cloud_errors_do_not_claim_an_unsubmitted_balance_rejection(panel, error):
    public = panel.public_job_error({
        "id": "fixture", "generation_backend": "cloud", "error": error,
    })
    assert "任务未提交" not in public
    assert "private" not in public
