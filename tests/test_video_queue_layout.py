"""A long queue keeps its contact sheet intact while cards move between groups."""
import base64

from playwright.sync_api import expect

from test_app_shell import browser, serve_page
from test_video_thumbnails import jpeg


def test_long_queue_keeps_compact_tiles_after_hover_reorder_and_completion(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1920, 'height': 1000})
    serve_page(page, block_scene=True)
    jobs = [dict(id=str(i), workflow='fixture-video', wf_name='视频工作流',
                 status='running' if i < 2 else 'queued', editable=i >= 2,
                 position=i - 1, media={'source_video': '素材-' + str(i) + '.mp4'},
                 params={'prompt': '保留原片场景'}, queue_revision=0,
                 thumbnails={'source_video': '/api/video-thumbnail/abcdef123456/' + 'a' * 32 + '.jpg'})
            for i in range(48)]
    queue_reads = []

    def queue(route):
        if route.request.method == 'POST':
            body = route.request.post_data_json
            if body['action'] == 'top':
                job = next(j for j in jobs if j['id'] == body['job_id'])
                jobs.remove(job)
                jobs.insert(2, job)
                for index, item in enumerate(jobs[2:], 1):
                    item['position'] = index
            return route.fulfill(json={'ok': True})
        queue_reads.append(True)
        return route.fulfill(json={'jobs': jobs, 'running': 2, 'waiting': 46, 'limit': 2})

    page.route('**/api/video-queue', queue)
    page.route('**/api/video-thumbnail/**', lambda r: r.fulfill(
        body=base64.b64decode(jpeg()), content_type='image/jpeg'))
    page.route('**/api/job/*', lambda r: r.fulfill(json={'id': r.request.url.rsplit('/', 1)[-1],
                                                    'images': [{'url': '/result.png', 'file_type': 'image'}]}))
    page.route('**/result.png', lambda r: r.fulfill(body=base64.b64decode(jpeg()), content_type='image/jpeg'))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def compact_tiles():
        dimensions = page.locator('[data-group=active] .task-tile').evaluate_all(
            '(tiles)=>tiles.map(e=>{const r=e.getBoundingClientRect();return [r.width,r.height]})')
        assert dimensions
        assert all(100 <= width < 250 and abs(height - width / 1.6) < 1
                   for width, height in dimensions), dimensions

    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('[data-group=active] .task-card')).to_have_count(48)
        compact_tiles()
        late = page.locator('[data-job-id="47"]')
        late.locator('.task-tile').hover()
        expect(late.locator('.task-badge')).to_have_text('排队 · 第 46 位')
        popup = late.locator('.task-details')
        expect(popup).to_be_visible()
        assert popup.evaluate('(e)=>getComputedStyle(e).position') == 'fixed'
        compact_tiles()
        late.get_by_role('button', name='置顶插队').click()
        expect(late.locator('.task-badge')).to_have_text('排队 · 第 1 位')
        assert page.locator('[data-group=active] .task-card').nth(2).get_attribute('data-job-id') == '47'
        compact_tiles()

        # Polling moves a terminal card without exposing its hidden queue actions.
        jobs[2].update(status='done', editable=False, position=None)
        expect(page.locator('[data-group=done] .task-card')).to_have_count(1, timeout=10000)
        page.locator('[data-group=done] summary').click()
        late.locator('.task-tile').hover()
        expect(late.locator('.queue-actions')).to_be_hidden()
        assert late.locator('.queue-actions').evaluate('(e)=>getComputedStyle(e).display') == 'none'
        compact_tiles()
        page.screenshot(path=str(tmp_path / 'long-queue-desktop.png'), full_page=True)

        page.set_viewport_size({'width': 390, 'height': 844})
        last = page.locator('[data-group=active] .task-card').last
        last.locator('.task-tile').hover()
        expect(last.locator('.task-badge')).to_be_visible()
        compact_tiles()
        assert last.locator('.task-details').bounding_box()['width'] <= 374
        page.screenshot(path=str(tmp_path / 'long-queue-mobile.png'), full_page=True)
        assert len(queue_reads) >= 3
        assert not errors
    finally:
        page.close()
