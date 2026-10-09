"""Offline login animation checks, including the real existing WebGL renderer."""
import json
import pytest
from playwright.sync_api import expect

from test_app_shell import ROOT, browser, serve_page
from test_membership_browser import account, strict_csp_shell


def record_transitions(page):
    page.add_init_script('''
      window.loginPhases=[];
      new MutationObserver(()=>{
        const phase=document.body?.dataset.loginScene;
        if(phase&&window.loginPhases.at(-1)!==phase)window.loginPhases.push(phase);
      }).observe(document,{subtree:true,attributes:true,attributeFilter:['data-login-scene']});
    ''')


@pytest.mark.parametrize('width', [390, 1440])
def test_fallback_login_transition_waits_for_auth_then_runs_once(browser, tmp_path, width):
    page = browser.new_page(viewport={'width': width, 'height': 900})
    requests = serve_page(page, block_scene=True)
    strict_csp_shell(page)
    record_transitions(page)
    signed_in = {'value': False}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if signed_in['value'] else
                                                          {'enabled': True, 'authenticated': False}))
    page.route('**/api/auth/login?*', lambda route: route.fulfill(body='<body style="background:#030407;color:white">Identity fixture</body>', content_type='text/html'))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLogin')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        page.wait_for_function("() => document.body.dataset.singularity==='fallback'")
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        assert page.locator('.page-host').count() == 0
        page.locator('#accountLogin').click()
        page.wait_for_url('**/api/auth/login?*')
        assert page.evaluate("Number(sessionStorage.getItem('jt-login-transition'))>0")
        signed_in['value'] = True
        page.goto('http://fixture.test/video')
        page.wait_for_function("() => document.body.dataset.loginScene==='entering'")
        expect(page.locator('#accountGate')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        page.wait_for_function("() => parseFloat(getComputedStyle(document.querySelector('.account-gate-card')).opacity)<0.75")
        page.screenshot(path=str(tmp_path/f'login-fallback-mid-{width}.png'))
        page.wait_for_function("() => document.body.dataset.loginScene==='workbench'")
        expect(page.locator('#accountGate')).to_be_hidden()
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert page.evaluate("sessionStorage.getItem('jt-login-transition')") is None
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.evaluate('window.loginPhases')[-5:] == ['entering', 'through', 'arriving', 'revealing', 'workbench']
        assert page.evaluate("parseFloat(getComputedStyle(document.getElementById('loginSceneFallback')).opacity)") > 0
        page.reload()
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert 'entering' not in page.evaluate('window.loginPhases')
    finally:
        page.close()


def test_reduced_motion_skips_zoom_and_marker_does_not_bypass_login(browser):
    page = browser.new_page(reduced_motion='reduce')
    serve_page(page, block_scene=True)
    page.add_init_script("sessionStorage.setItem('jt-login-transition',String(Date.now()))")
    record_transitions(page)
    identity = {'authenticated': False}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if identity['authenticated'] else
                                                          {'enabled': True, 'authenticated': False}))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLogin')).to_be_visible()
        assert page.locator('.page-host').count() == 0
        assert 'entering' not in page.evaluate('window.loginPhases')
        identity['authenticated'] = True
        page.reload()
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert page.evaluate('document.body.dataset.loginScene') == 'workbench'
        assert 'entering' not in page.evaluate('window.loginPhases')
    finally:
        page.close()


@pytest.mark.parametrize('settings', [
    {'jt-singularity-paused': 'true'},
    {'jt-singularity-appearance-v1': '{"speed":0}'},
    {'jt-singularity-appearance-v1': '{"opacity":0}'},
])
def test_saved_motion_and_hidden_background_preferences_skip_entry(browser, settings):
    page = browser.new_page()
    serve_page(page, block_scene=True)
    record_transitions(page)
    page.add_init_script('''for(const [key,value] of Object.entries(%s))localStorage.setItem(key,value);
      sessionStorage.setItem('jt-login-transition',String(Date.now()));''' % json.dumps(settings))
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account()))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert 'entering' not in page.evaluate('window.loginPhases')
        if 'opacity' in settings.get('jt-singularity-appearance-v1', ''):
            assert page.locator('#loginSceneFallback').evaluate('el=>getComputedStyle(el).opacity') == '0'
    finally:
        page.close()


