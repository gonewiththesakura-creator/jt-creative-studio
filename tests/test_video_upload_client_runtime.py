import json
import base64
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_video_upload_client_preflights_files_and_releases_replaced_local_preview_url():
    """Catches accidental Base64-era uploads that have no local preview lifecycle."""
    source = (ROOT / "sources" / "video_business.js").read_text(encoding="utf8")
    executable = source.rsplit("document.getElementById('genBtn').onclick=generate;", 1)[0]
    harness = r'''
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.textContent='';this.className='';this.dataset={};this.style={};}
  append(...items){this.children.push(...items)}
  replaceChildren(...items){this.children=[...items]}
  removeChild(item){this.children=this.children.filter(child=>child!==item)}
  querySelector(selector){return this.children.find(item=>item.className==='local-media-preview')||null}
}
const created=[], revoked=[];
globalThis.document={createElement:tag=>new Element(tag)};
globalThis.URL={createObjectURL:file=>{const value='blob:'+file.name;created.push(value);return value},revokeObjectURL:value=>revoked.push(value)};
globalThis.window={addEventListener:()=>{}};
'''
    assertion = r'''
const state=ensureMediaState('workflow');
const drop=new Element('div');
const image={type:'image'};
const video={type:'video'};
const result={
  unsupported:validateSelectedMedia({name:'camera.heic',size:1},image)!=='',
  tooLarge:validateSelectedMedia({name:'clip.mp4',size:60*1024*1024+1},video)!=='',
  allowed:validateSelectedMedia({name:'clip.mp4',size:60*1024*1024},video),
};
replaceLocalMediaPreview('source',video,{name:'first.mp4'},drop,state);
replaceLocalMediaPreview('source',video,{name:'second.mp4'},drop,state);
const media=drop.querySelector('.local-media-preview');
result.mediaTag=media.tagName;
result.controls=media.controls;
result.playsInline=media.playsInline;
result.preload=media.preload;
result.created=created;
result.revoked=revoked;
console.log(JSON.stringify(result));
'''
    completed = subprocess.run(
        ["node", "-e", harness + executable + assertion],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "unsupported": True,
        "tooLarge": True,
        "allowed": "",
        "mediaTag": "video",
        "controls": True,
        "playsInline": True,
        "preload": "metadata",
        "created": ["blob:first.mp4", "blob:second.mp4"],
        "revoked": ["blob:first.mp4"],
    }


def test_mobile_upload_sends_file_bytes_keeps_failure_preview_and_restores_selection():
    from playwright.sync_api import sync_playwright, expect
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOYsAAAAASUVORK5CYII=')
    workflows = [{
        'id': name, 'kind': 'video', 'name': name, 'desc': '测试素材上传',
        'rh_media': {'source': {'type': 'image', 'label': '参考图', 'required': True}},
        'rh_params': {'prompt': {'type': 'text', 'label': '提示词', 'default': '测试'}},
    } for name in ('first', 'second')]
    uploaded = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            request = request_route.request
            path = request.url.split('fixture.test')[-1]
            if path == '/video':
                return request_route.fulfill(body=(ROOT/'static/video.html').read_text(encoding='utf8'), content_type='text/html')
            if path == '/api/workflows':
                return request_route.fulfill(json=workflows)
            if path.startswith('/api/upload?'):
                uploaded.append((request.url, request.headers['content-type'], request.post_data_buffer))
                return request_route.fulfill(status=502, json={'error': '测试上游暂时不可用'})
            return request_route.fulfill(json=[])
        page.route('**/*', route)
        page.goto('http://fixture.test/video')
        page.locator('input[type=file]').set_input_files({'name': '手机参考图.png', 'mimeType': 'image/png', 'buffer': png})
        page.wait_for_function("document.querySelector('.fn').textContent.includes('上传失败')")
        assert len(uploaded) == 1
        assert uploaded[0][1:] == ('application/octet-stream', png)
        assert 'workflow=first' in uploaded[0][0] and 'filename=%E6%89%8B' in uploaded[0][0]
        expect(page.locator('img.local-media-preview')).to_be_visible()
        assert page.evaluate("ensureMediaState('first').tokens.source === undefined")
        page.locator('[data-wf=second]').click()
        page.locator('[data-wf=first]').click()
        expect(page.locator('img.local-media-preview')).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()


def test_replacing_upload_clears_old_token_and_waits_before_generation():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.route('**/*', lambda route: route.fulfill(json=[]))
        page.set_content('<div id="wfSwitch"></div><div id="wfForm"></div><button id="genBtn"></button><div id="genStatus"></div>')
        source = (ROOT/'sources/video_business.js').read_text(encoding='utf8').split("window.addEventListener('pagehide'")[0]
        page.add_script_tag(content=source)
        result = page.evaluate("""async () => {
            const wf={id:'video',name:'video',rh_media:{source:{type:'video',label:'视频'}},rh_params:{}};
            selectVideoWorkflow(wf);
            const state=ensureMediaState('video');state.tokens.source='old-token';
            sendMediaFile=()=>new Promise(()=>{});
            const drop=document.querySelector('.drop');
            uploadMedia('source',wf.rh_media.source,new File(['video'],'clip.mp4'),drop,wf,renderVersion,state);
            await generate();
            const media=drop.querySelector('video');
            return {oldToken:state.tokens.source,uploading:state.uploading.source,
                status:document.querySelector('#genStatus').textContent,
                controls:media.controls,playsInline:media.playsInline};
        }""")
        assert result['oldToken'] is None and result['uploading']
        assert '仍在上传' in result['status']
        assert result['controls'] and result['playsInline']
        chooser = []
        page.on('filechooser', lambda dialog: chooser.append(dialog))
        page.locator('video').dispatch_event('click')
        assert not chooser
        browser.close()
