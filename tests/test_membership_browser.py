"""Offline browser checks for identity boundaries; never submits a paid task."""
import base64
import json
from pathlib import Path
import pytest

from playwright.sync_api import expect

from test_app_shell import ROOT, browser, serve_page


def account(user_id='alice', admin=False):
    return {'enabled': True, 'authenticated': True, 'csrf_token': 'test-csrf-'+user_id,
            'user': {'id': user_id, 'display_name': '用户 '+user_id, 'is_admin': admin},
            'membership': {'plan': {'name': '创作月卡', 'max_concurrent': 2},
                           'active': True, 'expires_at': 1900000000,
                           'image_available': 98, 'video_available': 9}}


def strict_csp_shell(page):
    page.route('http://fixture.test/video', lambda route: route.fulfill(
        body=(ROOT/'static/app.html').read_bytes(), content_type='text/html', headers={
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}))


def test_login_gate_does_not_mount_or_fetch_private_pages(browser):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    requests = serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json={'enabled': True, 'authenticated': False}))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLogin')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        assert page.locator('.page-host').count() == 0
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    finally:
        page.close()


def test_auth_network_failure_stays_closed_then_retry_recovers(browser):
    page = browser.new_page()
    serve_page(page, block_scene=True)
    state = {'available': False}
    page.route('**/api/auth/me', lambda route: route.fulfill(status=200 if state['available'] else 503,
                                                          json=account() if state['available'] else {}))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountRetry')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        state['available'] = True
        page.locator('#accountRetry').click()
        expect(page.locator('#wfForm textarea')).to_be_visible()
        expect(page.locator('#accountGate')).to_be_hidden()
    finally:
        page.close()


def test_account_redeem_csrf_storage_boundary_and_expiry(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    serve_page(page, block_scene=True)
    strict_csp_shell(page)
    csp_errors = []
    page.on('console', lambda message: csp_errors.append(message.text) if 'Content Security Policy' in message.text else None)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account()))
    captures = []

    def redeem(route):
        captures.append((route.request.post_data_json, route.request.headers))
        route.fulfill(json={'membership': account()['membership']})

    page.route('**/api/membership/redeem', redeem)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert page.locator('#personalUpload').count() == 0
        # Exercise the same scoped storage bindings used by prompts, gallery,
        # upload keys, and pending submission IDs; other accounts stay untouched.
        result = page.evaluate('''() => {
            localStorage.setItem('jt-pending-video-submit','legacy-private');
            localStorage.setItem('jt-user:bob:jt-pending-video-submit','bob-private');
            const scope=jtApp.router.pages.get('/video').scope;
            const before=scope.localStorage.getItem('jt-pending-video-submit');
            scope.window.localStorage.setItem('jt-pending-video-submit','alice-private');
            scope.sessionStorage.setItem('jt-active-video','alice-task');
            return {before,own:localStorage.getItem('jt-user:alice:jt-pending-video-submit'),
              other:localStorage.getItem('jt-user:bob:jt-pending-video-submit'),
              legacy:localStorage.getItem('jt-pending-video-submit'),
              session:sessionStorage.getItem('jt-user:alice:jt-active-video')};
        }''')
        assert result == {'before': None, 'own': 'alice-private', 'other': 'bob-private',
                          'legacy': 'legacy-private', 'session': 'alice-task'}
        page.locator('#accountOpen').click()
        expect(page.locator('#accountPlan')).to_have_text('创作月卡')
        expect(page.locator('#accountQuota')).to_contain_text('98')
        page.locator('#accountCode').fill('JT-AAAAAAAA-BBBBBBBB-CCCCCCCC-DDDDDDDD')
        page.locator('#accountRedeem').click()
        expect(page.locator('#accountRedeemStatus')).to_have_text('套餐已开通。')
        assert captures[0][0] == {'code': 'JT-AAAAAAAA-BBBBBBBB-CCCCCCCC-DDDDDDDD'}
        assert captures[0][1]['x-csrf-token'] == 'test-csrf-alice'
        assert not page.evaluate("Object.values(localStorage).some(x=>x.includes('test-csrf'))")
        page.screenshot(path=str(tmp_path/'account-desktop.png'))
        page.locator('#accountClose').click()
        page.route('**/api/private-expiry', lambda route: route.fulfill(status=401, json={'error': '请登录'}))
        page.evaluate("jtApp.router.pages.get('/video').scope.fetch('/api/private-expiry')")
        expect(page.locator('body > .app-shell')).to_be_hidden()
        expect(page.locator('#accountLogin')).to_be_visible()
        assert not csp_errors
    finally:
        page.close()


