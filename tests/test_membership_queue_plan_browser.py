"""Offline checks for per-account video queue limits in packaged membership pages."""
import pytest
from playwright.sync_api import expect

from test_app_shell import browser, serve_page
from test_membership_browser import account


@pytest.mark.parametrize('width', [320, 390, 1440])
def test_admin_video_queue_limit_round_trip_defaults_and_validation(browser, tmp_path, width):
    page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
    serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account('owner', True)))
    plans = {'legacy-plan': {
        'id': 'legacy-plan', 'name': '旧套餐', 'price_display': '', 'active': True,
        'duration_days': 30, 'max_concurrent': 2, 'image_units': 100, 'video_units': 10,
        'features': ['image', 'video', 'upload', 'history', 'favorites'], 'backends': ['cloud'],
    }}
    saves = []

    def plan_route(route):
        if route.request.method == 'POST':
            payload = route.request.post_data_json
            saves.append((payload, route.request.headers))
            plan_id = payload.get('plan_id', 'new-plan')
            plans[plan_id] = {**payload, 'id': plan_id}
            route.fulfill(json={'plan': plans[plan_id]})
        else:
            route.fulfill(json={'plans': list(plans.values())})

    page.route('**/api/admin/membership/plans', plan_route)
    try:
        page.goto('http://fixture.test/video')
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('')
        form = page.locator('#adminPlanForm')
        queue = form.get_by_label('视频排队数', exact=True)
        selector = page.locator('#adminPlanSelect')
        save = form.get_by_role('button', name='保存套餐')
        expect(queue).to_have_value('100')
        expect(queue).to_have_attribute('aria-describedby', 'adminVideoQueueHelp')
        expect(page.locator('#adminVideoQueueHelp')).to_have_text(
            '只计算等待中的视频，不含生成中任务；每个账号单独计算。')
        form.get_by_label('套餐名称', exact=True).fill('视频创作套餐')
        for invalid in ('0', '101', '1.5', ''):
            queue.fill(invalid)
            save.click()
            assert not queue.evaluate('el => el.validity.valid')
            assert saves == []

        queue.fill('7')
        save.click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('套餐已保存。')
        assert type(saves[0][0]['max_video_queued']) is int
        assert saves[0][0]['max_video_queued'] == 7
        assert saves[0][1]['x-csrf-token'] == 'test-csrf-owner'
        expect(selector).to_have_value('new-plan')
        expect(queue).to_have_value('7')

        selector.select_option('legacy-plan')
        expect(queue).to_have_value('100')
        selector.select_option('new-plan')
        expect(queue).to_have_value('7')
        queue.fill('3')
        save.click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('套餐已保存。')
        assert len(saves) == 2
        assert saves[1][0]['plan_id'] == 'new-plan'
        assert type(saves[1][0]['max_video_queued']) is int
        assert saves[1][0]['max_video_queued'] == 3
        expect(queue).to_have_value('3')
        selector.select_option('legacy-plan')
        expect(queue).to_have_value('100')
        selector.select_option('new-plan')
        expect(queue).to_have_value('3')
        selector.select_option('')
        expect(queue).to_have_value('100')
        expect(form.get_by_label('套餐名称', exact=True)).to_have_value('')

        selector.select_option('legacy-plan')
        for limit in (100, 1):
            expect(queue).to_have_value('100')
            if limit != 100:
                queue.fill(str(limit))
            save.click()
            expect(page.locator('#membershipAdminStatus')).to_have_text('套餐已保存。')
            assert saves[-1][0]['plan_id'] == 'legacy-plan'
            assert type(saves[-1][0]['max_video_queued']) is int
            assert saves[-1][0]['max_video_queued'] == limit
            expect(queue).to_have_value(str(limit))

        page.reload()
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('')
        selector.select_option('new-plan')
        expect(queue).to_have_value('3')
        queue.scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#membershipAdmin').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
        for locator in (queue, page.locator('#adminVideoQueueHelp')):
            assert locator.evaluate('el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; }')
        page.screenshot(path=str(tmp_path / f'video-queue-plan-{width}.png'))
    finally:
        page.close()


@pytest.mark.parametrize('width', [320, 390])
@pytest.mark.parametrize('limit,expected', [(7, '7'), (None, '100')])
def test_account_shows_snapshot_video_queue_limit_and_refreshes(browser, tmp_path, width, limit, expected):
    page = browser.new_page(viewport={'width': width, 'height': 844}, reduced_motion='reduce')
    serve_page(page, block_scene=True)
    identity = account()
    identity['membership']['max_video_queued'] = 99
    if limit is not None:
        identity['membership']['plan']['max_video_queued'] = limit
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#accountOpen').click()
        queue = page.locator('#accountQuota > div').filter(has=page.get_by_text('视频排队上限', exact=True))
        expect(queue.locator('dd')).to_have_text(expected)
        expect(page.locator('#accountVideoQueueHelp')).to_be_visible()
        expect(page.locator('#accountVideoQueueHelp')).to_contain_text('不含生成中任务；每个账号单独计算')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#accountDialog').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(tmp_path / f'video-queue-account-{width}-{expected}.png'))

        identity['membership']['plan']['max_video_queued'] = 3
        page.locator('#accountRefresh').click()
        expect(queue.locator('dd')).to_have_text('3')
        identity['membership'] = {}
        page.locator('#accountRefresh').click()
        expect(queue.locator('dd')).to_have_text('—')
        expect(page.locator('#accountVideoQueueHelp')).to_be_hidden()
    finally:
        page.close()
