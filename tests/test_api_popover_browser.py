"""Real browser geometry without external network, credentials or shared profiles."""
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as driver:
        # These tests cover business-state timing and popover geometry, not GPU
        # throughput. The scene fallback retains the real appearance adapter;
        # full WebGL/motion coverage lives in verify_singularity_{ui,shader}.py.
        browser = driver.chromium.launch(headless=True, args=['--disable-webgl'])
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize('width,height', [(390, 844), (1280, 720), (1440, 900)])
def test_api_popover_stays_visible_and_operable_in_real_browser(browser, width, height):
    page = browser.new_page(viewport={'width': width, 'height': height})
    def serve(route):
        path = unquote(urlparse(route.request.url).path)
        if path.startswith('/api/'):
            return route.fulfill(json=[])
        file = ROOT / ('static/index.html' if path == '/' else path.lstrip('/'))
        if file.resolve().is_relative_to((ROOT/'static').resolve()) and file.is_file():
            return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
        return route.fulfill(status=404)
    page.route('**/*', serve)
    try:
        page.goto('http://fixture.test/')
        expect(page.locator('.creation-footer #genApiBtn')).to_be_visible()
        expect(page.locator('#apiDrawer #genApiBtn')).to_have_count(0)
        expect(page.locator('[data-api-progress], #apiDrawerStatus')).to_have_count(0)
        trigger = page.locator('#apiDrawerOpen')
        trigger.scroll_into_view_if_needed()
        before_scroll = page.evaluate('scrollY')
        trigger.click()
        expect(page.locator('#apiDrawer')).to_be_visible()
        page.wait_for_function("getComputedStyle(apiDrawer).opacity === '1'")
        layout = page.evaluate("""() => {
            const rect = ({top,right,bottom,left})=>({top,right,bottom,left});
            return {panel:rect(apiDrawer.getBoundingClientRect()),trigger:rect(apiDrawerOpen.getBoundingClientRect()),
                pane:rect(document.querySelector('.creation-pane').getBoundingClientRect()),
                width:innerWidth,scrollWidth:document.documentElement.scrollWidth,pageY:scrollY,active:document.activeElement.id};
        }""")
        assert layout['panel']['top'] >= max(8, layout['pane']['top'] + 8) - 1
        assert layout['panel']['bottom'] <= layout['trigger']['top'] - 7
        assert layout['panel']['left'] >= 0
        assert layout['panel']['right'] <= layout['width'] + 1
        assert layout['scrollWidth'] <= layout['width']
        assert layout['active'] == 'apiModel'
        assert abs(layout['pageY'] - before_scroll) <= 1
        page.evaluate('apiDrawer.scrollTop=apiDrawer.scrollHeight')
        assert page.evaluate('apiDrawer.scrollTop+apiDrawer.clientHeight >= apiDrawer.scrollHeight-1')
        page.keyboard.press('Escape')
        expect(page.locator('#apiDrawer')).to_be_hidden()
        expect(trigger).to_be_focused()
        if os.getenv('CAPTURE_BROWSER_EVIDENCE') and width in (390,1440):
            trigger.click()
            page.wait_for_function("getComputedStyle(apiDrawer).opacity === '1'")
            (ROOT/'evidence').mkdir(exist_ok=True)
            page.screenshot(path=str(ROOT/'evidence'/f'api-popover-{width}x{height}.png'))
    finally:
        page.close()


def test_api_button_displays_progress_and_terminal_states_without_duplicate_cards(browser):
    page = browser.new_page()
    def serve(route):
        path = unquote(urlparse(route.request.url).path)
        if path.startswith('/api/'):
            return route.fulfill(json=[])
        file = ROOT / ('static/index.html' if path == '/' else path.lstrip('/'))
        if file.resolve().is_relative_to((ROOT/'static').resolve()) and file.is_file():
            return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
        return route.fulfill(status=404)
    page.route('**/*', serve)
    try:
        page.goto('http://fixture.test/')
        button = page.locator('#genApiBtn')
        for job, label in [
            ({'status':'running','provider_status':'SUBMITTING'}, '提交中'),
            ({'status':'running','provider_status':'API_GENERATING'}, '生成中'),
            ({'status':'running','provider_status':'API_FITTING_RESULT'}, '整理图片'),
            ({'status':'done','provider_status':'API_DONE'}, '已完成'),
            ({'status':'error','provider_status':'API_ERROR','error':'图片下载失败'}, '生成失败'),
            ({'status':'cancelled','provider_status':''}, '已取消'),
            ({'status':'recovering','provider_status':''}, '查询任务中'),
        ]:
            page.evaluate('(job)=>startApiProgress(job)', job)
            expect(button).to_contain_text(label)
            expect(page.locator('[data-api-progress]')).to_have_count(0)
            expect(page.locator('#genApiStatus')).to_be_hidden()
            expect(page.locator('#genCloudBtn')).to_contain_text('云端')
            expect(page.locator('#genLocalBtn')).to_contain_text('本地')
        page.evaluate('clearInterval(apiProgressTimer)')
        page.evaluate("pauseApiProgress('点击继续查询原任务')")
        expect(button).to_contain_text('查询中断 · 继续查询')
        expect(button).to_have_attribute('aria-busy','false')
    finally:
        page.close()


