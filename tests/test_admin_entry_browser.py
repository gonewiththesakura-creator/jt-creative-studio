"""Offline checks for the persistent admin entry and re-verification boundary."""
from html import escape
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from test_app_shell import browser, serve_page
from test_membership_browser import account, open_admin


ADMIN_TABS = ('plans', 'codes', 'renewals', 'users', 'reservations')
ISSUED_CODE = 'JT-11111111-22222222-33333333-44444444'
PLAN = {
    'id': 'plan-a', 'name': '创作月卡', 'active': True,
    'price_display': '99 元 / 月', 'duration_days': 30, 'max_concurrent': 2,
    'image_units': 100, 'video_units': 10,
    'features': ['image', 'video', 'upload', 'history', 'favorites'],
    'backends': ['cloud'],
}


def admin_account(required=False):
    return dict(account('owner', admin=True), login_method='access_code',
                admin_login_available=True, admin_verification_required=required)


def serve_admin(page, identity):
    """Use fake identities and catch every request before it can leave the browser."""
    serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity['data']))
    calls = []

    def admin_route(route):
        request = route.request
        path = urlparse(request.url).path.removeprefix('/api/admin/membership/')
        calls.append((request.method, path))
        if request.method != 'GET':
            route.fulfill(status=503, json={'error': 'Unconfigured offline mutation'})
        elif path == 'plans':
            route.fulfill(json={'plans': [PLAN]})
        elif path in ('access-codes', 'codes'):
            route.fulfill(json={'codes': []})
        elif path == 'users':
            route.fulfill(json={'users': []})
        elif path == 'reservations':
            route.fulfill(json={'reservations': []})
        else:
            route.fulfill(status=404, json={'error': 'Unknown offline admin route'})

    page.route('**/api/admin/membership/**', admin_route)
    return calls


def expect_tab(page, tab):
    expect(page.locator(f'[data-admin-tab="{tab}"]')).to_have_attribute('aria-pressed', 'true')
    panel = 'codes' if tab == 'renewals' else tab
    expect(page.locator(f'[data-admin-panel="{panel}"]')).to_be_visible()
    expect(page.locator('#membershipAdminStatus')).to_have_text('')


def assert_no_plaintext_code(page):
    expect(page.locator('#adminIssuedCodes')).to_have_value('')
    expect(page.locator('#adminIssued')).to_be_hidden()
    assert page.evaluate('''code => ![
        document.documentElement.outerHTML, location.href,
        ...Array.from(document.querySelectorAll('input, textarea'), el => el.value),
        ...Object.values(localStorage), ...Object.values(sessionStorage)
    ].some(value => value.includes(code))''', ISSUED_CODE)


def test_expired_admin_keeps_entry_without_loading_management_data(browser):
    page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
    calls = serve_admin(page, {'data': admin_account(required=True)})
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#membershipAdminOpen')).to_have_text('管理后台')
        expect(page.locator('#accountOpen')).to_have_text('我的账号')
        assert page.locator('.topbar-tools #membershipAdminVerify').count() == 0
        open_admin(page)
        expect(page.locator('#membershipAdmin')).to_be_visible()
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        expect(page.locator('#membershipAdminVerification')).to_contain_text('owner')
        expect(page.locator('#membershipAdmin #membershipAdminVerify')).to_be_visible()
        expect(page.locator('#membershipAdminContent')).to_be_hidden()
        assert page.locator('#membershipAdminContent').evaluate('el => el.inert')
        assert calls == []
        page.locator('#membershipAdminClose').click()
        open_admin(page)
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        assert calls == []
    finally:
        page.close()


