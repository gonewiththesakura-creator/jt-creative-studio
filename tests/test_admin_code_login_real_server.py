"""Administrator code login through the real server and the real built frontend (2026-11-11).

No route is mocked: the browser talks to the panel's own HTTP handler with membership enabled in
access-code mode. Codes are issued inside the test store; no provider is reachable from the fixture.
"""
import pytest
from playwright.sync_api import expect

from test_app_shell import browser
from test_membership_http import membership_env
from test_server_review_regressions import panel


@pytest.fixture
def site(membership_env):
    env = membership_env
    env.gateway.login_mode = 'access_code'
    env.gateway.origin = 'http://127.0.0.1:%d' % env.httpd.server_address[1]
    admin = env.users['admin']['id']
    plan = env.store.save_plan(admin, {'name': 'Monthly', 'duration_days': 30, 'image_units': 10, 'video_units': 3})
    env.member_code = env.store.issue_access_codes(admin, plan['id'])[0]['code']
    rotated = env.store.rotate_access_code(admin, admin, 'fixture administrator code')
    env.admin_code = rotated['code'] if isinstance(rotated.get('code'), str) else rotated['code']['code']
    return env


def sign_in(browser, site, code):
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
    page = context.new_page()
    page.goto(site.gateway.origin + '/')
    expect(page.locator('#accountLoginCode')).to_be_visible()
    # The account-login route is a secondary link; the note tells administrators to use their own code.
    expect(page.locator('#accountAdminHint')).to_contain_text('管理员')
    page.locator('#accountLoginCode').fill(code)
    page.locator('#accountLogin').click()
    expect(page.locator('#accountGate')).to_be_hidden(timeout=15000)
    expect(page.locator('#accountOpen')).to_be_visible()
    return context, page


def test_administrator_code_opens_console_without_second_verification(browser, site):
    context, page = sign_in(browser, site, site.admin_code)
    try:
        expect(page.locator('#sideAdminOpen')).to_be_visible()
        page.locator('#sideAdminOpen').click()
        expect(page.locator('#membershipAdminVerification')).to_be_hidden()
        expect(page.locator('#membershipAdminContent')).to_be_visible()
        expect(page.locator('#adminPlanCards .admin-plan')).to_have_count(1)
        expect(page.locator('#membershipAdminStatus')).to_have_text('')
        page.locator('[data-admin-tab="users"]').click()
        expect(page.locator('#adminUsersRows tr')).not_to_have_count(0)
        assert page.evaluate("fetch('/api/admin/membership/plans').then(r => r.status)") == 200
    finally:
        context.close()


def test_member_code_has_no_console_entry_and_no_admin_api(browser, site):
    context, page = sign_in(browser, site, site.member_code)
    try:
        expect(page.locator('#sideAdminOpen')).to_have_count(0)
        page.locator('#accountOpen').click()
        expect(page.locator('#accountDialog')).to_be_visible()
        expect(page.locator('#membershipAdminOpen')).to_have_count(0)
        assert page.evaluate("fetch('/api/admin/membership/plans').then(r => r.status)") == 403
    finally:
        context.close()