def test_uncertain_submission_keeps_original_request_after_prompt_change_and_expiry(browser):
    page = browser.new_page()
    submissions = []
    def serve(route):
        path = unquote(urlparse(route.request.url).path)
        if path == '/api/generate':
            submissions.append(route.request.post_data_json)
            if len(submissions) <= 2:
                return route.fulfill(status=503, json={'error':'response lost after acceptance'})
            return route.fulfill(json={'job_id':'accepted-once'})
        if path == '/api/job/accepted-once':
            return route.fulfill(json={'id':'accepted-once','status':'done','generation_backend':'api','provider_status':'API_DONE','elapsed':1,'images':[]})
        if path.startswith('/api/'):
            return route.fulfill(json=[])
        file = ROOT / ('static/index.html' if path == '/' else path.lstrip('/'))
        if file.resolve().is_relative_to((ROOT/'static').resolve()) and file.is_file():
            return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
        return route.fulfill(status=404)
    page.route('**/*', serve)
    try:
        page.goto('http://fixture.test/')
        expect(page.locator('#genApiBtn')).to_be_enabled()
        page.evaluate("promptMode.value='manual';manualPositive.value='original portrait'")
        page.locator('#genApiBtn').click()
        expect(page.locator('#genApiBtn')).to_contain_text('提交待确认 · 继续查询')
        expect(page.locator('#genApiBtn')).to_have_attribute('aria-busy','false')
        page.evaluate("""() => {
            manualPositive.value='different portrait';
            const key=pendingCreatorKey('api'),saved=JSON.parse(localStorage.getItem(key));
            saved.created=1;localStorage.setItem(key,JSON.stringify(saved));
        }""")
        page.locator('#genApiBtn').click()
        expect(page.locator('#genApiBtn')).to_contain_text('已完成')
        assert len(submissions) == 3
        assert submissions[0] == submissions[1] == submissions[2]
        assert page.evaluate("localStorage.getItem(pendingCreatorKey('api'))") is None
    finally:
        page.close()


def test_rejected_api_submission_keeps_previous_image_and_other_channels_available(browser):
    page = browser.new_page()
    submissions = []
    def serve(route):
        path = unquote(urlparse(route.request.url).path)
        if path == '/api/generate':
            submissions.append(route.request.post_data_json)
            return route.fulfill(status=429, json={'error':'API生成次数已达上限，请稍后重试','code':'billable_quota_exceeded','backend':'api','retry_after':30})
        if path.startswith('/api/'):
            return route.fulfill(json=[])
        file = ROOT / ('static/index.html' if path == '/' else path.lstrip('/'))
        if file.resolve().is_relative_to((ROOT/'static').resolve()) and file.is_file():
            return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
        return route.fulfill(status=404)
    page.route('**/*', serve)
    try:
        page.goto('http://fixture.test/')
        expect(page.locator('#genApiBtn')).to_be_enabled()
        page.evaluate("""() => {
            promptMode.value='manual';manualPositive.value='test portrait';
            addResult({id:'previous',generation_backend:'api',images:[{url:'/static/previous.png'}]},genApiResult);
        }""")
        page.locator('#genApiBtn').click()
        expect(page.locator('#apiActionError')).to_have_text('API生成次数已达上限，请稍后重试')
        expect(page.locator('#genApiBtn')).to_contain_text('生成失败')
        expect(page.locator('#genApiResult .gallery-main img')).to_have_attribute('src','/static/previous.png')
        expect(page.locator('#genCloudBtn')).to_be_enabled()
        expect(page.locator('#genLocalBtn')).to_be_enabled()
        expect(page.locator('#genApiBtn')).to_be_enabled()
        assert len(submissions) == 1
        assert submissions[0]['generation_backend'] == 'api'
        assert page.evaluate("localStorage.getItem(pendingCreatorKey('api'))") is None
        # A retained accepted job must be queried, never submitted as another job.
        page.route('**/api/job/retained', lambda route: route.fulfill(json={'id':'retained','status':'done','generation_backend':'api','provider_status':'API_DONE','elapsed':2,'images':[]}))
        page.evaluate("rememberActiveJob('api','retained')")
        page.locator('#genApiBtn').click()
        expect(page.locator('#genApiBtn')).to_contain_text('已完成')
        assert len(submissions) == 1
    finally:
        page.close()
