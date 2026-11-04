"""Offline real-browser coverage of restore, edit, and ordinary submission."""
import copy
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_app_shell import browser, serve_page

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source_status', ['done', 'error', 'cancelled'])
@pytest.mark.parametrize('expired', [False, True])
def test_redo_restores_form_without_submitting(browser, tmp_path, source_status, expired):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    requests = serve_page(page, block_scene=True)
    workflow = next(w for w in json.loads((ROOT / 'config.json').read_text(encoding='utf8'))['workflows']
                    if w['id'] == 'h3_edit_n')
    other = dict(id='other-video', kind='video', backend='runninghub', name='Other workflow',
                 rh_media={}, rh_params={'prompt': {'type': 'text', 'default': 'Unsaved'}})
    params = dict(prompt='Original prompt', duration=18, short_edge=512, seed=403030338371891,
                  lora_1_model='minimax-n1', lora_1_strength=.43,
                  lora_2_model='minimax-n3', lora_2_strength=.82,
                  lora_3_model='minimax-n4', lora_3_strength=.67)
    names = {'source_video': 'movement.mp4', 'reference_image': 'subject.png',
             'reference_image_2': 'wardrobe.png', 'reference_image_3': 'lighting.png',
             'reference_image_4': 'details.png'}
    source = dict(id='original', workflow=workflow['id'], wf_name=workflow['name'],
                  status=source_status, editable=False, redoable=True, media=names,
                  prompt=params['prompt'], negative_prompt='text, watermark', params=params,
                  images=[])
    original = copy.deepcopy(source)
    tokens = {key: 'upl_' + key + 'a' * 40 for key in names}
    draft = dict(source, media={key: dict(filename=name, valid=not expired, expired=expired,
                                         token=None if expired else tokens[key], expires=2000000000,
                                         thumbnail='/preview.png') for key, name in names.items()})
    posts, errors, drafts = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/workflows', lambda route: route.fulfill(json=[other, workflow]))
    page.route('**/api/video-queue', lambda route: route.fulfill(json={
        'jobs': [source], 'running': 0, 'waiting': 0, 'limit': 2}))
    page.route('**/api/job/new-job', lambda route: route.fulfill(json=dict(
        id='new-job', status='queued', workflow=workflow['id'], media={}, params={})))
    page.route('**/preview.png', lambda route: route.fulfill(
        body=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082'), content_type='image/png'))

    def restore(route):
        drafts.append(route.request.method)
        route.fulfill(json=draft)

    def generate(route):
        posts.append(route.request.post_data_json)
        route.fulfill(json={'job_id': 'new-job'})

    page.route('**/api/video-redo-draft?job_id=original', restore)
    page.route('**/api/video-generate', generate)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#param_prompt')).to_have_value('Unsaved')
        if source_status == 'done':
            page.locator('[data-group="done"] summary').click()
        card = page.locator('[data-job-id="original"]')
        card.locator('.task-tile').hover()
        quick = card.locator('.task-redo-quick')
        expect(quick).to_have_attribute('title', '重做一次（恢复素材与配置到表单）')
        quick.click()
        expect(page.locator('#genStatus')).to_contain_text('已恢复任务配置')
        assert posts == [] and drafts == ['GET']
        expect(page.locator('#wfSwitch button[data-wf="h3_edit_n"]')).to_have_class('active')
        expect(page.locator('#param_prompt')).to_have_value(params['prompt'])
        expect(page.locator('#param_negative')).to_have_value('text, watermark')
        for key, value in params.items():
            expect(page.locator('#param_' + key)).to_have_value(str(value))
        for key, filename in names.items():
            slot = page.locator('.drop[data-media-key="' + key + '"]')
            expect(slot.locator('.fn')).to_contain_text(filename)
            expect(slot.locator('.fn')).to_contain_text('原素材已过期，请重新上传' if expired else '已上传')
            assert slot.locator('.local-media-preview').count() == (0 if expired else 1)
        # The full action and shortcut share the same restore-only behavior.
        card.locator('.task-tile').hover()
        card.locator('.task-redo').click()
        expect(page.locator('#genStatus')).to_contain_text('已恢复任务配置')
        assert posts == []
        page.locator('#param_prompt').fill('Modified prompt')
        page.locator('#genBtn').click()
        if expired:
            expect(page.locator('#genStatus')).to_contain_text('缺少必传素材')
            assert posts == []
        else:
            expect(page.locator('#genStatus')).to_contain_text('已提交')
            assert len(posts) == 1
            body = posts[0]
            assert 'redo_job_id' not in body
            assert body['workflow'] == workflow['id']
            assert body['prompt'] == body['params']['prompt'] == 'Modified prompt'
            assert body['negative_prompt'] == 'text, watermark'
            assert body['media'] == tokens
            for key, value in params.items():
                if key != 'prompt':
                    assert body['params'][key] == value
        assert source == original
        assert not [r for r in requests if r[0] != 'GET']
        assert not errors
    finally:
        page.close()
