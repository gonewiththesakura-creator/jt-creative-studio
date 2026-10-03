import json
import time

import pytest

from test_server_review_regressions import PANEL, panel


RUN_JOB = PANEL.run_job


def video_job(panel, **changes):
    job = {
        'id': 'failure-state', 'workflow': 'h3_edit_n', 'style_id': 'video',
        'generation_backend': 'cloud', 'video_queued': True,
        'status': 'running', 'provider_status': 'RUNNING',
        'rh_task_id': 'known-task', 'submit_started': time.time(),
        'cancel_requested': True,
    }
    job.update(changes)
    panel._jobs[job['id']] = job
    return job


def execute(panel, monkeypatch, job, executor, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(panel, 'rh_run_video', fail)
    monkeypatch.setattr(panel, '_rh_wait_task', fail)
    (RUN_JOB if executor == 'run' else panel.resume_cloud_job)(job)
    saved = json.loads(panel.JOBS_FILE.read_text(encoding='utf-8'))
    assert saved[job['id']] == job


@pytest.mark.parametrize('executor', ['run', 'resume'])
def test_confirmed_provider_failure_is_durably_terminal(panel, monkeypatch, executor):
    job = video_job(panel, queue_hold=True)
    execute(panel, monkeypatch, job, executor,
            panel.ProviderTaskFailed('RH task failed: 805 workflow execution failed'))
    assert job['status'] == 'error' and job['provider_status'] == 'FAILED'
    assert not job['queue_hold']
    assert job['provider_failure_confirmed_at'] > 0 and job['provider_finished'] > 0
    assert panel.video_redoable(job)
    assert not panel._cloud_slot_used(job)


@pytest.mark.parametrize('executor', ['run', 'resume'])
def test_provider_uncertainty_keeps_known_task_recovering(panel, monkeypatch, executor):
    job = video_job(panel)
    recoveries = []
    monkeypatch.setattr(panel, 'schedule_cloud_recovery', lambda j: recoveries.append(j['id']))
    execute(panel, monkeypatch, job, executor, panel.ProviderStateUncertain('query timed out'))
    assert job['status'] == 'recovering' and job['provider_status'] == 'RECOVERING'
    assert job['rh_task_id'] == 'known-task'
    assert 'provider_failure_confirmed_at' not in job
    assert panel._cloud_slot_used(job) and not panel.video_redoable(job)
    assert recoveries == [job['id']]


@pytest.mark.parametrize('executor', ['run', 'resume'])
def test_confirmed_cancellation_stays_cancelled(panel, monkeypatch, executor):
    job = video_job(panel)
    execute(panel, monkeypatch, job, executor, panel.ProviderTaskCancelled('RH_TASK_STOPPED'))
    assert job['status'] == 'cancelled' and job['provider_status'] == 'CANCELLED'
    assert job['cancel_confirmed_at'] > 0 and job['error'] is None
    assert 'provider_failure_confirmed_at' not in job
    assert panel.video_redoable(job)


def test_rh_query_records_failure_before_reading_node_detail(panel, monkeypatch):
    job = video_job(panel)
    monkeypatch.setattr(panel, '_provider_json_request', lambda *a, **kw: {
        'status': 'FAILED', 'errorCode': '805', 'errorMessage': 'workflow execution failed',
    })
    def detail(task_id):
        assert task_id == 'known-task'
        assert job['provider_status'] == 'FAILED' and job['provider_finished'] > 0
        return 'node 42 failed'
    monkeypatch.setattr(panel, 'rh_failed_task_detail', detail)
    with pytest.raises(panel.ProviderTaskFailed, match='node 42 failed'):
        panel.rh_query('known-task', job=job)


def test_ambiguous_create_with_task_id_is_checkpointed_without_resubmitting(panel, monkeypatch):
    job = video_job(panel, provider_status='DISPATCHING', cancel_requested=False)
    job.pop('rh_task_id')
    requests = []
    recoveries = []
    monkeypatch.setattr(panel, 'rh_build_h3_graph', lambda *a: {})
    monkeypatch.setattr(panel, 'rh_build_video_node_info', lambda *a: [])
    def response(req, **kwargs):
        requests.append(req.full_url)
        return {'code': 805, 'data': {'taskId': 'accepted-task'}}
    monkeypatch.setattr(panel, '_provider_json_request', response)
    monkeypatch.setattr(panel, 'schedule_cloud_recovery', lambda j: recoveries.append(j['id']))
    monkeypatch.setattr(panel, '_rh_wait_task', lambda *a, **kw: pytest.fail('ambiguous create must recover'))
    RUN_JOB(job)
    saved = json.loads(panel.JOBS_FILE.read_text(encoding='utf-8'))
    assert saved[job['id']] == job
    assert len(requests) == 1 and requests[0].endswith('/task/openapi/create')
    assert job['rh_task_id'] == 'accepted-task' and job['provider_started'] > 0
    assert job['status'] == 'recovering' and job['provider_status'] == 'RECOVERING'
    assert 'provider_failure_confirmed_at' not in job
    assert recoveries == [job['id']]
    assert not panel.video_redoable(job) and panel._cloud_slot_used(job)


def test_unknown_submit_transport_failure_retains_capacity_reservation(panel, monkeypatch):
    job = video_job(panel, provider_status='SUBMITTING', cancel_requested=False)
    job.pop('rh_task_id')
    execute(panel, monkeypatch, job, 'run', TimeoutError('submit response lost'))
    assert job['status'] == 'error' and job['queue_hold'] is True
    assert 'provider_failure_confirmed_at' not in job
    assert not panel.video_redoable(job) and panel._cloud_slot_used(job)
