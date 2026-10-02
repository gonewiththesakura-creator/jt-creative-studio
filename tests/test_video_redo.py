import copy
import time

import pytest

from test_server_review_regressions import (
    SESSION_ID,
    json_request,
    panel,
    running_server,
    session_cookie,
)


def completed_video(panel):
    workflow = panel.WORKFLOWS['h3_edit_n']
    media = {
        'reference_image': 'subject.png',
        'reference_image_2': 'wardrobe.png',
        'reference_image_3': 'lighting.png',
        'reference_image_4': 'details.png',
        'source_video': 'movement.mp4',
    }
    params = {
        'prompt': 'Preserve the camera and motion; change only the wardrobe.',
        'duration': 18,
        'short_edge': 512,
        'seed': 403030338371891,
        'lora_1_model': 'minimax-n1',
        'lora_1_strength': .43,
        'lora_2_model': 'minimax-n3',
        'lora_2_strength': .82,
        'lora_3_model': 'minimax-n4',
        'lora_3_strength': .67,
    }
    _, params = panel.normalize_rh_workflow_inputs(workflow, media, params)
    job = {
        'id': 'aabbcc123456',
        'workflow': workflow['id'],
        'wf_name': workflow['name'],
        'style_id': 'video',
        'generation_backend': 'cloud',
        'status': 'done',
        'created': time.time() - 100,
        'prompt': params['prompt'],
        'negative_prompt': 'text, watermark',
        'params': params,
        'media': media,
        'provider_media': {key: 'api/' + name for key, name in media.items()},
        'queue_media_expires': time.time() + 3600,
        'request_session_hash': panel._session_hash(SESSION_ID),
        'input_thumbnails': {'source_video': 'b' * 32},
        'images': [{'url': 'https://example.test/finished.mp4', 'file_type': 'mp4'}],
        'selection_snapshot': panel.upload_bound_snapshot(
            workflow, media, params, {'media_names': media}, 'video'),
    }
    panel._jobs[job['id']] = job
    return job


def redo(httpd, panel, original, request_id, **overrides):
    body = {'redo_job_id': original['id'], 'client_request_id': request_id}
    body.update(overrides)
    return json_request(httpd, 'POST', '/api/video-generate', body,
                        cookie=session_cookie(panel))


@pytest.mark.parametrize('original_status', ['done', 'error', 'cancelled'])
def test_redo_uses_saved_inputs_new_seed_and_deduplicates_retry(panel, original_status):
    original = completed_video(panel)
    original['status'] = original_status
    if original_status != 'done':
        original['images'] = []
    if original_status == 'error':
        original.update(error='Provider execution failed', provider_status='FAILED')
    elif original_status == 'cancelled':
        original.update(provider_status='CANCELLED', cancel_requested=True,
                        cancel_confirmed_at=time.time())
    before = copy.deepcopy(original)
    with running_server(panel) as httpd:
        status, queue, _ = json_request(httpd, 'GET', '/api/video-queue',
                                        cookie=session_cookie(panel))
        assert status == 200 and queue['jobs'][0]['redoable'] is True
        status, saved, _ = json_request(httpd, 'GET', '/api/job/' + original['id'],
                                        cookie=session_cookie(panel))
        assert status == 200 and saved['redoable'] is True
        status, first, _ = redo(
            httpd, panel, original, 'redo-first',
            prompt='browser override', workflow='h3_t2v_i2v',
            params={'lora_1_model': 'none', 'duration': 4},
            media={'source_video': 'untrusted.mp4'})
        assert status == 200, first
        status, duplicate, _ = redo(httpd, panel, original, 'redo-first')
        assert status == 200 and duplicate['deduplicated']
        assert duplicate['job_id'] == first['job_id']
        status, second, _ = redo(httpd, panel, original, 'redo-second')
        assert status == 200, second
        assert second['job_id'] != first['job_id']
    assert original == before
    assert len(panel._jobs) == 3
    children = [panel._jobs[result['job_id']] for result in (first, second)]
    assert children[0]['params']['seed'] != children[1]['params']['seed']
    for child in children:
        assert child['status'] == 'queued' and child['video_queued']
        assert child['redo_of'] == original['id']
        assert child['workflow'] == original['workflow']
        assert child['prompt'] == original['prompt']
        assert child['negative_prompt'] == original['negative_prompt']
        assert child['media'] == original['media']
        assert child['provider_media'] == original['provider_media']
        assert child['queue_media_expires'] == original['queue_media_expires']
        assert child['input_thumbnails'] == original['input_thumbnails']
        assert child['input_thumbnails'] is not original['input_thumbnails']
        assert child['params'] is not original['params']
        assert {key: value for key, value in child['params'].items() if key != 'seed'} == {
            key: value for key, value in original['params'].items() if key != 'seed'}
        assert child['params']['seed'] != original['params']['seed']
        assert 0 <= child['params']['seed'] <= 2**50
        assert child['selection_snapshot']['params'] == child['params']
        assert panel.public_video_thumbnails(child)['source_video'] == (
            '/api/video-thumbnail/' + original['id'] + '/' + 'b' * 32 + '.jpg')
    assert children[0]['queue_order'] < children[1]['queue_order']
    panel.load_jobs()
    assert panel._jobs[first['job_id']]['params'] == children[0]['params']
    assert panel._jobs[original['id']] == before


