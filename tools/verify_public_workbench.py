"""Read-only Chromium smoke check; aborts every non-GET/HEAD request."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://8.210.125.65:8189')
    parser.add_argument('--output', type=Path, default=Path('evidence/public-workbench'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            for width, height in ((390, 844), (1440, 900)):
                for route, name in (('/', 'creator'), ('/video', 'video'), ('/realism', 'realism')):
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    errors, blocked = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def read_only(request):
                        if request.request.method not in ('GET', 'HEAD'):
                            blocked.append(request.request.url)
                            return request.abort()
                        return request.continue_()
                    page.route('**/*', read_only)
                    try:
                        response = page.goto(args.base.rstrip('/') + route, wait_until='domcontentloaded', timeout=45000)
                        assert response.status == 200, response.status
                        page.wait_for_function("!document.querySelector('.config-loading')", timeout=45000)
                        if name == 'creator':
                            page.wait_for_function('styleDataReady && stylePreview.complete && stylePreview.naturalWidth > 0', timeout=45000)
                            assert page.locator('.creation-footer #genApiBtn').count() == 1
                            assert page.locator('#apiDrawer #genApiBtn, [data-api-progress], #apiDrawerStatus').count() == 0
                            page.locator('#apiDrawerOpen').click()
                            page.wait_for_function("getComputedStyle(apiDrawer).opacity === '1'")
                            geometry = page.evaluate('''() => {
                                const p=apiDrawer.getBoundingClientRect(),t=apiDrawerOpen.getBoundingClientRect();
                                return {top:p.top,bottom:p.bottom,right:p.right,left:p.left,triggerTop:t.top};
                            }''')
                            assert geometry['top'] >= 7 and geometry['bottom'] <= geometry['triggerTop'] - 7, geometry
                            assert geometry['left'] >= 0 and geometry['right'] <= width + 1, geometry
                            assert not page.locator('.library-overlay.open').count()
                        else:
                            page.wait_for_function("document.querySelector('textarea,input,select') !== null")
                            geometry = None
                        layout = page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
                            backgroundLayers:document.querySelectorAll('.app-background').length,
                            inputs:document.querySelectorAll('textarea,input,select').length,
                            loadedImages:[...document.images].filter(i=>i.complete&&i.naturalWidth>0).length})''')
                        assert layout['scrollWidth'] <= width + 1, layout
                        assert layout['backgroundLayers'] == 1, layout
                        assert not errors, errors
                        assert not blocked, blocked
                        screenshot = f'{name}-{width}x{height}.png'
                        page.screenshot(path=str(args.output / screenshot))
                        results.append({'page':route,'viewport':[width,height],'http_status':response.status,
                            'layout':layout,'popover':geometry,'page_errors':errors,'blocked_writes':blocked,'screenshot':screenshot})
                        print(json.dumps(results[-1]), flush=True)
                    finally:
                        page.close()
        finally:
            browser.close()
    (args.output / 'checks.json').write_text(json.dumps({'status':'PASS','checks':results}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
