import base64

from playwright.sync_api import expect

from test_app_shell import browser, serve_page


def media_sample(page):
    return page.evaluate('''async () => {
        const canvas = document.createElement('canvas');
        canvas.width = 320; canvas.height = 180;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#387e9b'; ctx.fillRect(0, 0, 320, 180);
        ctx.fillStyle = '#eed278'; ctx.fillRect(100, 35, 120, 110);
        const png = canvas.toDataURL('image/png').split(',')[1];
        const stream = canvas.captureStream(10);
        const recorder = new MediaRecorder(stream, {mimeType: 'video/webm'});
        const parts = [];
        recorder.ondataavailable = e => parts.push(e.data);
        const stopped = new Promise(resolve => recorder.onstop = resolve);
        recorder.start();
        let frame = 0;
        const animation = setInterval(() => {
            ctx.fillStyle = '#387e9b'; ctx.fillRect(0, 0, 320, 180);
            ctx.fillStyle = '#eed278'; ctx.fillRect(100 + (++frame % 10), 35, 120, 110);
        }, 80);
        await new Promise(resolve => setTimeout(resolve, 500));
        clearInterval(animation);
        recorder.stop(); await stopped;
        stream.getTracks().forEach(track => track.stop());
        const bytes = new Uint8Array(await new Blob(parts).arrayBuffer());
        return {png, video: btoa(String.fromCharCode(...bytes))};
    }''')


