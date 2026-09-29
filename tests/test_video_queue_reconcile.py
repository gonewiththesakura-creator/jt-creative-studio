import time
import pytest
from test_server_review_regressions import panel, PANEL

RUN_JOB = PANEL.run_job


def setup_holds(panel, monkeypatch):
    monkeypatch.setattr(panel, '_queue_hold_check_after', 0)
    monkeypatch.setattr(panel, '_queue_hold_idle_sample', None)
    held = dict(id='held', workflow='h3_edit_n', status='error', queue_hold=True,
                generation_backend='cloud', video_queued=True, submit_started=time.time()-600)
    waiting = dict(id='waiting', workflow='h3_edit_n', status='queued', created=time.time(),
                   generation_backend='cloud', video_queued=True, queue_media_expires=time.time()+3600)
    panel._jobs.update(held=held, waiting=waiting)
    return held, waiting


def test_two_idle_samples_release_only_hold_and_dispatch_waiting(panel, monkeypatch):
    held, waiting = setup_holds(panel, monkeypatch)
    requests=[]
    def query(req, **kw):
        requests.append(req.full_url)
        return {'code':0,'data':{'currentTaskCounts':'0'}}
    monkeypatch.setattr(panel, '_provider_json_request', query)
    panel.reconcile_video_queue_holds()
    assert held['queue_hold'] and waiting['status']=='queued'
    monkeypatch.setattr(panel, '_queue_hold_check_after', 0)
    panel.reconcile_video_queue_holds()
    assert not held['queue_hold'] and held['status']=='error'
    assert waiting['status']=='queued'
    assert all(url.endswith('/uc/openapi/accountStatus') for url in requests)
    panel.dispatch_video_queue()
    assert waiting['status']=='running' and not held.get('rh_task_id')


@pytest.mark.parametrize('response',[{'code':0,'data':{'currentTaskCounts':1}}, {'code':0,'data':{}}, {'code':401}, {'code':0,'data':{'currentTaskCounts':False}}])
def test_uncertain_or_busy_provider_keeps_hold(panel, monkeypatch, response):
    held, _ = setup_holds(panel, monkeypatch)
    monkeypatch.setattr(panel, '_provider_json_request', lambda *a,**kw:response)
    for _ in range(2):
        monkeypatch.setattr(panel, '_queue_hold_check_after', 0)
        panel.reconcile_video_queue_holds()
    assert held['queue_hold']


def test_grace_period_and_failed_persistence_do_not_release(panel, monkeypatch):
    held, _ = setup_holds(panel, monkeypatch)
    held['submit_started']=time.time()
    monkeypatch.setattr(panel, '_provider_json_request', lambda *a,**kw:pytest.fail('too early'))
    panel.reconcile_video_queue_holds()
    held['submit_started']-=600
    monkeypatch.setattr(panel, '_provider_json_request', lambda *a,**kw:{'code':0,'data':{'currentTaskCounts':0}})
    panel.reconcile_video_queue_holds()
    monkeypatch.setattr(panel, '_queue_hold_check_after', 0)
    monkeypatch.setattr(panel, 'save_jobs', lambda: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):panel.reconcile_video_queue_holds()
    assert held['queue_hold']


@pytest.mark.parametrize('kind,hold',[('rejected',False),('unknown',True),('timeout',True)])
def test_submit_failure_classification(panel, monkeypatch, kind, hold):
    job=dict(id='new',workflow='h3_edit_n',generation_backend='cloud',video_queued=True)
    def submit(job,w):
        job['submit_started']=time.time()
        raise {'rejected':panel.ProviderTaskFailed,'unknown':panel.ProviderStateUncertain,'timeout':TimeoutError}[kind]('test')
    monkeypatch.setattr(panel,'rh_run_video',submit)
    RUN_JOB(job)
    assert job['status']=='error' and bool(job.get('queue_hold'))==hold