def test_switching_identity_reloads_private_page_state(browser):
    page = browser.new_page()
    requests = serve_page(page, block_scene=True)
    identity = {'id': 'alice'}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account(identity['id'])))
    try:
        page.goto('http://fixture.test/video')
        prompt = page.locator('#wfForm textarea').first
        expect(prompt).to_be_visible()
        prompt.fill('Alice private prompt')
        identity['id'] = 'bob'
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#accountOpen')).to_have_text('用户 bob')
        expect(page.locator('#wfForm textarea').first).to_have_value('测试')
        assert len([r for r in requests if r[2] == 'document']) == 2
    finally:
        page.close()


def test_identity_refresh_expiry_closes_open_admin_dialog(browser):
    page = browser.new_page()
    serve_page(page, block_scene=True)
    identity = {'authenticated': True}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account(admin=True) if identity['authenticated']
                                                          else {'enabled': True, 'authenticated': False}))
    page.route('**/api/admin/membership/plans', lambda route: route.fulfill(json={'plans': []}))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdmin')).to_be_visible()
        identity['authenticated'] = False
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#accountLogin')).to_be_visible()
        expect(page.locator('#membershipAdmin')).to_be_hidden()
        expect(page.locator('body > .app-shell')).to_be_hidden()
    finally:
        page.close()


def test_member_upload_uses_scoped_chunks_and_waits_for_receipt(browser):
    page = browser.new_page()
    requests = serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account()))
    page.route('**/api/workflows', lambda route: route.fulfill(json=[{
        'id': 'fixture-video', 'kind': 'video', 'name': '测试视频',
        'rh_media': {'reference_image': {'type': 'image', 'label': '参考图', 'required': True}},
        'rh_params': {'prompt': {'type': 'text', 'label': '提示词', 'default': '测试'}}}]))
    posts = []
    finish_calls = []

    def respond(route, payload):
        posts.append((route.request.url, route.request.headers))
        route.fulfill(json=payload)

    page.route('**/api/upload-start', lambda route: respond(route, {'upload_id': 'upload-a'}))
    page.route('**/api/upload-chunk?*', lambda route: respond(route, {'offset': len(route.request.post_data_buffer)}))

    def finish(route):
        finish_calls.append(True)
        respond(route, {'status': 'processing'} if len(finish_calls) == 1 else
                {'status': 'done', 'uploadToken': 'owned-upload-token'})

    page.route('**/api/upload-finish', finish)
    try:
        page.goto('http://fixture.test/video')
        drop = page.locator('[data-media-key="reference_image"]')
        expect(drop).to_be_visible()
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZQAAAABJRU5ErkJggg==')
        drop.locator('input[type=file]').set_input_files({'name': 'reference.png', 'mimeType': 'image/png', 'buffer': png})
        expect(drop.locator('.fn')).to_contain_text('已上传', timeout=10000)
        assert len(finish_calls) == 2
        assert len(posts) == 4
        assert all(headers['x-csrf-token'] == 'test-csrf-alice' for _, headers in posts)
        assert not [r for r in requests if '/api/upload-direct-' in r[1]]
        assert page.locator('#personalUpload').count() == 0
    finally:
        page.close()


def test_admin_plan_and_activation_code_flow(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account('admin', True)))
    plans, saves, issue_requests = [], [], []

    def plan_route(route):
        if route.request.method == 'POST':
            plan = dict(route.request.post_data_json, id='plan-a')
            saves.append(plan)
            plans.append(plan)
            route.fulfill(json={'plan': plan})
        else:
            route.fulfill(json={'plans': plans})

    def code_route(route):
        if route.request.method == 'POST':
            issue_requests.append((route.request.post_data_json, route.request.headers))
            route.fulfill(json={'codes': [{'id': 'code-a', 'code': 'JT-11111111-22222222-33333333-44444444'}]})
        else:
            route.fulfill(json={'codes': [{'id': 'code-a', 'code_hint': '4444', 'plan_id': 'plan-a', 'note': '',
                                         'redeemed_at': None, 'revoked_at': None}] if issue_requests else []})

    page.route('**/api/admin/membership/plans', plan_route)
    page.route('**/api/admin/membership/codes*', code_route)
    try:
        page.goto('http://fixture.test/video')
        page.locator('#membershipAdminOpen').click()
        form = page.locator('#adminPlanForm')
        form.locator('[name=name]').fill('创作月卡')
        form.locator('[name=price_display]').fill('99 元 / 月')
        form.locator('[name=max_concurrent]').fill('2')
        form.get_by_role('button', name='保存套餐').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('套餐已保存。')
        assert saves[0]['duration_days'] == 30 and saves[0]['max_concurrent'] == 2
        assert saves[0]['features'] == ['image', 'video', 'upload', 'history', 'favorites']
        page.locator('[data-admin-tab=codes]').click()
        page.locator('#adminCodeForm [name=note]').fill('线下订单 001')
        page.locator('#adminCodeForm button[type=submit]').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value('JT-11111111-22222222-33333333-44444444')
        assert issue_requests[0][0] == {'plan_id': 'plan-a', 'count': 1, 'note': '线下订单 001'}
        assert issue_requests[0][1]['x-csrf-token'] == 'test-csrf-admin'
        assert not page.evaluate("Object.values(localStorage).some(x=>x.includes('JT-11111111'))")
        page.screenshot(path=str(tmp_path/'admin-desktop.png'))
        page.locator('#membershipAdminClose').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value('')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('#accountOpen').click()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'account-mobile.png'))
    finally:
        page.close()


