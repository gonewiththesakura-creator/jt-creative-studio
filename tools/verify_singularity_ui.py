"""Offline browser check of the real pages. All provider routes are mocked."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence' / 'singularity'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        for route_name in ('index', 'realism', 'video'):
            for width in (390, 1440):
                page = browser.new_page(viewport={'width':width, 'height':900})
                errors, posts = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
                def serve(route):
                    path = unquote(urlparse(route.request.url).path)
                    if route.request.method == 'POST':
                        posts.append(path)
                        return route.fulfill(status=503,json={'error':'offline test: submissions blocked'})
                    if path == '/api/workflows':
                        return route.fulfill(json=[{'id':'fixture-'+kind,'kind':kind,'backend':'runninghub',
                            'name':'素材创作测试','desc':'用于离线验证控件显示，不提交任务。',
                            'rh_media':{'image':{'type':'image','label':'参考图片','required':True}},
                            'rh_params':{'prompt':{'type':'text','label':'创作提示词','required':True,'default':'描述你的画面'}}}
                            for kind in ('video','rh_workflow')])
                    if path.startswith('/api/'):
                        return route.fulfill(json=[])
                    if path == '/favicon.ico':
                        return route.fulfill(status=204)
                    route_files = {'/':f'static/{route_name}.html','/realism':'static/realism.html','/video':'static/video.html'}
                    file = ROOT / route_files.get(path,path.lstrip('/'))
                    if file.resolve().is_relative_to((ROOT/'static').resolve()) and file.is_file():
                        return route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
                    return route.fulfill(status=404)
                page.route('**/*', serve)
                page.goto('http://fixture.test/')
                page.wait_for_function("document.body.dataset.singularity === 'ready'", timeout=90000)
                page.locator('#singularityMotion').click()
                expect(page.locator('#singularityMotion')).to_have_attribute('aria-pressed','true')
                expect(page.locator('.creation-pane')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUT/f'{route_name}-{width}.png'))
                page.locator('#singularityFocus').click()
                assert page.locator('.app-shell').evaluate('(node)=>node.inert')
                page.keyboard.press('Escape')
                expect(page.locator('#singularityFocus')).to_be_focused()
                assert not page.locator('.app-shell').evaluate('(node)=>node.inert')
                if route_name == 'realism':
                    expect(page.locator('.control-title').first).to_be_visible()
                    assert page.locator('.control-title').first.evaluate('(el)=>getComputedStyle(el).color') == 'rgb(209, 199, 189)'
                if route_name == 'index':
                    page.locator('#apiDrawerOpen').click()
                    expect(page.locator('#apiModel')).to_be_visible()
                    page.locator('#apiModel').select_option('gpt-image-2')
                    page.locator('label.api-ratio-option').filter(has=page.locator('input[value="16:9"]')).click()
                    expect(page.locator('input[name=apiRatio][value="16:9"]')).to_be_checked()
                    page.screenshot(path=str(OUT/f'api-settings-{width}.png'))
                    page.keyboard.press('Escape')
                    page.locator('input[name=promptModeRadio][value=manual]').check()
                    page.locator('#manualPositive').fill('测试提示词，不提交任务')
                    expect(page.locator('#manualPositive')).to_have_value('测试提示词，不提交任务')
                assert not errors, errors
                assert not posts, posts
                report.append({'page':route_name,'width':width,'renderer':'ready','errors':errors,'paid_requests':0})
                page.close()
        # A WebGL failure must leave all generation controls operable.
        page = browser.new_page()
        page.route('**/*', serve)
        page.add_init_script("HTMLCanvasElement.prototype.getContext = () => null")
        page.goto('http://fixture.test/')
        page.wait_for_function("document.body.dataset.singularity === 'fallback'")
        expect(page.locator('.creation-pane')).to_be_visible()
        expect(page.locator('#singularityFocus')).to_be_disabled()
        page.close()
        page = browser.new_page()
        def shader_failure(route):
            if urlparse(route.request.url).path.endswith('/shaders.js'):
                return route.fulfill(content_type='application/javascript',body='export const vertexShader="INVALID GLSL"; export const fragmentShader="INVALID GLSL";')
            return serve(route)
        page.route('**/*', shader_failure)
        page.goto('http://fixture.test/')
        page.wait_for_function("document.body.dataset.singularity === 'fallback'")
        expect(page.locator('.creation-pane')).to_be_visible()
        expect(page.locator('#singularityFocus')).to_be_disabled()
        browser.close()
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
