"""Offline browser regressions: credential retirement and server-only uploads."""
import base64
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_app_shell import browser, serve_page
from test_access_code_browser import identity


ROOT = Path(__file__).resolve().parents[1]
SENTINEL = 'offline-retired-key-NEVER-SEND-001'


@pytest.mark.parametrize('account_id', [None, 'alice'])
def test_legacy_credentials_removed_before_account_fetch_without_reading_values(browser, account_id):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    page.add_init_script('''
        for (const storage of [localStorage, sessionStorage]) {
          for (const key of ['jt-personal-rh-key','jt-user:alice:jt-personal-rh-key','jt-user:bob%%3A2:jt-personal-rh-key']) storage.setItem(key, %s);
          storage.setItem('jt-appearance-settings-v1', 'keep-appearance');
          storage.setItem('jt-user:alice:jt-prompt-presets', 'keep-presets');
        }
        window.credentialReads=0;
        const originalGet=Storage.prototype.getItem;
        Storage.prototype.getItem=function(key) { if(String(key).endsWith('jt-personal-rh-key')) window.credentialReads++;return originalGet.call(this,key); };
        const originalFetch=window.fetch;
        window.fetch=function(...args) {
          if(String(args[0]).startsWith('/api/auth/me')) window.keysAtAuthRequest=[...Object.keys(localStorage),...Object.keys(sessionStorage)].filter(key=>key.endsWith('jt-personal-rh-key'));
          return originalFetch.apply(this,args);
        };
    ''' % json.dumps(SENTINEL))
    captured = []
    page.on('request', lambda request: captured.append((request.url, request.headers, request.post_data)))
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity(account_id)))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLoginCode') if account_id is None else page.locator('#wfForm textarea')).to_be_visible()
        assert page.evaluate('window.keysAtAuthRequest') == []
        assert page.evaluate('window.credentialReads') == 0
        assert not page.evaluate("[...Object.keys(localStorage),...Object.keys(sessionStorage)].some(key=>key.endsWith('jt-personal-rh-key'))")
        assert page.evaluate("localStorage.getItem('jt-appearance-settings-v1')") == 'keep-appearance'
        assert page.evaluate("sessionStorage.getItem('jt-user:alice:jt-prompt-presets')") == 'keep-presets'
        assert SENTINEL not in json.dumps(captured)
        assert page.locator('#personalUpload').count() == 0
        if account_id is None:
            assert not [r for r in requests if r[1] == '/api/workflows']
    finally:
        page.close()


def test_old_key_added_by_another_tab_is_removed(browser):
    context = browser.new_context(reduced_motion='reduce')
    first, second = context.new_page(), context.new_page()
    for page in (first, second):
        serve_page(page, block_scene=True)
        page.route('**/api/auth/me', lambda route: route.fulfill(json=identity()))
    try:
        first.goto('http://fixture.test/video')
        second.goto('http://fixture.test/video')
        expect(first.locator('#accountLoginCode')).to_be_visible()
        second.evaluate("localStorage.setItem('jt-personal-rh-key', 'offline-fake-key')")
        first.wait_for_function("!Object.keys(localStorage).some(key=>key.endsWith('jt-personal-rh-key'))")
    finally:
        context.close()