@pytest.mark.parametrize('tab', ADMIN_TABS)
def test_admin_verification_returns_to_same_tab_and_consumes_query(browser, tab):
    page = browser.new_page(reduced_motion='reduce')
    identity = {'data': admin_account()}
    calls = serve_admin(page, identity)
    return_paths = []

    def verify_and_return(route):
        return_to = parse_qs(urlparse(route.request.url).query)['return_to'][0]
        return_paths.append(return_to)
        identity['data'] = admin_account()
        # Playwright does not route the later requests in an HTTP redirect
        # chain. A fixture identity page keeps the return navigation offline.
        route.fulfill(content_type='text/html', body=(
            '<a id="offlineIdentityReturn" href="' + escape(return_to, quote=True)
            + '">验证成功，返回工作台</a>'))

    page.route('**/api/auth/login?*', verify_and_return)
    try:
        page.goto('http://fixture.test/video?keep=fixture')
        open_admin(page)
        expect_tab(page, 'plans')
        if tab != 'plans':
            page.locator(f'[data-admin-tab="{tab}"]').click()
            expect_tab(page, tab)
        calls_before_expiry = list(calls)
        page.evaluate("window.dispatchEvent(new CustomEvent('jt:admin-verification-required'))")
        # The account dialog refreshes /api/auth/me, which now reports the expiry too.
        identity['data'] = admin_account(required=True)
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        expect(page.locator('#membershipAdminContent')).to_be_hidden()
        page.locator('#membershipAdminClose').click()
        open_admin(page)
        assert calls == calls_before_expiry
        page.locator('#membershipAdminVerify').click()
        page.locator('#offlineIdentityReturn').click()
        page.wait_for_url('http://fixture.test/video?keep=fixture')
        expect(page.locator('#membershipAdmin')).to_be_visible()
        expect_tab(page, tab)
        expect(page.locator('#membershipAdminVerification')).to_be_hidden()
        assert len(return_paths) == 1
        destination = urlparse(return_paths[0])
        assert destination.path == '/video'
        assert parse_qs(destination.query) == {'keep': ['fixture'], 'admin': [tab]}
        assert len(page.context.pages) == 1
        assert len(calls) > len(calls_before_expiry)
    finally:
        page.close()


def test_gate_identifies_workbench_admin_and_preserves_admin_destination(browser):
    page = browser.new_page()
    identity = {'data': {'enabled': True, 'authenticated': False,
                         'login_method': 'access_code', 'admin_login_available': True}}
    calls = serve_admin(page, identity)
    page.route('**/api/auth/login?*', lambda route: route.fulfill(body='Offline identity login'))
    try:
        page.goto('http://fixture.test/video?keep=fixture')
        expect(page.locator('#accountAdminLogin')).to_have_text('改用管理员账号登录')  # 2026-11-11: secondary link, studio v2 login page
        page.locator('#accountAdminLogin').click()
        page.wait_for_url('**/api/auth/login?*')
        return_to = parse_qs(urlparse(page.url).query)['return_to'][0]
        destination = urlparse(return_to)
        assert destination.path == '/video'
        assert parse_qs(destination.query) == {'keep': ['fixture'], 'admin': ['plans']}
        assert calls == []
    finally:
        page.close()


@pytest.mark.parametrize('tab', ADMIN_TABS)
def test_member_cannot_open_admin_by_query(browser, tab):
    page = browser.new_page()
    calls = serve_admin(page, {'data': account()})
    try:
        page.goto(f'http://fixture.test/video?keep=fixture&admin={tab}')
        expect(page.locator('#wfForm textarea')).to_be_visible()
        expect(page.locator('#membershipAdminOpen')).to_have_count(0)
        expect(page.locator('#membershipAdmin')).to_have_count(0)
        assert page.url == 'http://fixture.test/video?keep=fixture'
        assert calls == []
    finally:
        page.close()


def test_admin_api_403_clears_issued_code_and_stops_management_requests(browser):
    page = browser.new_page()
    identity = {'data': admin_account()}
    calls = serve_admin(page, identity)

    def issue_code(route):
        if route.request.method == 'POST':
            route.fulfill(json={'codes': [{'id': 'code-a', 'code': ISSUED_CODE}]})
        else:
            route.fulfill(json={'codes': []})

    page.route('**/api/admin/membership/access-codes*', issue_code)
    def verification_expired(route):
        # The account dialog refreshes /api/auth/me, which reports the same expiry.
        identity['data'] = admin_account(required=True)
        route.fulfill(status=403, json={'code': 'admin_verification_required', 'error': '请重新验证管理员身份'})

    page.route('**/api/admin/membership/users?*', verification_expired)
    try:
        page.goto('http://fixture.test/video')
        open_admin(page)
        expect_tab(page, 'plans')
        page.locator('[data-admin-tab=codes]').click()
        expect_tab(page, 'codes')
        page.locator('#adminCodeForm button[type=submit]').click()
        expect(page.locator('#adminIssuedCodes')).to_have_value(ISSUED_CODE)
        expect(page.locator('#membershipAdminStatus')).to_contain_text('已生成')
        page.locator('[data-admin-tab=users]').click()
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        expect(page.locator('#membershipAdminContent')).to_be_hidden()
        assert page.locator('#membershipAdminOpen').evaluate('el => !el.hidden')
        assert_no_plaintext_code(page)
        count = len(calls)
        page.locator('#membershipAdminClose').click()
        open_admin(page)
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        assert len(calls) == count
        assert_no_plaintext_code(page)
    finally:
        page.close()


