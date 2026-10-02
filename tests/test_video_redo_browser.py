import copy

from playwright.sync_api import expect
from test_app_shell import browser, serve_page


def test_completed_redo_keeps_form_and_retries_same_submission(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    requests = serve_page(page, block_scene=True)
    source = dict(
        id='original', workflow='fixture-video', wf_name='Original video',
        status='done', editable=False, media={'source_video': 'source.mp4'},
        params={'prompt': 'Original prompt', 'lora_1_model': 'minimax-n4',
                'lora_1_strength': .7, 'lora_2_model': 'minimax-n2',
                'lora_2_strength': .6, 'lora_3_model': 'none', 'seed': 42},
        images=[{'url': '/result.png', 'file_type': 'image'}],
    )
    original = copy.deepcopy(source)
    jobs = [source, dict(id='waiting', workflow='fixture-video',
                        wf_name='Waiting video', status='queued', editable=True,
                        position=1, queue_revision=0, media={}, params={})]
    posts, held = [], []
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/video-queue', lambda route: route.fulfill(json={
        'jobs': jobs, 'running': 0, 'waiting': len(jobs) - 1, 'limit': 2,
    }))
    page.route('**/api/job/original', lambda route: route.fulfill(json=source))
    page.route('**/result.png', lambda route: route.fulfill(status=204))

    def generate(route):
        posts.append(route.request.post_data_json)
        held.append(route)

    page.route('**/api/video-generate', generate)

    def accept(job_id):
        jobs.append(dict(id=job_id, workflow='fixture-video', status='queued',
                         editable=True, position=len(jobs), queue_revision=0,
                         media=source['media'], params=source['params']))
        held.pop(0).fulfill(json={'job_id': job_id})
        expect(page.locator('#genStatus')).to_contain_text('已加入队列')
        expect(page.locator('[data-job-id="' + job_id + '"]')).to_be_visible()

    try:
        page.goto('http://fixture.test/video')
        queued = page.locator('[data-job-id="waiting"]')
        expect(queued.locator('.task-redo-quick')).to_be_hidden()
        expect(queued.locator('.task-redo')).to_be_hidden()
        page.locator('[data-group="done"] summary').click()
        card = page.locator('[data-job-id="original"]')
        quick = card.locator('.task-redo-quick')
        card.locator('.task-tile').hover()
        expect(quick).to_have_css('opacity', '1')
        expect(quick).to_have_attribute('aria-label', '重做一次')
        expect(quick).to_have_attribute('title', '重做一次（复用素材与配置，更换随机种子）')
        expect(card.locator('.task-redo')).to_be_visible()
        quick_box, tile_box = quick.bounding_box(), card.locator('.task-tile').bounding_box()
        assert quick_box['x'] >= tile_box['x']
        assert quick_box['y'] >= tile_box['y']
        assert quick_box['x'] + quick_box['width'] <= tile_box['x'] + tile_box['width']
        assert quick_box['y'] + quick_box['height'] <= tile_box['y'] + tile_box['height']
        assert quick_box['width'] == 28 and quick_box['height'] == 28
        page.mouse.move(0, 0)
        quick.focus()
        expect(quick).to_have_css('opacity', '1')

        prompt = page.locator('#wfForm textarea').first
        prompt.fill('Unsaved prompt for a different task')
        quick.dblclick()
        expect(quick).to_be_disabled()
        expect(card.locator('.task-redo')).to_be_disabled()
        assert len(posts) == 1
        first_nonce = posts[0]['client_request_id']
        assert posts[0] == {'redo_job_id': 'original', 'client_request_id': first_nonce}
        assert page.evaluate("localStorage.getItem('jt-pending-video-redo-original')") == first_nonce
        expect(prompt).to_have_value('Unsaved prompt for a different task')

        held.pop(0).fulfill(status=503, json={'error': 'Simulated connection failure'})
        expect(quick).to_be_enabled()
        expect(page.locator('#genStatus')).to_contain_text('再次点击会核对同一次提交')
        assert page.evaluate("localStorage.getItem('jt-pending-video-redo-original')") == first_nonce
        card.locator('.task-tile').hover()
        card.locator('.task-redo').click()
        expect(quick).to_be_disabled()
        assert len(posts) == 2 and posts[1] == posts[0]
        accept('redo-one')
        expect(quick).to_be_enabled()
        assert page.evaluate("localStorage.getItem('jt-pending-video-redo-original')") is None

        quick.click()
        expect(quick).to_be_disabled()
        assert len(posts) == 3
        assert posts[2]['redo_job_id'] == 'original'
        assert posts[2]['client_request_id'] != first_nonce
        assert set(posts[2]) == {'redo_job_id', 'client_request_id'}
        accept('redo-two')
        expect(quick).to_be_enabled()
        expect(prompt).to_have_value('Unsaved prompt for a different task')
        assert source == original
        assert not [request for request in requests if request[0] != 'GET']
        assert not errors
        card.locator('.task-tile').hover()
        page.screenshot(path=str(tmp_path / 'completed-redo-desktop.png'), full_page=True)
    finally:
        for route in held:
            route.abort()
        page.close()