def test_expired_inputs_reject_new_redo_but_allow_accepted_retry(panel):
    original = completed_video(panel)
    with running_server(panel) as httpd:
        status, accepted, _ = redo(httpd, panel, original, 'redo-before-expiry')
        assert status == 200, accepted
        original['queue_media_expires'] = time.time() - 1
        status, duplicate, _ = redo(httpd, panel, original, 'redo-before-expiry')
        assert status == 200 and duplicate['deduplicated']
        assert duplicate['job_id'] == accepted['job_id']
        status, rejected, _ = redo(httpd, panel, original, 'redo-after-expiry')
        assert status == 410 and rejected['error']
    assert len(panel._jobs) == 2


def test_redo_requires_owned_finished_video_and_required_media(panel):
    original = completed_video(panel)
    before = copy.deepcopy(original)
    with running_server(panel) as httpd:
        status, _, _ = json_request(
            httpd, 'POST', '/api/video-generate',
            {'redo_job_id': original['id'], 'client_request_id': 'redo-other-owner'},
            cookie=session_cookie(panel, 'other-session-1234567890'))
        assert status == 404
        unresolved_states = (
            {'status': 'queued'},
            {'status': 'running'},
            {'status': 'recovering'},
            {'status': 'error', 'queue_hold': True},
            {'status': 'error', 'cancel_requested': True},
            {'status': 'error', 'provider_status': 'RUNNING'},
            {'status': 'error', 'provider_status': 'SUBMITTING'},
        )
        for index, changes in enumerate(unresolved_states):
            original.clear(); original.update(copy.deepcopy(before)); original.update(changes)
            status, queue, _ = json_request(httpd, 'GET', '/api/video-queue',
                                            cookie=session_cookie(panel))
            assert status == 200 and queue['jobs'][0]['redoable'] is False
            status, rejected, _ = redo(httpd, panel, original, 'redo-unresolved-' + str(index))
            assert status == 409 and '暂不能重做' in rejected['error']
        original.clear(); original.update(copy.deepcopy(before))
        for key in ('provider_media', 'media'):
            saved = original[key].pop('source_video')
            status, _, _ = redo(httpd, panel, original, 'redo-missing-' + key)
            assert status == 400
            original[key]['source_video'] = saved
    assert list(panel._jobs) == [original['id']]
    assert original == before


@pytest.mark.parametrize('limit_name', ['VIDEO_QUEUE_LIMIT', 'VIDEO_QUEUE_SESSION_LIMIT'])
def test_redo_queue_limit_does_not_change_original_or_accept_another_job(
        panel, monkeypatch, limit_name):
    original = completed_video(panel)
    before = copy.deepcopy(original)
    monkeypatch.setattr(panel, limit_name, 1)
    with running_server(panel) as httpd:
        status, accepted, _ = redo(httpd, panel, original, 'redo-fills-queue')
        assert status == 200, accepted
        status, rejected, _ = redo(httpd, panel, original, 'redo-full-queue')
        assert status == 429 and rejected['error']
        status, duplicate, _ = redo(httpd, panel, original, 'redo-fills-queue')
        assert status == 200 and duplicate['deduplicated']
        assert duplicate['job_id'] == accepted['job_id']
    assert original == before
    assert len(panel._jobs) == 2
