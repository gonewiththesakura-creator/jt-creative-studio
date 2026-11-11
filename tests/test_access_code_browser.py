"""Offline access-code login and admin flows; all provider traffic is intercepted."""
import pytest
from playwright.sync_api import expect

from test_app_shell import browser, serve_page
from test_membership_browser import account, open_admin, strict_csp_shell


LOGIN_CODE = 'JT-TEST-LOGIN-AAAAAAAA-BBBBBBBB-CCCCCCCC'
ROTATED_CODE = 'JT-TEST-ROTATED-DDDDDDDD-EEEEEEEE-FFFFFFFF'


def identity(user_id=None, admin=False):
    result = account(user_id, admin) if user_id else {'enabled': True, 'authenticated': False}
    return dict(result, login_method='access_code', admin_login_available=True)


def assert_no_saved_code(page, code):
    assert code not in page.url
    assert not page.evaluate('code => [...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(code))', code)


@pytest.mark.parametrize('width', [390, 1440])
def test_code_login_reveals_same_document_without_persisting_secret(browser, width):
    page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    strict_csp_shell(page)
    user = {'id': None}
    posts, errors, documents = [], [], []
    page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity(user['id'])))

    def code_login(route):
        posts.append((route.request.post_data_json, route.request.headers))
        user['id'] = 'alice'
        route.fulfill(json={'ok': True})

    page.route('**/api/auth/code-login', code_login)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLoginCode')).to_be_visible()
        expect(page.locator('#accountLoginCode')).to_have_attribute('type', 'password')
        expect(page.locator('#accountAdminLogin')).to_have_text('改用管理员账号登录')  # 2026-11-11: secondary link, studio v2 login page
        assert page.locator('.page-host').count() == 0
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        page.evaluate('window.sameDocumentMarker = 12345')
        page.locator('#accountLoginCode').fill(LOGIN_CODE)
        page.locator('#accountLogin').click()
        expect(page.locator('#wfForm textarea')).to_be_visible()
        expect(page.locator('#accountGate')).to_be_hidden()
        expect(page.locator('#accountLoginCode')).to_have_value('')
        assert page.evaluate('window.sameDocumentMarker') == 12345
        assert len(documents) == 1
        assert posts[0][0] == {'code': LOGIN_CODE}
        assert posts[0][1]['origin'] == 'http://fixture.test'
        assert 'x-csrf-token' not in posts[0][1]
        assert_no_saved_code(page, LOGIN_CODE)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
    finally:
        page.close()


@pytest.mark.parametrize('status,message', [(401, '登录激活码无效或已停用'), (429, '尝试过于频繁，请稍后重试')])
def test_rejected_code_never_mounts_private_page_or_sticks_disabled(browser, status, message):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity()))
    page.route('**/api/auth/code-login', lambda route: route.fulfill(status=status, json={'error': message}))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#accountLoginCode').fill(LOGIN_CODE)
        page.locator('#accountLogin').click()
        expect(page.locator('#accountGateStatus')).to_have_text(message)
        expect(page.locator('#accountLogin')).to_be_enabled()
        expect(page.locator('#accountLoginCode')).to_be_enabled()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        assert page.locator('.page-host').count() == 0
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        assert_no_saved_code(page, LOGIN_CODE)
    finally:
        page.close()


def test_expired_session_then_other_code_reloads_account_private_state(browser):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    user = {'id': 'alice'}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity(user['id'])))

    def switch(route):
        user['id'] = 'bob'
        route.fulfill(json={'ok': True})

    page.route('**/api/auth/code-login', switch)
    try:
        page.goto('http://fixture.test/video')
        prompt = page.locator('#wfForm textarea').first
        expect(prompt).to_be_visible()
        prompt.fill('Alice private prompt')
        page.evaluate("jtApp.router.pages.get('/video').scope.localStorage.setItem('private', 'alice-only')")
        user['id'] = None
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#accountLoginCode')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        page.locator('#accountLoginCode').fill(ROTATED_CODE)
        page.locator('#accountLogin').click()
        expect(page.locator('#accountOpen')).to_have_text('用户 bob')
        expect(page.locator('#wfForm textarea').first).to_have_value('测试')
        assert page.evaluate("jtApp.router.pages.get('/video').scope.localStorage.getItem('private')") is None
        assert page.evaluate("localStorage.getItem('jt-user:alice:private')") == 'alice-only'
        assert len([r for r in requests if r[2] == 'document']) == 2
        assert_no_saved_code(page, ROTATED_CODE)
    finally:
        page.close()


# 15f4c40 made same-account re-login reload the page (losing drafts) because expiry clears private media;
# since 2026-10-20 only a different identity reloads, and the gallery repaints via jt:media-restore.
def test_same_account_relogin_clears_transition_marker_without_reloading_private_state(browser):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    user = {'id': 'alice'}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity(user['id'])))

    def relogin(route):
        user['id'] = 'alice'
        route.fulfill(json={'ok': True})

    page.route('**/api/auth/code-login', relogin)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#wfForm textarea').first).to_be_visible()
        page.locator('#wfForm textarea').first.fill('同账号未提交内容')
        user['id'] = None
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#accountLoginCode')).to_be_visible()
        page.locator('#accountLoginCode').fill(LOGIN_CODE)
        page.locator('#accountLogin').click()
        expect(page.locator('#accountGate')).to_be_hidden()
        expect(page.locator('#wfForm textarea').first).to_have_value('同账号未提交内容')
        assert len([r for r in requests if r[2] == 'document']) == 1
        assert page.evaluate("sessionStorage.getItem('jt-login-transition')") is None
        assert_no_saved_code(page, LOGIN_CODE)
    finally:
        page.close()


