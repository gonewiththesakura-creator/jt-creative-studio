"""Browser integration with every network request intercepted; never calls a provider."""
import json
import ast
import hashlib
import subprocess
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def test_packaging_preserves_business_functions_and_backend_contracts():
    subprocess.run(['node','frontend/verify-contracts.mjs'],cwd=ROOT,check=True,capture_output=True)
    baseline=subprocess.check_output(['git','show','4035030:server.py'],cwd=ROOT).decode('utf8')
    current_source=(ROOT/'server.py').read_text(encoding='utf8')
    def business(source):
        tree=ast.parse(source)
        for node in tree.body:
            if isinstance(node,ast.ClassDef) and node.name=='Handler':
                node.body=[item for item in node.body if not isinstance(item,ast.FunctionDef) or item.name not in ('do_GET','_send_static')]
        return ast.dump(tree,include_attributes=False)
    assert business(baseline)==business(current_source)
    assert subprocess.check_output(['git','show','4035030:config.json'],cwd=ROOT).replace(b'\r\n',b'\n')==(ROOT/'config.json').read_bytes().replace(b'\r\n',b'\n')


def test_all_packaged_resources_are_content_addressed():
    manifest=json.loads((ROOT/'static/app-manifest.json').read_text(encoding='utf8'))
    for url in manifest['assets']:
        file=ROOT/url.lstrip('/')
        assert hashlib.sha256(file.read_bytes()).hexdigest()[:12]==file.name.split('.')[-2]