@pytest.mark.parametrize('success', [True, False])
def test_admin_reservation_settlement_requires_note_and_confirmation(browser, success):
    page = browser.new_page()
    serve_page(page, block_scene=True)
    strict_csp_shell(page)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account('admin', True)))
    page.route('**/api/admin/membership/plans', lambda route: route.fulfill(json={'plans': []}))
    items = [dict(job_id='uncertain', user_id='alice', kind='video', units=1, state='running',
                  job_status='error', reason='结果未确认', can_settle=True),
             dict(job_id='active', user_id='alice', kind='image', units=4, state='running',
                  job_status='running', reason='', can_settle=False),
             dict(job_id='recovering', user_id='alice', kind='video', units=1, state='running',
                  job_status='recovering', reason='', can_settle=True)]
    page.route('**/api/admin/membership/reservations', lambda route: route.fulfill(json={'reservations': items}))
    posts = []

    def settle(route):
        posts.append((route.request.post_data_json, route.request.headers))
        items.pop(0)
        route.fulfill(json={'ok': True})

    page.route('**/api/admin/membership/reservations/settle', settle)
    try:
        page.goto('http://fixture.test/video')
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('')
        page.locator('[data-admin-tab=reservations]').click()
        row = page.locator('[data-reservation=uncertain]')
        expect(row).to_be_visible()
        expect(page.locator('[data-reservation=active] button')).to_be_disabled()
        expect(page.locator('[data-reservation=recovering] button')).to_be_disabled()
        row.get_by_role('button', name='确认计费' if success else '退回额度', exact=True).click()
        page.locator('#adminSettleNote').fill('短说明')
        page.locator('#adminSettleSubmit').click()
        assert not posts
        note = '已核实服务后台的实际任务结果与生成记录。'
        page.locator('#adminSettleNote').fill(note)
        page.once('dialog', lambda dialog: dialog.dismiss())
        page.locator('#adminSettleSubmit').click()
        assert not posts
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#adminSettleSubmit').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('额度已结算。' if success else '额度已退回。')
        assert len(posts) == 1
        assert posts[0][0] == {'job_id': 'uncertain', 'success': success, 'note': note}
        assert posts[0][1]['x-csrf-token'] == 'test-csrf-admin'
        expect(row).to_have_count(0)
    finally:
        page.close()


@pytest.mark.parametrize('logout_url,redirect', [
    ('https://auth.dreamapi.club/api/logout?client_id=fixture&post_logout_redirect_uri=https%3A%2F%2Fstudio.dreamapi.club%2F', True),
    ('https://evil.example/api/logout', False),
    ('http://auth.dreamapi.club/api/logout', False),
    ('https://auth.dreamapi.club/other-path', False),
    ('https://unexpected@auth.dreamapi.club/api/logout', False),
    (None, False),
])
def test_logout_only_redirects_to_exact_https_identity_logout(browser, logout_url, redirect):
    page = browser.new_page()
    requests = serve_page(page, block_scene=True)
    state, posts = {'signed_in': True}, []
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if state['signed_in'] else
                                                          {'enabled': True, 'authenticated': False}))

    def logout(route):
        state['signed_in'] = False
        posts.append(route.request.headers)
        route.fulfill(json={'ok': True, 'logout_url': logout_url})

    page.route('**/api/auth/logout', logout)
    page.route('https://auth.dreamapi.club/api/logout?*', lambda route: route.fulfill(body='Signed out', content_type='text/plain'))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#accountOpen').click()
        page.locator('#accountLogout').click()
        if redirect:
            page.wait_for_url(logout_url)
            expect(page.locator('body')).to_contain_text('Signed out')
        else:
            expect(page.locator('#accountLogin')).to_be_visible()
            assert page.url == 'http://fixture.test/video'
            assert len([request for request in requests if request[2] == 'document']) == 2
        assert len(posts) == 1 and posts[0]['x-csrf-token'] == 'test-csrf-alice'
    finally:
        page.close()