def admin_page(browser):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    serve_page(page, block_scene=True)
    strict_csp_shell(page)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity('admin', True)))
    page.route('**/api/admin/membership/plans', lambda route: route.fulfill(json={'plans': [
        {'id': 'plan-a', 'name': '月卡', 'active': True}]}))
    return page


def test_admin_issues_distinct_login_and_renewal_codes_and_revokes_used_login(browser):
    page = admin_page(browser)
    posts, revocations = [], []
    login_codes = [{'id': 'code-old', 'code_hint': 'OLD1', 'plan_id': 'plan-a',
                    'user_id': 'alice', 'activated_at': 1, 'revoked_at': None,
                    'note': '<img src=x onerror=alert(1)>'}]

    def issue(route, kind):
        if route.request.method == 'POST':
            posts.append((kind, route.request.post_data_json, route.request.headers))
            route.fulfill(json={'codes': [{'id': 'new-'+kind, 'code': LOGIN_CODE if kind == 'access-codes' else 'JT-RENEWAL-ONCE'}]})
        else:
            route.fulfill(json={'codes': login_codes if kind == 'access-codes' else []})

    page.route('**/api/admin/membership/access-codes*', lambda route: issue(route, 'access-codes'))
    page.route('**/api/admin/membership/codes*', lambda route: issue(route, 'codes'))

    def revoke(route):
        revocations.append(route.request.post_data_json)
        login_codes[0]['revoked_at'] = 2
        route.fulfill(json={'ok': True})

    page.route('**/api/admin/membership/access-codes/revoke', revoke)
    try:
        page.goto('http://fixture.test/video')
        open_admin(page)
        page.locator('[data-admin-tab=codes]').click()
        expect(page.locator('#adminCodesRows')).to_contain_text('使用中')
        expect(page.locator('#adminCodesRows')).to_contain_text('<img src=x onerror=alert(1)>')
        assert page.locator('#adminCodesRows img').count() == 0
        page.locator('#adminCodeForm [name=note]').fill('线下订单 002')
        page.locator('#adminCodeForm button[type=submit]').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value(LOGIN_CODE)
        assert posts[0][0] == 'access-codes'
        assert posts[0][1] == {'plan_id': 'plan-a', 'count': 1, 'note': '线下订单 002'}
        assert posts[0][2]['x-csrf-token'] == 'test-csrf-admin'
        assert_no_saved_code(page, LOGIN_CODE)
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#adminCodesRows').get_by_role('button', name='作废').click()
        expect(page.locator('#adminCodesRows')).to_contain_text('已作废')
        assert revocations == [{'code_id': 'code-old'}]
        page.locator('[data-admin-tab=renewals]').click()
        expect(page.locator('#adminCodeForm button[type=submit]')).to_have_text('生成续费码')
        page.locator('#adminCodeForm button[type=submit]').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value('JT-RENEWAL-ONCE')
        assert posts[1][0] == 'codes'
        page.locator('#membershipAdminClose').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value('')
    finally:
        page.close()


def test_admin_rotates_existing_account_only_after_confirmation_and_clears_secret_on_expiry(browser):
    page = admin_page(browser)
    page.route('**/api/admin/membership/users?*', lambda route: route.fulfill(json={'users': [
        {'id': 'alice', 'display_name': '原账号 Alice', 'disabled': False, 'is_admin': False}]}))
    posts = []

    def rotate(route):
        posts.append((route.request.post_data_json, route.request.headers))
        route.fulfill(json={'code': {'id': 'new-code', 'code': ROTATED_CODE, 'user_id': 'alice'}})

    page.route('**/api/admin/membership/users/rotate-code', rotate)
    try:
        page.goto('http://fixture.test/video')
        open_admin(page)
        page.locator('[data-admin-tab=users]').click()
        button = page.locator('#adminUsersRows').get_by_role('button', name='更换登录码')
        expect(button).to_be_visible()
        page.once('dialog', lambda dialog: dialog.dismiss())
        button.click()
        assert not posts
        page.once('dialog', lambda dialog: dialog.accept())
        button.click()
        expect(page.locator('#adminIssuedCodes')).to_have_value(ROTATED_CODE)
        expect(page.locator('#adminIssuedCodes')).to_be_visible()
        assert posts[0][0]['user_id'] == 'alice'
        assert len(posts[0][0]['note']) >= 10
        assert posts[0][1]['x-csrf-token'] == 'test-csrf-admin'
        assert_no_saved_code(page, ROTATED_CODE)
        page.evaluate("window.dispatchEvent(new CustomEvent('jt:auth-expired'))")
        expect(page.locator('#membershipAdmin')).to_be_hidden()
        expect(page.locator('#adminIssuedCodes')).to_have_value('')
        expect(page.locator('body > .app-shell')).to_be_hidden()
    finally:
        page.close()