def test_401_after_identity_before_route_completion_does_not_reopen_workbench(browser):
    page = browser.new_page(reduced_motion='reduce')
    serve_page(page, block_scene=True)
    record_transitions(page)
    page.add_init_script("sessionStorage.setItem('jt-login-transition',String(Date.now()))")
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account()))
    page.route('**/api/expiry-fixture', lambda route: route.fulfill(status=401, json={'error': '请登录'}))
    manifest = json.loads((ROOT/'static/app-manifest.json').read_text(encoding='utf8'))
    pending = []
    page.route('http://fixture.test'+manifest['pages']['/video']['module'], lambda route: pending.append(route))
    try:
        page.goto('http://fixture.test/video')
        page.wait_for_function("() => document.body.dataset.loginScene==='waiting-entry'")
        page.wait_for_function('() => jtApp.router!==null')
        assert page.locator('.page-host').count() == 0
        api = next(url for url in manifest['assets'] if '/api.' in url)
        # A real 401 goes through the same request wrapper as every scoped page,
        # while the initial route module is still held on the network.
        assert page.evaluate('''async url=>{const api=await import(url);
            return (await api.accountFetch('/api/expiry-fixture')).status}''', api) == 401
        expect(page.locator('#accountLogin')).to_be_visible()
        assert pending
        pending.pop().fulfill(body=(ROOT/manifest['pages']['/video']['module'].lstrip('/')).read_bytes(), content_type='text/javascript')
        page.wait_for_function("() => document.body.dataset.page==='/video'")
        expect(page.locator('body > .app-shell')).to_be_hidden()
        expect(page.locator('#accountLogin')).to_be_visible()
        assert page.evaluate('document.body.dataset.loginScene') == 'login'
        assert 'entering' not in page.evaluate('window.loginPhases')
    finally:
        page.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_real_black_hole_reuses_one_renderer_from_gate_to_workbench(browser, tmp_path, width):
    graphics_browser = browser.browser_type.launch(headless=True, args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = graphics_browser.new_page(viewport={'width': width, 'height': 900})
    # One rendered frame is enough to check the visual transition without
    # software-GPU throughput influencing animation and screenshot timing.
    page.add_init_script("localStorage.setItem('jt-singularity-paused','true')")
    requests = serve_page(page)
    strict_csp_shell(page)
    record_transitions(page)
    identity = {'authenticated': False}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if identity['authenticated'] else
                                                          {'enabled': True, 'authenticated': False}))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLogin')).to_be_visible()
        page.wait_for_function("() => document.body.dataset.singularity==='ready'", timeout=60000)
        page.wait_for_function("() => parseFloat(getComputedStyle(document.getElementById('singularityCanvas')).opacity)>.7")
        assert page.evaluate('jtApp.metrics.renderers') == 1
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        page.screenshot(path=str(tmp_path/f'login-webgl-{width}.png'))
        # The renderer remains paused for software-GPU test throughput, while
        # the saved user preference is cleared so this case exercises entry.
        page.evaluate("localStorage.removeItem('jt-singularity-paused')")
        page.evaluate("sessionStorage.setItem('jt-login-transition',String(Date.now()))")
        # Trigger the existing retry control so the same document retains
        # the exact renderer created behind its unauthenticated gate.
        identity['authenticated'] = True
        page.locator('#accountRetry').evaluate('button=>button.click()')
        page.wait_for_function("() => document.body.dataset.loginScene==='entering'", timeout=15000)
        page.wait_for_function("() => parseFloat(getComputedStyle(document.querySelector('.account-gate-card')).opacity)<.65")
        transforms = page.locator('#singularityCanvas').evaluate("canvas=>getComputedStyle(canvas).transform")
        assert transforms != 'none'
        page.screenshot(path=str(tmp_path/f'login-webgl-mid-{width}.png'))
        page.wait_for_function("() => document.body.dataset.loginScene==='workbench'")
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert page.locator('#singularityCanvas').count() == 1
        assert page.evaluate('jtApp.metrics.renderers') == 1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/f'workbench-webgl-{width}.png'))
        assert not errors
    finally:
        graphics_browser.close()
