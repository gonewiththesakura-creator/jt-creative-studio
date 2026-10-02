"""Visible clear controls with every request intercepted; no provider calls."""
import base64
import copy

from playwright.sync_api import expect

from test_app_shell import browser, serve_page


PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=')


def clear_fixture(page, fail=False):
    serve_page(page, block_scene=True)
    jobs = [dict(id=job_id, workflow='fixture-video', wf_name=label,
                 status=status, created=100 + index, prompt='保留配置-' + job_id,
                 params={'lora_1_model': 'minimax-n4', 'lora_1_strength': .7},
                 images=[dict(url='/result-' + job_id + '.png', file_type='png')]
                 if status == 'done' else [],
                 editable=status == 'queued', cancellable=status == 'running',
                 position=1 if status == 'queued' else None)
            for index, (job_id, label, status) in enumerate([
                ('done-a', '完成甲', 'done'), ('done-b', '完成乙', 'done'),
                ('error-a', '失败甲', 'error'), ('cancelled-a', '取消甲', 'cancelled'),
                ('queued-a', '排队甲', 'queued'), ('running-a', '生成甲', 'running')])]
    calls, queue_polls = [], []

    def queue(route):
        queue_polls.append(True)
        route.fulfill(json={'jobs': [copy.deepcopy(job) for job in jobs
                                    if not job.get('task_cleared')],
                            'running': 1, 'waiting': 1, 'limit': 2})

    def clear(route):
        body = route.request.post_data_json
        calls.append(body)
        if fail:
            return route.fulfill(status=503, json={'error': '离线模拟清除失败'})
        scope = body['scope']
        eligible = [job for job in jobs if job['status'] in (
            ('error', 'cancelled') if scope == 'errors' else ('done', 'error', 'cancelled'))]
        for job in eligible:
            job['gallery_cleared'] = True
            if scope != 'gallery':
                job['task_cleared'] = job['history_cleared'] = True
        route.fulfill(json={'ok': True, 'scope': scope,
                            'cleared_ids': [job['id'] for job in eligible]})

    page.route('**/api/video-queue', queue)
    page.route('**/api/jobs?*', lambda route: route.fulfill(
        json=[copy.deepcopy(job) for job in jobs if not job.get('history_cleared')]))
    page.route('**/api/job/*', lambda route: route.fulfill(json=copy.deepcopy(next(
        job for job in jobs if job['id'] == route.request.url.rsplit('/', 1)[-1]))))
    page.route('**/result-*.png', lambda route: route.fulfill(body=PNG, content_type='image/png'))
    page.route('**/api/video-clear', clear)
    page.route('**/api/favorites', lambda route: route.fulfill(json=[dict(
        id='saved-a', job_id='done-a', style_id='video', archive_status='ready',
        favorite_media_type='image/png', image_url='/result-done-a.png',
        prompt='收藏仍然保留', selection_snapshot={'params': jobs[0]['params']})]))
    return jobs, calls, queue_polls


def test_clear_scopes_preserve_active_tasks_favorites_and_survive_polling(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    jobs, calls, queue_polls = clear_fixture(page)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('.task-card')).to_have_count(6)
        expect(page.locator('.gallery-thumb')).to_have_count(2)

        page.locator('#clearVideoGallery').click()
        expect(page.locator('.gallery-thumb')).to_have_count(0)
        expect(page.locator('.task-card')).to_have_count(6)
        before_poll = len(queue_polls)
        page.wait_for_timeout(4300)
        assert len(queue_polls) > before_poll, 'Exercise a later queue refresh after clearing'
        expect(page.locator('.gallery-thumb')).to_have_count(0)
        page.reload()
        expect(page.locator('.task-card')).to_have_count(6)
        expect(page.locator('.gallery-thumb')).to_have_count(0)
        page.locator('#histOpen').first.click()
        expect(page.locator('#histList .history-card')).to_have_count(6)
        page.locator('#histOverlay .close').click()

        page.locator('#clearVideoErrors').click()
        expect(page.locator('.task-card')).to_have_count(4)
        expect(page.locator('.task-card[data-job-id="done-a"]')).to_have_count(1)
        expect(page.locator('.task-card[data-job-id="done-b"]')).to_have_count(1)
        expect(page.locator('.task-card[data-job-id="error-a"]')).to_have_count(0)
        expect(page.locator('.task-card[data-job-id="cancelled-a"]')).to_have_count(0)
        page.locator('#histOpen').first.click()
        expect(page.locator('#histList .history-card')).to_have_count(4)
        page.locator('#clearVideoHistory').click()
        expect(page.locator('#histList .history-card')).to_have_count(2)
        expect(page.locator('#histList')).to_contain_text('排队甲')
        expect(page.locator('#histList')).to_contain_text('生成甲')
        page.locator('#histOverlay .close').click()
        expect(page.locator('.task-card')).to_have_count(2)
        expect(page.locator('.task-card[data-job-id="queued-a"]')).to_have_count(1)
        expect(page.locator('.task-card[data-job-id="running-a"]')).to_have_count(1)

        page.reload()
        expect(page.locator('.task-card')).to_have_count(2)
        expect(page.locator('.gallery-thumb')).to_have_count(0)
        page.locator('#favOpen').first.click()
        expect(page.locator('.favorite-card[data-favorite-id="saved-a"]')).to_contain_text('收藏仍然保留')
        assert [call['scope'] for call in calls] == ['gallery', 'errors', 'history']
        assert [job['status'] for job in jobs[-2:]] == ['queued', 'running']
        assert not any(job.get('task_cleared') or job.get('history_cleared')
                       for job in jobs[-2:])
        assert not errors
    finally:
        page.close()


def test_failed_clear_keeps_results_and_task_history(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    jobs, calls, _ = clear_fixture(page, fail=True)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('.gallery-thumb')).to_have_count(2)
        page.locator('#clearVideoGallery').click()
        expect(page.locator('#genStatus')).to_contain_text('清除失败')
        expect(page.locator('#clearVideoGallery')).to_be_enabled()
        expect(page.locator('.gallery-thumb')).to_have_count(2)
        expect(page.locator('.task-card')).to_have_count(6)
        page.locator('#histOpen').first.click()
        expect(page.locator('#histList .history-card')).to_have_count(6)
        assert calls == [{'scope': 'gallery'}]
        assert not any(job.get('gallery_cleared') for job in jobs)
    finally:
        page.close()
