import time
import pytest
from test_server_review_regressions import panel, PANEL, SESSION_ID
from test_video_queue import enqueue

RUN_JOB=PANEL.run_job


def active_job(panel):
    jid=enqueue(panel,1)[0]
    job=panel._jobs[jid]
    job.update(status='running',rh_task_id='provider-123')
    return job


def request_cancel(panel,job,owner=SESSION_ID):
    panel.edit_video_queue(owner,dict(job_id=job['id'],revision=job['queue_revision'],action='cancel_running'))


def test_cancel_is_owned_durable_idempotent_and_keeps_slot(panel,monkeypatch):
    job=active_job(panel)
    with pytest.raises(LookupError):request_cancel(panel,job,'someone-else')
    original_save=panel.save_jobs
    monkeypatch.setattr(panel,'save_jobs',lambda:(_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):request_cancel(panel,job)
    assert not job.get('cancel_requested')
    monkeypatch.setattr(panel,'save_jobs',original_save)
    request_cancel(panel,job);revision=job['queue_revision'];request_cancel(panel,job)
    assert job['queue_revision']==revision and panel._cloud_slot_used(job)
    panel.load_jobs();restored=panel._jobs[job['id']]
    assert restored['cancel_requested'] and restored['rh_task_id']=='provider-123' and restored['status']=='recovering'
    assert panel.video_queue_snapshot(SESSION_ID)['jobs'][0]['cancellable']


@pytest.mark.parametrize('reply',[{'code':0},{'code':807},TimeoutError('offline')])
def test_cancel_ack_rejection_or_timeout_never_releases_without_status(panel,monkeypatch,reply):
    job=active_job(panel);request_cancel(panel,job);calls=[]
    def provider(req,**kw):
        calls.append(req.full_url)
        if isinstance(reply,Exception):raise reply
        return reply
    monkeypatch.setattr(panel,'_provider_json_request',provider)
    panel._request_provider_cancel(job,'provider-123')
    panel._request_provider_cancel(job,'provider-123')
    assert calls==['https://www.runninghub.ai/task/openapi/cancel']
    assert panel._cloud_slot_used(job) and job['status']=='running'


@pytest.mark.parametrize('resume',[False,True])
def test_confirmed_stop_exits_poll_worker_and_refills_slot(panel,monkeypatch,resume):
    job=active_job(panel);request_cancel(panel,job)
    calls=[]
    def provider(req,**kw):
        calls.append(req.full_url)
        return {'code':0} if req.full_url.endswith('/cancel') else {'status':'CANCELLED'}
    monkeypatch.setattr(panel,'_provider_json_request',provider)
    if resume:panel.resume_cloud_job(job)
    else:
        monkeypatch.setattr(panel,'rh_run_video',lambda j,w:panel._rh_wait_task(j,j['rh_task_id'],time.time()+10))
        RUN_JOB(job)
    assert job['status']=='cancelled' and not panel._cloud_slot_used(job)
    assert job['cancel_confirmed_at'] and len(calls)==2
    waiting=dict(job,id='waiting',status='queued',cancel_requested=False,created=time.time(),queue_media_expires=time.time()+60)
    panel._jobs['waiting']=waiting
    panel.dispatch_video_queue()
    assert waiting['status']=='running'


def test_completion_wins_cancel_race_preserves_result(panel,monkeypatch):
    job=active_job(panel);request_cancel(panel,job)
    def provider(req,**kw):
        return {'code':0} if req.full_url.endswith('/cancel') else {'status':'SUCCESS','results':[{'url':'https://example.com/result.mp4'}]}
    monkeypatch.setattr(panel,'_provider_json_request',provider)
    monkeypatch.setattr(panel,'rh_output_details',lambda tid:[])
    panel.resume_cloud_job(job)
    assert job['status']=='done' and job['images'][0]['url']=='https://example.com/result.mp4'
    with pytest.raises(ValueError):request_cancel(panel,job)


def test_poll_network_error_does_not_release_cancel_pending(panel,monkeypatch):
    job=active_job(panel);request_cancel(panel,job)
    monkeypatch.setattr(panel,'_provider_json_request',lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
    # End only this polling attempt after the failed query, without waiting.
    clock=[1000]
    monkeypatch.setattr(panel.time,'time',lambda:clock[0])
    monkeypatch.setattr(panel.time,'sleep',lambda _:clock.__setitem__(0,1002))
    with pytest.raises(panel.ProviderStateUncertain):panel._rh_wait_task(job,job['rh_task_id'],1001)
    assert job['cancel_requested'] and panel._cloud_slot_used(job)
