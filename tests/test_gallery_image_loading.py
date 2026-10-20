"""Real-browser media regressions; entirely synthetic, no cloud generation."""
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'sources/gallery_image_loader.js').read_text(encoding='utf8')


@contextmanager
def gallery_server():
    metrics = {'requests': [], 'active': 0, 'peak': 0}
    counts = Counter()
    lock = threading.Lock()
    picture = BytesIO()
    Image.new('RGB', (240, 360), '#c0a77d').save(picture, format='WEBP')
    body = picture.getvalue()
    job = {'id': 'synthetic', 'generation_backend': 'cloud', 'images': [
        {'url': '/original/' + str(i), 'preview_url': '/view/' + str(i), 'thumb_url': '/thumb/' + str(i)}
        for i in range(4)]}
    css = '''body{background:#15161b;color:#e6d6b9;font:16px sans-serif;margin:20px}button{color:inherit;background:#29292d;border:1px solid #806948;border-radius:8px;padding:10px}.gallery-main{display:flex;flex-direction:column;align-items:center}.gallery-image-viewport{position:relative;display:grid;place-items:center;width:100%;height:55vh;overflow:hidden}.gallery-result-image{width:100%;height:100%;object-fit:contain}.gallery-actions{display:flex;justify-content:space-around;gap:20px;width:100%;margin:12px}.gallery-strip{display:grid;grid-template-columns:44px minmax(0,1fr) 44px;gap:8px}.gallery-thumbs{display:flex;gap:8px;overflow:auto}.gallery-thumb{flex:0 0 72px;height:68px;padding:3px}.gallery-thumb.active{border:2px solid #dbb06e}.gallery-thumb img{width:100%;height:100%;object-fit:contain}[hidden]{display:none!important}'''
    html = ('<!doctype html><meta charset="utf-8"><style>' + css + '</style>'
            '<div class="preview-stage"><div id="previewEmpty"></div><div id="result"></div></div>'
            '<script>const backendUi=()=>({label:"云端"}),creatorCoinText=()=>"",setResultTab=()=>{},api=async()=>({});'
            'const fixtureJob=' + json.dumps(job) + ';' + SOURCE
            + ';addResult(fixtureJob,document.getElementById("result"));</script>').encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/':
                self.send_response(200);self.send_header('Content-Type', 'text/html; charset=utf-8');self.end_headers();self.wfile.write(html)
                return
            if self.path == '/favicon.ico':
                self.send_response(404);self.end_headers();return
            with lock:
                counts[self.path] += 1
                number = counts[self.path]
                metrics['requests'].append(self.path)
                metrics['active'] += 1
                metrics['peak'] = max(metrics['peak'], metrics['active'])
            try:
                time.sleep(.1 if not self.path.endswith('slow') else .4)
                code = 503 if (self.path in ('/view/0', '/thumb/1') and number == 1) or self.path == '/always-busy' else 404 if self.path == '/missing' else 200
                self.send_response(code)
                self.send_header('Content-Type', 'image/webp' if code == 200 else 'text/plain')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write((b'not-an-image' if self.path == '/corrupt-once' and number == 1 else body) if code == 200 else b'retry')
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    metrics['active'] -= 1

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', metrics, counts
    finally:
        server.shutdown();server.server_close();thread.join()


def test_four_images_retry_selection_reuse_and_identity_clear(tmp_path):
    with gallery_server() as (url, metrics, counts), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 760})
        errors = [];page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.locator('.gallery-result-image')).to_be_visible()
        expect(page.locator('.gallery-thumb img:visible')).to_have_count(4)
        assert metrics['peak'] <= 2
        assert metrics['requests'][0] == '/view/0'
        assert counts['/view/0'] == counts['/thumb/1'] == 2
        assert not any(path.startswith('/original/') for path in metrics['requests'])
        assert not any(counts[f'/view/{i}'] for i in (1, 2, 3))
        before = page.locator('.gallery-image-viewport').bounding_box()
        page.get_by_role('button', name='查看结果 2', exact=True).click()
        page.get_by_role('button', name='查看结果 4', exact=True).click()
        expect(page.locator('.gallery-result-image')).to_have_attribute('alt', '结果 4')
        expect(page.locator('.gallery-result-image')).to_be_visible()
        assert page.locator('.gallery-image-viewport').bounding_box() == before
        page.get_by_role('button', name='查看结果 1', exact=True).click()
        expect(page.locator('.gallery-result-image')).to_be_visible()
        page.get_by_role('button', name='查看结果 4', exact=True).click()
        expect(page.locator('.gallery-result-image')).to_be_visible()
        assert counts['/view/0'] == 2 and counts['/view/3'] == 1
        assert page.locator('.gallery-actions a').get_attribute('href') == '/original/3'
        # Clearing the account removes every rendered object URL and discards
        # cached responses; re-entering must perform a fresh authorised fetch.
        page.evaluate("window.dispatchEvent(new CustomEvent('jt:media-clear'))")
        assert page.locator('img[src^="blob:"]').count() == 0
        page.evaluate('addResult(fixtureJob,document.getElementById("result"))')
        expect(page.locator('.gallery-result-image')).to_be_visible()
        assert counts['/view/0'] == 3
        page.set_viewport_size({'width': 320, 'height': 760})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / 'gallery-mobile.png'))
        assert not errors
        browser.close()


