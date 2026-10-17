import time
import pytest
from test_server_review_regressions import panel, SESSION_ID, running_server, json_request, session_cookie


def submit(panel, httpd, request='image-edit-test-1'):
    workflow = panel.WORKFLOWS['qwen21_wardrobe']
    media = {key: panel.issue_upload_capability('api/'+key+'.png', workflow['id'], key,
             'image', key+'.png', SESSION_ID) for key in workflow['rh_media']}
    return json_request(httpd, 'POST', '/api/image-edit-generate', {
        'workflow': workflow['id'], 'params': {'prompt': 'change clothing only', 'seed': '23'},
        'media': media, 'client_request_id': request,
        'selection_snapshot': {'media_names': {'person': 'person.png', 'clothing': 'dress.png'}},
    }, cookie=session_cookie(panel))


@pytest.mark.parametrize('terminal', ['done', 'error', 'cancelled'])
def test_image_queue_redo_restores_both_images_prompt_and_settings(panel, terminal):
    with running_server(panel) as httpd:
        status, body, _ = submit(panel, httpd)
        assert status == 200, body
        original = panel._jobs[body['job_id']]
        assert original['style_id'] == 'realism' and original['status'] == 'queued'
        assert original['params']['seed'] == 23
        assert set(original['provider_media']) == {'person', 'clothing'}
        nodes = panel.rh_build_generic_node_info(original, panel.WORKFLOWS[original['workflow']])
        by_node = {row['nodeId']: row['fieldValue'] for row in nodes if row['fieldName']=='image'}
        assert by_node == {'470': 'api/person.png', '475': 'api/clothing.png'}
        original.update(status=terminal, provider_status={'done':'SUCCESS','error':'FAILED','cancelled':'CANCELLED'}[terminal])
        status, result, _ = json_request(httpd, 'POST', '/api/image-edit-generate', {
            'redo_job_id': original['id'], 'client_request_id': 'image-redo-request-1',
        }, cookie=session_cookie(panel))
        assert status == 200, result
        child = panel._jobs[result['job_id']]
        assert child['params']['prompt'] == original['params']['prompt']
        assert child['params']['seed'] != original['params']['seed']
        assert child['provider_media'] == original['provider_media']
        assert child['media'] == original['media']
        assert child['selection_snapshot']['media_names'] == original['selection_snapshot']['media_names']
        assert child['queue_media_expires'] == original['queue_media_expires']
        status, again, _ = json_request(httpd, 'POST', '/api/image-edit-generate', {
            'redo_job_id': original['id'], 'client_request_id': 'image-redo-request-1',
        }, cookie=session_cookie(panel))
        assert status == 200 and again['job_id'] == child['id']
        assert not panel.video_queue_snapshot(SESSION_ID)['jobs']
        assert len(panel.video_queue_snapshot(SESSION_ID, 'realism')['jobs']) == 2
        status, _, _ = json_request(httpd, 'POST', '/api/image-edit-queue', {
            'job_id': child['id'], 'revision': 0, 'action': 'cancel',
        }, cookie=session_cookie(panel, 'other-image-user-1234567890'))
        assert status == 404 and child['status'] == 'queued'
        status, _, _ = json_request(httpd, 'POST', '/api/video-queue', {
            'job_id': child['id'], 'revision': 0, 'action': 'cancel',
        }, cookie=session_cookie(panel))
        assert status == 404 and child['status'] == 'queued'
        panel.edit_video_queue(SESSION_ID, {'job_id':child['id'], 'revision':0, 'action':'cancel'}, 'realism')
        assert child['status'] == 'cancelled'


def test_image_history_cursor_and_clear_keep_waiting_jobs(panel):
    with running_server(panel) as httpd:
        status, body, _ = submit(panel, httpd)
        assert status == 200
        queued = panel._jobs[body['job_id']]
        for i in range(35):
            job = dict(queued, id=f'{i:012x}', status='error', provider_status='FAILED', created=time.time()-100-i)
            panel._jobs[job['id']] = job
        first = panel.scoped_history_jobs(list(panel._jobs.values()), 'realism', limit=20)
        last = first[-1]
        second = panel.scoped_history_jobs(list(panel._jobs.values()), 'realism', limit=20, before=(last['created'], last['id']))
        assert len(first) == 20 and len(second) == 16
        assert not set(j['id'] for j in first) & set(j['id'] for j in second)
        result = panel.clear_video_ui(SESSION_ID, 'errors', 'realism')
        assert len(result['cleared_ids']) == 35
        assert queued['status'] == 'queued' and not queued.get('task_cleared')


def test_image_redo_expired_media_and_running_task_rejected(panel):
    with running_server(panel) as httpd:
        status, body, _ = submit(panel, httpd)
        assert status == 200
        original = panel._jobs[body['job_id']]
        for state, expected in [('running',409), ('done',410)]:
            original.update(status=state, provider_status='RUNNING' if state=='running' else 'SUCCESS', queue_media_expires=0)
            status, _, _ = json_request(httpd, 'POST', '/api/image-edit-generate', {
                'redo_job_id': original['id'], 'client_request_id':'image-invalid-redo-'+state,
            }, cookie=session_cookie(panel))
            assert status == expected
