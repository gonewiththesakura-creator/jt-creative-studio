import copy
import http.client
import json
import time

from test_server_review_regressions import (
    SESSION_ID,
    json_request,
    panel,
    running_server,
    session_cookie,
)


def video_job(panel, job_id, status='done', owner=SESSION_ID, **fields):
    job = {
        'id': job_id, 'style_id': 'video', 'workflow': 'h3_edit_n',
        'wf_name': 'Video editing', 'generation_backend': 'cloud',
        'status': status, 'created': time.time(),
        'request_session_hash': panel._session_hash(owner),
        'media': {'reference_image': 'subject.png', 'source_video': 'movement.mp4'},
        'params': {'prompt': 'Retain the camera movement.'},
        'images': [{'url': 'https://example.test/result.mp4', 'file_type': 'mp4'}],
    }
    job.update(fields)
    panel._jobs[job_id] = job
    return job


def clear(httpd, panel, scope, cookie=None):
    return json_request(httpd, 'POST', '/api/video-clear', {'scope': scope},
                        cookie=cookie or session_cookie(panel))


def test_history_clear_retains_jobs_media_favorites_and_unresolved_work(panel):
    done = video_job(panel, 'completed')
    video_job(panel, 'failed', 'error')
    video_job(panel, 'cancelled', 'cancelled', cancel_requested=True, cancel_confirmed_at=time.time())
    video_job(panel, 'queued', 'queued', video_queued=True, queue_order=0)
    video_job(panel, 'running', 'running', history_cleared=True, task_cleared=True)
    video_job(panel, 'recovering', 'recovering')
    video_job(panel, 'held', 'error', queue_hold=True)
    video_job(panel, 'cancelling', 'error', cancel_requested=True)
    video_job(panel, 'upstream-active', 'error', provider_status='RUNNING')
    video_job(panel, 'other-owner', owner='other-session-1234567890')
    video_job(panel, 'image-task', style_id='sketch', workflow='anima02')
    preserved_ids = set(panel._jobs) - {'completed', 'failed', 'cancelled'}
    preserved = {job_id: copy.deepcopy(panel._jobs[job_id]) for job_id in preserved_ids}
    panel._favorites['favorite'] = {'job_id': done['id'], 'image_url': '/retained.mp4'}
    saved_favorites = copy.deepcopy(panel._favorites)
    output_folder = panel.JOBS_DIR / done['id']
    output_folder.mkdir()
    output = output_folder / 'result.mp4'
    output.write_bytes(b'retained video bytes')
    with running_server(panel) as httpd:
        status, result, _ = clear(httpd, panel, 'history')
        assert status == 200 and result['ok']
        assert set(result['cleared_ids']) == {'completed', 'failed', 'cancelled'}
        status, repeated, _ = clear(httpd, panel, 'history')
        assert status == 200 and repeated['cleared_ids'] == result['cleared_ids']
        status, queue, _ = json_request(httpd, 'GET', '/api/video-queue', cookie=session_cookie(panel))
        assert status == 200
        assert {job['id'] for job in queue['jobs']} == preserved_ids - {'other-owner', 'image-task'}
        status, history, _ = json_request(httpd, 'GET', '/api/jobs?scope=video&limit=30',
                                           cookie=session_cookie(panel))
        assert status == 200
        assert {job['id'] for job in history} == preserved_ids - {'other-owner', 'image-task'}
        status, retained, _ = json_request(httpd, 'GET', '/api/job/completed', cookie=session_cookie(panel))
        assert status == 200 and retained['images'] == done['images']
        assert retained['media'] == done['media'] and retained['gallery_cleared']
    assert {job_id: panel._jobs[job_id] for job_id in preserved_ids} == preserved
    assert panel._favorites == saved_favorites
    assert output.read_bytes() == b'retained video bytes'
    saved = json.loads(panel.JOBS_FILE.read_text(encoding='utf-8'))
    assert set(saved) == set(panel._jobs)
    assert saved['completed']['history_cleared'] and saved['completed']['task_cleared']


def test_gallery_and_errors_clear_only_their_requested_scopes(panel):
    video_job(panel, 'completed')
    video_job(panel, 'failed', 'error')
    video_job(panel, 'cancelled', 'cancelled')
    video_job(panel, 'held', 'error', queue_hold=True)
    with running_server(panel) as httpd:
        status, result, _ = clear(httpd, panel, 'gallery')
        assert status == 200 and result['cleared_ids'] == ['completed']
        status, queue, _ = json_request(httpd, 'GET', '/api/video-queue', cookie=session_cookie(panel))
        completed = next(job for job in queue['jobs'] if job['id'] == 'completed')
        assert status == 200 and completed['gallery_cleared'] is True
        assert not panel._jobs['completed'].get('history_cleared')
        assert not panel._jobs['completed'].get('task_cleared')
        status, history, _ = json_request(httpd, 'GET', '/api/jobs?scope=video', cookie=session_cookie(panel))
        assert status == 200 and {job['id'] for job in history} == set(panel._jobs)
        status, result, _ = clear(httpd, panel, 'errors')
        assert status == 200 and set(result['cleared_ids']) == {'failed', 'cancelled'}
        status, history, _ = json_request(httpd, 'GET', '/api/jobs?scope=video', cookie=session_cookie(panel))
        assert status == 200 and {job['id'] for job in history} == {'completed', 'held'}
    saved = json.loads(panel.JOBS_FILE.read_text(encoding='utf-8'))
    assert saved['completed']['gallery_cleared']
    assert not saved['completed'].get('history_cleared')
    assert saved['failed']['task_cleared'] and saved['cancelled']['history_cleared']
    assert not saved['held'].get('task_cleared')


def test_clear_rejects_missing_session_cross_origin_and_rolls_back_failed_save(panel, monkeypatch):
    video_job(panel, 'completed')
    before = copy.deepcopy(panel._jobs)
    with running_server(panel) as httpd:
        status, _, _ = json_request(httpd, 'POST', '/api/video-clear', {'scope': 'history'})
        assert status == 428
        connection = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=10)
        connection.request('POST', '/api/video-clear', body=json.dumps({'scope': 'history'}),
                           headers={'Content-Type': 'application/json', 'Cookie': session_cookie(panel),
                                    'Origin': 'https://other.example'})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.close()
        status, _, _ = clear(httpd, panel, 'unsupported')
        assert status == 400 and panel._jobs == before

        def failed_save():
            raise OSError('offline simulated disk failure')

        monkeypatch.setattr(panel, 'save_jobs', failed_save)
        status, result, _ = clear(httpd, panel, 'history')
        assert status == 503 and result['error']
    assert panel._jobs == before
    assert not panel.JOBS_FILE.exists()