def serve_page(page, legacy=False, requests=None, block_scene=False):
    requests = requests if requests is not None else []
    def serve(route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        requests.append((request.method, path, request.resource_type))
        if request.method != 'GET':
            return route.fulfill(status=503,json={'error':'offline: paid requests forbidden'})
        if path == '/api/workflows':
            return route.fulfill(json=[{'id':'fixture-'+kind,'kind':kind,'backend':'runninghub','name':'测试工作流',
                'rh_media':{},'rh_params':{'prompt':{'type':'text','label':'提示词','default':'测试'}}}
                for kind in ('video','rh_workflow')])
        if path.startswith('/api/'):
            return route.fulfill(json=[])
        if path=='/favicon.ico':return route.fulfill(status=204)
        if block_scene and ('workbench.' in path or path.endswith('/workbench.js')):return route.abort()
        if path in ('/','/realism','/video'):
            file=ROOT/'static'/({'/':'index.html','/realism':'realism.html','/video':'video.html'}[path] if legacy else 'app.html')
        else:file=ROOT/path.lstrip('/')
        if file.resolve().is_relative_to(ROOT/'static') and file.is_file():
            return route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
        return route.fulfill(status=404)
    page.route('**/*',serve)
    return requests


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        yield browser
        browser.close()


def current(page):
    return page.locator('.page-host:not([hidden])')


@pytest.mark.parametrize('width',[390,1440])
def test_keep_alive_navigation_and_back_forward(browser,width):
    page=browser.new_page(viewport={'width':width,'height':900})
    requests=serve_page(page)
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto('http://fixture.test/')
        expect(current(page).locator('#genApiBtn')).to_be_enabled()
        current(page).locator('input[name=promptModeRadio][value=manual]').check()
        current(page).locator('#manualPositive').fill('状态保留测试')
        current(page).locator('#genSeed').fill('123456')
        page.locator('body > .app-shell > .topbar a[href="/realism"]').click()
        expect(current(page).locator('#workflowSelect')).to_be_visible()
        # DOM state, including custom properties and file objects, must retain identity.
        current(page).evaluate('(host)=>host.shadowRoot.querySelector("#workflowSelect").dataset.kept="realism"')
        page.locator('body > .app-shell > .topbar a[href="/video"]').click()
        expect(current(page).locator('#wfForm textarea')).to_be_visible()
        current(page).locator('#wfForm textarea').fill('视频参数保留')
        page.locator('body > .app-shell > .topbar a[href="/"]').click()
        expect(current(page).locator('#manualPositive')).to_have_value('状态保留测试')
        expect(current(page).locator('#genSeed')).to_have_value('123456')
        page.go_back();expect(current(page).locator('#wfForm textarea')).to_have_value('视频参数保留')
        page.go_back();expect(current(page).locator('#workflowSelect')).to_have_attribute('data-kept','realism')
        page.go_forward();expect(current(page).locator('#wfForm textarea')).to_have_value('视频参数保留')
        assert len([r for r in requests if r[2]=='document'])==1
        assert len([r for r in requests if r[1]=='/api/workflows'])==1
        assert not [r for r in requests if r[0]!='GET']
        assert not errors, errors
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    finally:page.close()


@pytest.mark.parametrize('path',['/','/realism','/video'])
def test_direct_route_refresh_and_scene_failure(browser,path):
    page=browser.new_page(reduced_motion='reduce')
    serve_page(page,block_scene=True)
    try:
        page.goto('http://fixture.test'+path)
        expect(current(page).locator('.creation-pane')).to_be_visible()
        page.reload()
        expect(current(page).locator('.creation-pane')).to_be_visible()
        assert page.evaluate('document.body.dataset.page')==path
        assert page.locator('iframe').count()==0
    finally:page.close()


def test_creator_loads_only_selected_style_then_switches(browser):
    page=browser.new_page();requests=serve_page(page,block_scene=True)
    try:
        page.goto('http://fixture.test/')
        expect(current(page).locator('#genApiBtn')).to_be_enabled()
        styles=[r[1] for r in requests if '/assets/style-' in r[1]]
        assert len(styles)==1,styles
        assert not any('style-configs.' in r[1] for r in requests)
        current(page).locator('[data-style=graphic]').click()
        expect(current(page).locator('[data-style=graphic]')).to_have_class('active')
        assert len([r for r in requests if '/assets/style-' in r[1]])==2
    finally:page.close()


def test_task_recovery_keeps_polling_when_page_is_hidden_without_resubmit(browser):
    page=browser.new_page();requests=serve_page(page)
    page.add_init_script("sessionStorage.setItem('jt-active-main-api','mock-running')")
    terminal=False;polls=[]
    def status(route):
        polls.append(True)
        route.fulfill(json={'id':'mock-running','generation_backend':'api','status':'error' if terminal else 'running',
            'provider_status':'API_ERROR' if terminal else 'API_GENERATING','created':1,'error':'离线模拟失败','elapsed':1,'images':[]})
    page.route('**/api/job/mock-running',status)
    try:
        page.goto('http://fixture.test/')
        expect(current(page).locator('#genApiBtn')).to_have_attribute('aria-busy','true')
        page.locator('body > .app-shell > .topbar a[href="/video"]').click()
        expect(current(page).locator('#wfForm')).to_be_visible()
        terminal=True
        page.wait_for_function("sessionStorage.getItem('jt-active-main-api')===null",timeout=15000)
        page.locator('body > .app-shell > .topbar a[href="/"]').click()
        expect(current(page).locator('#genApiBtn')).to_be_enabled()
        expect(current(page).locator('#genApiBtn')).to_contain_text('生成失败')
        assert len(polls)>=2
        assert not [r for r in requests if r[0]!='GET']
    finally:page.close()


def test_static_routes_and_immutable_headers_over_real_local_http():
    import importlib.util
    import threading
    import urllib.request
    spec=importlib.util.spec_from_file_location('shell_http',ROOT/'server.py')
    panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)
    class Handler(panel.Handler):
        def _upload_session(self,create=False):return ('test',None)
        def log_message(self,*args):pass
    server=panel.BoundedHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for route in ['/','/realism','/video']:
            with opener.open(f'http://127.0.0.1:{server.server_port}'+route,timeout=5) as response:
                assert b'pageRoot' in response.read()
                assert 'no-cache' in response.headers['Cache-Control']
        manifest=json.loads((ROOT/'static/app-manifest.json').read_text(encoding='utf8'))
        for route in [manifest['main'],manifest['pages']['/']['markup'],manifest['pages']['/']['css']]:
            with opener.open(f'http://127.0.0.1:{server.server_port}'+route,timeout=5) as response:
                assert response.headers['Cache-Control']=='public, max-age=31536000, immutable'
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_scoped_api_settings_and_shared_appearance(browser):
    page=browser.new_page();serve_page(page)
    try:
        page.goto('http://fixture.test/')
        expect(current(page).locator('#genApiBtn')).to_be_enabled()
        current(page).locator('#apiDrawerOpen').click()
        expect(current(page).locator('#apiModel')).to_be_visible()
        current(page).locator('#apiModel').select_option('gpt-image-2')
        page.keyboard.press('Escape')
        expect(current(page).locator('#apiDrawer')).to_be_hidden()
        expect(page.locator('#appearanceOpen')).to_be_visible()
        page.locator('#appearanceOpen').click()
        page.locator('input[type=number][data-appearance=glassBlur]').fill('7')
        page.locator('input[type=number][data-appearance=glassOpacity]').fill('0.32')
        page.keyboard.press('Escape')
        assert current(page).locator('.creation-pane').evaluate('(el)=>getComputedStyle(el).backdropFilter')=='none'
        assert '0.32' in current(page).locator('.creation-pane').evaluate('(el)=>getComputedStyle(el).backgroundColor')
        page.locator('body > .app-shell > .topbar a[href="/video"]').click()
        page.locator('body > .app-shell > .topbar a[href="/"]').click()
        current(page).locator('#apiDrawerOpen').click()
        expect(current(page).locator('#apiModel')).to_have_value('gpt-image-2')
        page.keyboard.press('Escape')
        page.locator('body > .app-shell > .topbar #histOpen').click()
        expect(current(page).locator('#histOverlay')).to_have_class('library-overlay open')
    finally:page.close()
