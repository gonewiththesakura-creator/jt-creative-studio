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
        browser = driver.chromium.launch(headless=True)
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
