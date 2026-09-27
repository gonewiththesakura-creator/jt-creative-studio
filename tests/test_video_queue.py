import time
import threading
import pytest
from test_server_review_regressions import panel, SESSION_ID, running_server, json_request, session_cookie


def enqueue(panel, count=3):
    ids = []
    with running_server(panel) as httpd:
        for i in range(count):
            status, body, _ = json_request(httpd, 'POST', '/api/video-generate', {
                'workflow': 'h3_t2v_i2v', 'prompt': 'slow camera', 'media': {},
                'params': {}, 'client_request_id': 'queue-test-'+str(i),
            }, cookie=session_cookie(panel))
            assert status == 200, body
            ids.append(body['job_id'])
    return ids


def test_slots_refill_without_duplicate_submit_and_survive_restart(panel, monkeypatch):
    ids = enqueue(panel, 4)
    starts = []
    monkeypatch.setattr(panel, 'run_job', lambda j: starts.append(j['id']))
    panel.load_jobs()
    assert all(panel._jobs[k]['status'] == 'queued' for k in ids)
    threads = [threading.Thread(target=panel.dispatch_video_queue) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert starts == ids[:2]
    panel._jobs[ids[0]]['status'] = 'done'
    panel.dispatch_video_queue()
    for _ in range(100):
        if len(starts) == 3: break
        time.sleep(.01)
    assert starts == ids[:3]
    panel.save_jobs()
    panel.load_jobs()
    assert panel._jobs[ids[1]]['queue_hold']
    panel.dispatch_video_queue()
    assert panel._jobs[ids[3]]['status'] == 'queued'


def test_owner_reorder_cancel_edit_revision_and_dispatch_race(panel):
    ids = enqueue(panel)
    def act(i, action, **kw):
        j = panel._jobs[ids[i]]
        panel.edit_video_queue(SESSION_ID, dict(job_id=j['id'], revision=j['queue_revision'], action=action, **kw))
    with pytest.raises(LookupError):
        panel.edit_video_queue('other-session', dict(job_id=ids[0], revision=0, action='cancel'))
    act(2, 'top')
    assert [j['id'] for j in panel._video_waiting()] == [ids[2], ids[0], ids[1]]
    with pytest.raises(ValueError):
        panel.edit_video_queue(SESSION_ID, dict(job_id=ids[0], revision=0, action='cancel'))
    act(2, 'down')
    act(1, 'up')
    act(0, 'edit', params={'prompt': 'new camera'})
    assert panel._jobs[ids[0]]['prompt'] == 'new camera'
    act(1, 'cancel')
    assert panel._jobs[ids[1]]['status'] == 'cancelled'
    panel.dispatch_video_queue()
    with pytest.raises(ValueError): act(0, 'cancel')
    assert panel.video_queue_snapshot('other-session')['jobs'] == []
    assert len(panel.video_queue_snapshot(SESSION_ID)['jobs']) == 3


def test_drain_expiry_and_http_ownership(panel):
    ids = enqueue(panel)
    panel._release_draining = True
    panel.dispatch_video_queue()
    assert all(panel._jobs[k]['status'] == 'queued' for k in ids)
    panel._release_draining = False
    panel._jobs[ids[0]]['queue_media_expires'] = 0
    panel.dispatch_video_queue()
    assert panel._jobs[ids[0]]['provider_status'] == 'QUEUE_EXPIRED'
    with running_server(panel) as httpd:
        status, body, _ = json_request(httpd, 'GET', '/api/video-queue', cookie=session_cookie(panel))
        assert status == 200 and body['running'] == 2
        status, _, _ = json_request(httpd, 'POST', '/api/video-queue', {
            'job_id': ids[0], 'revision': 0, 'action': 'cancel'
        }, cookie=session_cookie(panel, 'other-session-1234567890'))
        assert status == 404


def test_failed_edit_save_does_not_change_queued_job(panel, monkeypatch):
    ids = enqueue(panel, 1)
    def fail(): raise OSError('disk unavailable')
    monkeypatch.setattr(panel, 'save_jobs', fail)
    with pytest.raises(OSError):
        panel.edit_video_queue(SESSION_ID, dict(job_id=ids[0], revision=0, action='cancel'))
    assert panel._jobs[ids[0]]['status'] == 'queued'
    assert panel._jobs[ids[0]]['queue_revision'] == 0