@pytest.mark.parametrize('boundary', ['verification_expiry', 'dialog_close_reopen'])
def test_late_issued_code_cannot_reappear_after_boundary(browser, boundary):
    page = browser.new_page()
    serve_admin(page, {'data': admin_account()})
    pending = []

    def issue_code(route):
        if route.request.method == 'POST':
            pending.append(route)
        else:
            route.fulfill(json={'codes': []})

    page.route('**/api/admin/membership/access-codes*', issue_code)
    try:
        page.goto('http://fixture.test/video')
        open_admin(page)
        expect_tab(page, 'plans')
        page.locator('[data-admin-tab=codes]').click()
        expect_tab(page, 'codes')
        with page.expect_request(lambda request: request.method == 'POST'
                                 and request.url.endswith('/api/admin/membership/access-codes')):
            page.locator('#adminCodeForm button[type=submit]').click()
        expect(page.locator('#adminCodeForm button[type=submit]')).to_be_disabled()
        assert len(pending) == 1
        if boundary == 'verification_expiry':
            page.evaluate("window.dispatchEvent(new CustomEvent('jt:admin-verification-required'))")
            expect(page.locator('#membershipAdminVerification')).to_be_visible()
        else:
            page.locator('#membershipAdminClose').click()
            expect(page.locator('#membershipAdmin')).to_be_hidden()
            open_admin(page)
            expect_tab(page, 'codes')
        with page.expect_response(lambda response: response.request.method == 'POST'
                                  and response.url.endswith('/api/admin/membership/access-codes')) as completed:
            pending.pop().fulfill(json={'codes': [{'id': 'code-a', 'code': ISSUED_CODE}]})
        completed.value.finished()
        # Check after the response body and a rendering cycle, so an assertion
        # cannot pass merely because the delayed fetch has not resumed yet.
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        assert_no_plaintext_code(page)
        if boundary == 'verification_expiry':
            expect(page.locator('#membershipAdminContent')).to_be_hidden()
        else:
            expect_tab(page, 'codes')
            assert_no_plaintext_code(page)
    finally:
        for route in pending:
            route.abort()
        page.close()


@pytest.mark.parametrize('width', [320, 390])
def test_mobile_admin_tabs_remain_usable_without_horizontal_overflow(browser, width, tmp_path):
    page = browser.new_page(viewport={'width': width, 'height': 844}, reduced_motion='reduce')
    serve_admin(page, {'data': admin_account()})
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountOpen')).to_be_in_viewport()
        assert page.locator('.topbar-tools #membershipAdminOpen').count() == 0
        page.locator('#accountOpen').click()
        expect(page.locator('#accountDialog #membershipAdminOpen')).to_be_in_viewport()
        page.locator('#accountDialog #membershipAdminOpen').click()
        expect(page.locator('#accountDialog')).to_be_hidden()
        expect_tab(page, 'plans')
        for tab in ADMIN_TABS:
            button = page.locator(f'[data-admin-tab="{tab}"]')
            button.click()
            expect_tab(page, tab)
            expect(button).to_be_in_viewport()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#membershipAdmin').evaluate('''el => {
                const rect = el.getBoundingClientRect();
                return rect.left >= 0 && rect.right <= innerWidth + 1
                    && el.scrollWidth <= el.clientWidth + 1;
            }'''), (width, tab)
            assert page.locator('.admin-tabs').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(tmp_path / f'admin-entry-{width}.png'))
    finally:
        page.close()
