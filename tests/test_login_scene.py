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
    documents=[]
    page.on('request',lambda request:documents.append(request.url) if request.resource_type=='document' else None)
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if signed_in['value'] else
                                                          {'enabled': True, 'authenticated': False, 'login_method':'access_code'}))
    def login(route):
        signed_in['value'] = True
        route.fulfill(json={'ok': True})
    page.route('**/api/auth/code-login', login)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#accountLogin')).to_be_visible()
        expect(page.locator('body > .app-shell')).to_be_hidden()
        page.wait_for_function("() => document.body.dataset.singularity==='fallback'")
        assert not [r for r in requests if r[1] in ('/api/workflows', '/api/video-queue')]
        assert page.locator('.page-host').count() == 0
        assert page.locator('.login-scene-orbit').count() == 0
        page.locator('#accountLoginCode').fill('JT-LOGIN-FIXTURE')
        page.locator('#accountLogin').click()
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
        assert page.url == 'http://fixture.test/video'
        assert len(documents) == 1
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
                                                          {'enabled': True, 'authenticated': False, 'login_method':'access_code'}))
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
            assert page.evaluate("document.body.style.getPropertyValue('--appearance-opacity')") == '0'
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
    # Compile the actual shader once before starting the measured travel.
    page.add_init_script("localStorage.setItem('jt-singularity-paused','true')")
    requests = serve_page(page)
    strict_csp_shell(page)
    record_transitions(page)
    identity = {'authenticated': False}
    page.route('**/api/auth/me', lambda route: route.fulfill(json=account() if identity['authenticated'] else
                                                          {'enabled': True, 'authenticated': False, 'login_method':'access_code'}))
    def login(route):
        identity['authenticated'] = True
        route.fulfill(json={'ok': True})
    page.route('**/api/auth/code-login', login)
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
        page.evaluate("localStorage.removeItem('jt-singularity-paused')")
        page.evaluate('''() => {
            window.loginFrameGaps=[];window.travelFrames=[];let last=0;
            const sample=t=>{
                const phase=document.body.dataset.loginScene;
                if(['entering','through','arriving','revealing'].includes(phase)){
                    if(last)loginFrameGaps.push(t-last);last=t;travelFrames.push(jtApp.metrics.frames);
                }else last=0;
                if(phase!=='workbench')requestAnimationFrame(sample);
            };
            requestAnimationFrame(sample);
        }''')
        dimensions=page.locator('#singularityCanvas').evaluate('canvas=>[canvas.width,canvas.height]')
        page.locator('#accountLoginCode').fill('JT-LOGIN-FIXTURE')
        page.locator('#accountLogin').click()
        page.wait_for_function("() => document.body.dataset.loginScene==='entering'", timeout=15000)
        page.wait_for_function("() => parseFloat(getComputedStyle(document.querySelector('.account-gate-card')).opacity)<.65")
        assert page.locator('#singularityCanvas').evaluate("canvas=>getComputedStyle(canvas).transform") == 'none'
        page.wait_for_function("() => document.body.dataset.loginScene==='workbench'")
        expect(page.locator('#wfForm textarea')).to_be_visible()
        assert page.locator('#singularityCanvas').count() == 1
        assert page.evaluate('jtApp.metrics.renderers') == 1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('#singularityCanvas').evaluate('canvas=>[canvas.width,canvas.height]') == dimensions
        gaps=sorted(page.evaluate('loginFrameGaps'))
        assert len(gaps)>20, 'The lightweight transition must continue producing frames'
        assert len(set(page.evaluate('travelFrames'))) == 1, 'The heavy shader must stay frozen during travel'
        report={'width':width,'frames':len(gaps),'p50_ms':gaps[len(gaps)//2],
                'p95_ms':gaps[int(len(gaps)*.95)],'max_ms':max(gaps),
                'canvas_size':dimensions,'pixel_budget':page.evaluate('jtApp.metrics.pixelBudget')}
        (tmp_path/f'login-motion-{width}.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        page.screenshot(path=str(tmp_path/f'workbench-webgl-{width}.png'))
        assert not errors
    finally:
        graphics_browser.close()


def test_login_uses_saved_appearance_before_gpu_initialization(browser):
    settings={'offsetX':-.27,'offsetY':.17,'mobileX':.14,'mobileY':-.11,'radius':27,
              'temperature':.45,'exposure':.7,'opacity':.63,'zoom':1.32,
              'quality':.9,'speed':.4,'glassOpacity':.44,'glassBlur':7,'edge':.31}
    page=browser.new_page()
    serve_page(page,block_scene=True)
    raw=json.dumps(settings)
    page.add_init_script("localStorage.setItem('jt-singularity-appearance-v1',%s)" % json.dumps(raw))
    page.route('**/api/auth/me',lambda route:route.fulfill(json={'enabled':True,'authenticated':False,'login_method':'access_code'}))
    try:
        page.goto('http://fixture.test/')
        expect(page.locator('#accountLoginCode')).to_be_visible()
        style=page.locator('.account-gate-card').evaluate('el=>({background:getComputedStyle(el).backgroundColor,blur:getComputedStyle(el).backdropFilter})')
        assert style=={'background':'rgba(15, 16, 20, 0.44)','blur':'blur(7px)'}
        assert page.evaluate("document.body.style.getPropertyValue('--appearance-opacity')")=='0.63'
        assert page.evaluate("localStorage.getItem('jt-singularity-appearance-v1')")==raw
        assert page.locator('.login-scene-orbit').count()==0
        assert page.locator('.page-host').count()==0
    finally:page.close()