def test_same_account_restore_refetches_cleared_images_in_place():
    with gallery_server() as (url, metrics, counts), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 760})
        errors = [];page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        blobs = page.locator('img[src^="blob:"]')
        expect(blobs).to_have_count(5)
        page.evaluate("document.querySelector('.gallery-result-image').dataset.marker='same-element'")
        views = counts['/view/0']
        # Session expiry fires both events (api.js, then the account gate); no private bytes may remain.
        page.evaluate("dispatchEvent(new CustomEvent('jt:auth-expired'));dispatchEvent(new CustomEvent('jt:media-clear'))")
        assert blobs.count() == 0
        # The same account signed back in: the existing elements are refetched, not re-rendered.
        page.evaluate("dispatchEvent(new CustomEvent('jt:media-restore'))")
        expect(blobs).to_have_count(5)
        expect(page.locator('.gallery-result-image')).to_have_attribute('data-marker', 'same-element')
        expect(page.locator('.gallery-result-image')).to_be_visible()
        assert counts['/view/0'] == views + 1
        # A second restore has nothing left to repaint.
        page.evaluate("dispatchEvent(new CustomEvent('jt:media-restore'))")
        page.wait_for_timeout(300)
        assert counts['/view/0'] == views + 1
        assert not errors
        browser.close()


def test_retries_are_bounded_auth_failures_not_retried_and_inflight_cleared():
    with gallery_server() as (url, metrics, counts), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page();page.goto(url)
        assert page.evaluate("galleryImageLoader.load('/always-busy').then(()=>false,()=>true)")
        assert counts['/always-busy'] == 4
        assert page.evaluate("galleryImageLoader.load('/missing').then(()=>false,()=>true)")
        assert counts['/missing'] == 1
        assert page.evaluate("""async()=>{
            const img=document.createElement('img');document.body.append(img);
            const failed=await galleryImageLoader.bind(img,'/corrupt-once').then(()=>false,()=>true);
            await galleryImageLoader.bind(img,'/corrupt-once');
            return failed&&img.naturalWidth===240;
        }""")
        assert counts['/corrupt-once'] == 2
        result = page.evaluate("""async()=>{
            const before=document.querySelectorAll('img[src^="blob:"]').length;
            const request=galleryImageLoader.load('/private-slow').then(()=>false,error=>error.name==='AbortError');
            await new Promise(resolve=>setTimeout(resolve,30));galleryImageLoader.clear();
            const rejected=await request;await new Promise(resolve=>setTimeout(resolve,500));
            return {before,rejected,remaining:document.querySelectorAll('img[src^="blob:"]').length};
        }""")
        assert result['before'] > 0 and result['rejected'] and result['remaining'] == 0
        assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length') == 0
        browser.close()