@pytest.mark.parametrize('member', [True, False])
def test_video_upload_never_needs_client_credentials_and_retry_reuses_chunk_receipt(browser, member):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=identity('alice') if member else {'enabled': False}))
    page.route('**/api/workflows', lambda route: route.fulfill(json=[{
        'id': 'fixture-video', 'kind': 'video', 'name': '测试视频',
        'rh_media': {'reference_image': {'type': 'image', 'label': '参考图', 'required': True}},
        'rh_params': {'prompt': {'type': 'text', 'label': '提示词', 'default': '测试'}}}]))
    counts = {'start': 0, 'chunk': 0, 'finish': 0}
    posts = []

    def upload(route):
        request = route.request
        stage = request.url.split('/api/upload-')[1].split('?')[0]
        counts[stage] += 1
        posts.append((request.url, request.headers))
        if stage == 'start':
            route.fulfill(json={'upload_id': 'offline-a'})
        elif stage == 'chunk':
            route.fulfill(json={'offset': len(request.post_data_buffer)})
        elif counts[stage] == 1:
            route.fulfill(status=503, json={'error': '离线模拟接收中断'})
        else:
            route.fulfill(json={'status': 'done', 'uploadToken': 'owned-upload-token'})

    page.route('**/api/upload-*', upload)
    try:
        page.goto('http://fixture.test/video')
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6ZQAAAABJRU5ErkJggg==')
        drop = page.locator('[data-media-key="reference_image"]')
        drop.locator('input[type=file]').set_input_files({'name': 'reference.png', 'mimeType': 'image/png', 'buffer': png})
        expect(drop.locator('.upload-retry')).to_be_visible()
        drop.locator('.upload-retry').click()
        expect(drop.locator('.fn')).to_contain_text('已上传')
        assert counts == {'start': 1, 'chunk': 1, 'finish': 2}
        assert all(url.startswith('http://fixture.test/api/upload-') and 'authorization' not in headers for url, headers in posts)
        if member:
            assert all(headers['x-csrf-token'] == 'test-csrf-alice' for _, headers in posts)
        assert not [r for r in requests if '/api/upload-direct-' in r[1]]
        assert page.locator('#personalUpload').count() == 0
        assert page.evaluate("[...Object.keys(localStorage),...Object.keys(sessionStorage)].every(key=>!key.endsWith('jt-personal-rh-key'))")
    finally:
        page.close()


def test_current_public_assets_do_not_contain_upstream_identity_or_direct_upload():
    manifest = json.loads((ROOT / 'static/app-manifest.json').read_text(encoding='utf8'))
    for url in manifest['assets']:
        path = ROOT / url.lstrip('/')
        if path.suffix not in ('.js', '.html', '.json'):
            continue
        code = path.read_text(encoding='utf8').lower()
        assert all(term not in code for term in ['runninghub', 'openapi/v2/media/upload', 'personalrhkey', 'sha256.hmac']), path.name


def test_admin_code_login_needs_verification_before_management(browser):
    page = browser.new_page(reduced_motion='reduce')
    requests = serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=dict(identity('admin', True), admin_verification_required=True, admin_verify_url='https://evil.invalid/')))
    page.route('**/api/auth/login?*', lambda route: route.fulfill(body='offline identity verification'))
    try:
        page.goto('http://fixture.test/video')
        # a28b141: the admin entry stays visible; verification happens inside the dialog.
        expect(page.locator('#membershipAdminOpen')).to_be_visible()
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdminVerify')).to_be_visible()
        expect(page.locator('#membershipAdminContent')).to_be_hidden()
        assert not [r for r in requests if r[1].startswith('/api/admin/membership/')]
        page.locator('#membershipAdminVerify').click()
        page.wait_for_url('**/api/auth/login?return_to=%2Fvideo%3Fadmin%3Dplans')
        assert page.url.startswith('http://fixture.test/')
    finally:
        page.close()


def test_admin_verification_expiry_clears_issued_secrets(browser):
    page = browser.new_page(reduced_motion='reduce')
    serve_page(page, block_scene=True)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=dict(identity('admin', True), admin_verification_required=False)))
    page.route('**/api/admin/membership/plans', lambda route: route.fulfill(json={'plans': []}))
    page.route('**/api/admin/membership/users?*', lambda route: route.fulfill(status=403, json={'code': 'admin_verification_required', 'error': '管理操作需要重新验证管理员身份'}))
    try:
        page.goto('http://fixture.test/video')
        page.locator('#membershipAdminOpen').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('')
        page.locator('#adminIssuedCodes').evaluate("el=>el.value='offline-newly-issued-code'")
        page.locator('[data-admin-tab=users]').click()
        # a28b141: expiry swaps the open dialog to its verification panel instead of closing it.
        expect(page.locator('#membershipAdminVerification')).to_be_visible()
        expect(page.locator('#membershipAdminContent')).to_be_hidden()
        expect(page.locator('#membershipAdminVerify')).to_be_visible()
        expect(page.locator('#adminIssuedCodes')).to_have_value('')
    finally:
        page.close()