def test_favorite_video_details_and_polling_preserve_player(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    requests = serve_page(page, block_scene=True)
    sample = media_sample(page)
    prompt = '保留完整镜头与动作。' * 40 + '最后一段提示词也必须显示'
    favorites = [dict(id='ready', job_id='done', image_index=0,
                      style_id='video', archive_status='ready',
                      favorite_media_type='video/webm', image_url='/api/favorite-image/ready',
                      prompt=prompt, selection_snapshot={'params': {
                          'lora_1_model': 'minimax-n1', 'lora_1_strength': .4,
                          'lora_2_model': 'minimax-n4', 'lora_2_strength': .7,
                          'lora_3_model': 'none', 'lora_3_strength': 0}}),
                 dict(id='pending', job_id='waiting', image_index=0,
                      style_id='video', archive_status='saving')]
    polls = []

    def favorites_response(route):
        polls.append(route.request.method)
        route.fulfill(json=favorites)

    page.route('**/api/favorites', favorites_response)
    page.route('**/api/video-queue', lambda route: route.fulfill(
        json={'jobs': [], 'running': 0, 'waiting': 0, 'limit': 2}))
    page.route('**/api/favorite-image/ready', lambda route: route.fulfill(
        body=base64.b64decode(sample['video']), content_type='video/webm'))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#favOpen').first.click()
        card = page.locator('.favorite-card[data-favorite-id="ready"]')
        video = card.locator('video')
        expect(video).to_have_attribute('preload', 'metadata')
        video.evaluate("el => {el.dataset.retained='yes'; el.loop=true; el.muted=true; return el.play()}")
        expect(video).to_have_js_property('paused', False)
        page.wait_for_function('''() => {
            const video = document.querySelector('.page-host[data-page="/video"]').shadowRoot
                .querySelector('.favorite-card[data-favorite-id="ready"] video');
            return video?.readyState >= 2 && video.currentTime > 0;
        }''')
        assert video.evaluate('''video => {
            const canvas = document.createElement('canvas'); canvas.width=1; canvas.height=1;
            const ctx=canvas.getContext('2d'); ctx.drawImage(video,0,0,1,1);
            return [...ctx.getImageData(0,0,1,1).data].slice(0,3).some(channel=>channel>30);
        }'''), 'Favorite player must decode a visible frame'
        card.locator('.favorite-details summary').click()
        expect(card.locator('.favorite-details')).to_contain_text(prompt)
        expect(card.locator('.favorite-details')).to_contain_text('LoRA 1：dog · 强度 0.4')
        expect(card.locator('.favorite-details')).to_contain_text('LoRA 2：v4 · 强度 0.7')
        expect(card.locator('.favorite-details')).to_contain_text('LoRA 3：不加载')
        expect(page.locator('.favorite-card[data-favorite-id="pending"]')).to_contain_text('后台保存中')
        page.wait_for_timeout(5500)
        assert len(polls) >= 2, 'Pending archives should refresh their status'
        expect(video).to_have_attribute('data-retained', 'yes')
        expect(video).to_have_js_property('paused', False)
        assert card.locator('.favorite-details').evaluate('el => el.open')
        page.screenshot(path=str(tmp_path / 'favorite-library.png'), full_page=True)
        assert not errors
        assert not [request for request in requests if request[0] != 'GET']
    finally:
        page.close()


def test_history_has_loaded_thumbnails_and_complete_configuration(browser, tmp_path):
    page = browser.new_page(viewport={'width': 390, 'height': 900})
    serve_page(page, block_scene=True)
    sample = media_sample(page)
    thumbnail = '/api/video-thumbnail/source/' + 'a' * 32 + '.jpg'
    jobs = [dict(id='done', workflow='fixture-video', wf_name='完成的视频',
                 status='done', created=100, prompt='历史提示词',
                 params={'lora_1_model': 'minimax-n6', 'lora_1_strength': .6},
                 thumbnails={'source_video': thumbnail}, media={'source_video': '已完成素材.webm'}),
            dict(id='queued', workflow='fixture-video', wf_name='排队的视频',
                 status='queued', created=101, prompt='排队提示词', params={},
                 thumbnails={'source_video': thumbnail}, media={'source_video': '排队素材.webm'})]
    page.route('**/api/jobs?*', lambda route: route.fulfill(json=jobs))
    page.route('**/api/video-queue', lambda route: route.fulfill(
        json={'jobs': [], 'running': 0, 'waiting': 0, 'limit': 2}))
    page.route('**' + thumbnail, lambda route: route.fulfill(
        body=base64.b64decode(sample['png']), content_type='image/png'))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#histOpen').first.click()
        cards = page.locator('#histList .history-card')
        expect(cards).to_have_count(2)
        thumbnails = cards.locator('.history-thumbnail img')
        expect(thumbnails).to_have_count(2)
        expect(thumbnails.first).to_have_attribute('loading', 'lazy')
        expect(thumbnails.first).to_have_js_property('naturalWidth', 320)
        expect(cards.first).to_contain_text('已完成素材.webm')
        expect(cards.last).to_contain_text('排队素材.webm')
        expect(cards.last.get_by_role('button', name='播放结果')).to_be_disabled()
        cards.first.locator('details summary').click()
        expect(cards.first.locator('details')).to_contain_text('历史提示词')
        expect(cards.first.locator('details')).to_contain_text('LoRA 1：hp · 强度 0.6')
        assert page.locator('#histList').evaluate('el => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(tmp_path / 'history-thumbnails-mobile.png'), full_page=True)
    finally:
        page.close()


def test_upload_remove_cancel_and_completed_task_navigation(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    serve_page(page, block_scene=True)
    sample = media_sample(page)
    workflow = dict(id='controls', kind='video', name='控件测试',
                    rh_media={'reference_image': dict(type='image', label='参考图', required=True)},
                    rh_params={'prompt': dict(type='text', label='提示词', default='保留镜头')})
    jobs = [dict(id='queued-'+str(i), workflow='controls', status='queued', editable=True,
                 position=i+1, queue_revision=0, params={}) for i in range(24)]
    jobs += [dict(id='done-'+str(i), workflow='controls', status='done', params={},
                  images=[dict(url='/result.webm', file_type='webm')]) for i in range(2)]
    actions, generation = [], []

    def queue_response(route):
        if route.request.method == 'POST':
            body = route.request.post_data_json
            actions.append(body)
            next(job for job in jobs if job['id'] == body['job_id']).update(
                status='cancelled', editable=False)
            return route.fulfill(json={'ok': True})
        route.fulfill(json={'jobs': jobs, 'running': 0, 'waiting': 24, 'limit': 2})

    page.route('**/api/workflows', lambda route: route.fulfill(json=[workflow]))
    page.route('**/api/video-queue', queue_response)
    page.route('**/api/job/*', lambda route: route.fulfill(json=next(
        job for job in jobs if job['id'] == route.request.url.rsplit('/', 1)[-1])))
    page.route('**/result.webm', lambda route: route.fulfill(
        body=base64.b64decode(sample['video']), content_type='video/webm'))
    # 97be240 keeps upload credentials server-side: files go through the account chunk-upload API.
    page.route('**/api/upload-start', lambda route: route.fulfill(json={'upload_id': 'offline-upload'}))
    page.route('**/api/upload-chunk?*', lambda route: route.fulfill(json={'offset': len(route.request.post_data_buffer)}))
    page.route('**/api/upload-finish', lambda route: route.fulfill(json={'uploadToken': 'upl_fake'}))
    page.route('**/api/video-generate', lambda route: (generation.append(route.request.post_data_json),
                                                    route.fulfill(status=503, json={'error': 'offline only'})))
    try:
        page.goto('http://fixture.test/video')
        drop = page.locator('.drop[data-media-key="reference_image"]')
        with page.expect_file_chooser() as chooser:
            drop.locator('.upload-trigger').click()
        chooser.value.set_files({'name': 'reference.png', 'mimeType': 'image/png',
                                 'buffer': base64.b64decode(sample['png'])})
        expect(drop.locator('.fn')).to_contain_text('已上传')
        expect(drop.locator('.local-media-preview')).to_have_count(1)
        drop.hover()
        expect(drop.locator('.media-remove')).to_be_visible()
        drop.locator('.media-remove').click()
        expect(drop.locator('.local-media-preview')).to_have_count(0)
        expect(drop.locator('.fn')).to_have_text('')
        expect(drop.locator('.media-remove')).to_be_hidden()
        page.locator('#genBtn').click()
        expect(page.locator('#genStatus')).to_contain_text('缺少必传素材')
        assert not generation, 'Removing an upload must clear its submission token'

        queued = page.locator('.task-card[data-job-id="queued-0"]')
        queued.hover()
        queued.locator('.task-remove').click()
        expect(queued).to_have_attribute('data-status', 'cancelled')
        assert [action['action'] for action in actions] == ['cancel']

        page.locator('[data-group="done"] > summary').click()
        done = page.locator('.task-card[data-job-id="done-0"]')
        done.locator('.task-tile').click()
        expect(done).to_have_class('task-card is-selected')
        stage = page.locator('.preview-stage')
        expect(stage).to_have_js_property('scrollTop', 0)
        stage.evaluate('el => el.scrollTop=60')
        before = stage.evaluate('el => el.scrollTop')
        page.locator('.gallery-thumb').last.click()
        expect(page.locator('.task-card[data-job-id="done-1"]')).to_have_class('task-card is-selected')
        assert abs(stage.evaluate('el => el.scrollTop') - before) < 1
    finally:
        page.close()