def test_packaged_creator_results_fit_full_image_and_preserve_gallery_loading(tmp_path):
    requests = []
    picture = BytesIO()
    # A full-resolution portrait exposes intrinsic grid sizing; a small solid
    # fixture in the history drawer previously missed the real result crop.
    canvas = Image.new('RGB', (860, 1536), '#c0a77d')
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 859, 153), fill='#dc4646')
    draw.rectangle((0, 1382, 859, 1535), fill='#468cdc')
    canvas.save(picture, format='PNG')
    images = [{'url': '/api/result-media/test/'+str(i), 'preview_url': '/api/rh-preview/test/'+str(i)+'?size=view', 'thumb_url': '/api/rh-preview/test/'+str(i)+'?size=thumb'} for i in range(4)]
    job = {'id':'test','status':'done','generation_backend':'cloud','images':images,'style_id':'sketch','width':768,'height':1024,'batch':4,'seed':17}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-webgl'])
        page = browser.new_page(viewport={'width':1320,'height':806})
        page.add_init_script("sessionStorage.setItem('jt-active-main-cloud','test')")
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def serve(route):
            request=route.request;path=urlparse(request.url).path;requests.append((request.method,request.url))
            if request.method!='GET':return route.fulfill(status=503)
            if path=='/api/auth/me':return route.fulfill(json={'enabled':False,'authenticated':False})
            if path=='/api/jobs':return route.fulfill(json=[job])
            if path=='/api/job/test':return route.fulfill(json=job)
            if path.startswith('/api/rh-preview/'):return route.fulfill(body=picture.getvalue(),content_type='image/png',headers={'Cache-Control':'no-store'})
            if path.startswith('/api/'):return route.fulfill(json=[])
            file=ROOT/('static/app.html' if path=='/' else path.lstrip('/'))
            if file.resolve().is_relative_to(ROOT/'static') and file.is_file():return route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream')
            return route.fulfill(status=404)
        page.route('**/*',serve);page.goto('http://fixture.test/')
        host=page.locator('.page-host:not([hidden])')
        expect(host.locator('#genCloudBtn')).to_be_enabled()
        result=host.locator('#genCloudResult')

        def assert_uncropped(gallery, label):
            image=gallery.locator('.gallery-result-image')
            expect(image).to_be_visible()
            bounds=image.evaluate('''image=>{
                const imageBox=image.getBoundingClientRect(),view=image.parentElement.getBoundingClientRect();
                return {image:imageBox.toJSON(),view:view.toJSON(),fit:getComputedStyle(image).objectFit};
            }''')
            image_box, view=bounds['image'], bounds['view']
            assert bounds['fit']=='contain'
            assert image_box['top']>=view['top']-1 and image_box['bottom']<=view['bottom']+1, bounds
            assert image_box['left']>=view['left']-1 and image_box['right']<=view['right']+1, bounds
            screenshot=gallery.locator('.gallery-image-viewport').screenshot()
            preview=Image.open(BytesIO(screenshot)).convert('RGB')
            scale=min(preview.width/860,preview.height/1536)
            top=(preview.height-1536*scale)/2
            assert preview.getpixel((preview.width//2, round(top+76*scale)))==(220,70,70)
            assert preview.getpixel((preview.width//2, round(top+1459*scale)))==(70,140,220)
            (tmp_path/(label+'.png')).write_bytes(screenshot)

        for width,height in [(1320,806),(1920,1080),(320,760)]:
            page.set_viewport_size({'width':width,'height':height})
            assert_uncropped(result,'main-'+str(width))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            before=result.locator('.gallery-image-viewport').bounding_box()
            result.get_by_role('button',name='查看结果 3',exact=True).click()
            assert_uncropped(result,'selected-'+str(width))
            assert result.locator('.gallery-image-viewport').bounding_box()['height']==before['height']
            result.get_by_role('button',name='查看结果 1',exact=True).click()
        page.set_viewport_size({'width':1440,'height':900})
        page.locator('body > .app-shell > .topbar #histOpen').click()
        host.get_by_role('button',name='查看图片',exact=True).click()
        history=host.locator('#histList')
        expect(history.locator('.gallery-thumb img:visible')).to_have_count(4)
        assert_uncropped(history,'history-desktop')
        expect(history.locator('.gallery-actions a')).to_have_attribute('href',images[0]['url'])
        assert len([url for method,url in requests if '/api/rh-preview/' in url])==6
        assert not [url for method,url in requests if '/api/result-media/' in url]
        history.get_by_role('button',name='查看结果 3',exact=True).click()
        expect(history.locator('.gallery-result-image')).to_be_visible()
        history.get_by_role('button',name='查看结果 1',exact=True).click()
        expect(history.locator('.gallery-result-image')).to_be_visible()
        assert len([url for method,url in requests if '/api/rh-preview/' in url])==6
        page.screenshot(path=str(tmp_path/'packaged-gallery-desktop.png'))
        page.set_viewport_size({'width':320,'height':760})
        assert_uncropped(history,'history-mobile')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'packaged-gallery-mobile.png'))
        assert not errors
        browser.close()


if __name__=='__main__':
    with gallery_server() as (url, _, __):
        print(url, flush=True)
        threading.Event().wait()
