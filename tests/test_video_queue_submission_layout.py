"""Accepted submissions stay compact even while the queue snapshot is unavailable."""
import re

import pytest
from playwright.sync_api import expect

from test_app_shell import browser, serve_page


@pytest.mark.parametrize('width', [1440, 390])
def test_accepted_submission_waits_in_grid_until_queue_recovers(browser, tmp_path, width):
    page = browser.new_page(viewport={'width': width, 'height': 1000 if width == 1440 else 844})
    serve_page(page, block_scene=True)
    jobs = [dict(id='existing-done', workflow='fixture-video', wf_name='已完成任务',
                 status='done', editable=False, params={'prompt': '之前的提示词'}, media={}),
            dict(id='existing-error', workflow='fixture-video', wf_name='之前的失败任务',
                 status='error', editable=False, params={'prompt': '失败的提示词'}, media={})]
    accepted, held_queue = [], []
    snapshot_available = True
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def queue(route):
        if not snapshot_available:
            held_queue.append(route)
            return
        route.fulfill(json={'jobs': jobs, 'running': 0, 'waiting': max(0, len(jobs) - 2), 'limit': 2})

    def generate(route):
        nonlocal snapshot_available
        accepted.append(route.request.post_data_json)
        snapshot_available = False
        route.fulfill(json={'job_id': 'accepted-new'})

    page.route('**/api/video-queue', queue)
    page.route('**/api/video-generate', generate)
    page.route('**/api/job/*', lambda route: route.fulfill(json={'images': []}))

    def pending_card_is_compact(card):
        assert card.evaluate('(e)=>e.parentElement.classList.contains("task-grid")')
        assert card.evaluate('(e)=>e.closest("[data-group]").dataset.group') == 'active'
        dimensions = card.bounding_box()
        # 2026-11-10: on wide screens the task rail lists compact rows; narrower layouts keep 16:10 tiles.
        assert dimensions and dimensions['width'] < 290, dimensions
        assert (abs(dimensions['height'] - dimensions['width'] / 1.6) < 1
                or (dimensions['width'] >= 200 and 48 <= dimensions['height'] <= 72)), dimensions
        expect(card.locator('.task-badge')).to_have_text(re.compile('排队|同步|等待|提交'))
        # No revision or confirmed state exists until the snapshot arrives.
        assert card.locator('.queue-actions').evaluate(
            '(e)=>e.hidden||[...e.querySelectorAll("button")].every(b=>b.hidden||b.disabled)')

    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('.task-card')).to_have_count(2)
        page.locator('#wfForm textarea').first.fill('这次提交的提示词')
        with page.expect_request(lambda request: request.url.endswith('/api/video-queue')):
            page.locator('#genBtn').click()
        new = page.locator('[data-job-id="accepted-new"]')
        expect(new).to_be_visible()
        pending_card_is_compact(new)
        page.screenshot(path=str(tmp_path / ('submission-pending-' + str(width) + '.png')), full_page=True)

        # Reject the first snapshot, then let its automatic retry recover.
        assert held_queue, 'Accepted submission did not request a queue snapshot'
        held_queue.pop(0).fulfill(status=503, json={'error': '队列连接暂时中断'})
        expect(page.locator('#taskCount')).to_contain_text('自动重试')
        pending_card_is_compact(new)

        jobs.append(dict(id='accepted-new', workflow='fixture-video', wf_name='新任务',
                         status='queued', editable=True, position=1, queue_revision=0,
                         params={'prompt': accepted[0]['prompt']}, media={}))
        snapshot_available = True
        for route in held_queue[:]:
            route.fulfill(status=503, json={'error': '队列连接暂时中断'})
            held_queue.remove(route)
        expect(new.locator('.task-badge')).to_have_text('排队 · 第 1 位', timeout=10000)
        expect(page.locator('[data-group="active"] .task-card')).to_have_count(1)
        expect(page.locator('[data-job-id="accepted-new"]')).to_have_count(1)
        expect(page.locator('.task-card')).to_have_count(3)
        assert new.bounding_box()['width'] < 250
        new.locator('.task-tile').hover()
        expect(new.get_by_role('button', name='编辑参数')).to_be_enabled()
        assert len(accepted) == 1
        assert not errors
        page.screenshot(path=str(tmp_path / ('submission-recovered-' + str(width) + '.png')), full_page=True)
    finally:
        for route in held_queue:
            route.abort()
        page.close()
