import base64
import http.client
import io
import json
import threading
import time
import subprocess
import shutil

import pytest
from PIL import Image
from media_library import MediaLibrary
from test_server_review_regressions import panel, running_server, session_cookie


def png():
    out = io.BytesIO()
    Image.new('RGB', (12, 8), '#cd9861').save(out, 'PNG')
    return out.getvalue()


def saved(library, code):
    data = png()
    aid = library.start(code, 'reference.png', len(data), 'image')['id']
    library.chunk(code, aid, 0, data)
    library.finish(code, aid, None, None, lambda *args: 'image/png')
    return aid


def test_resumable_restart_limit_and_expiration(tmp_path):
    now = [10000.0]
    library = MediaLibrary(tmp_path, lambda: now[0])
    code = library.create()['code']
    aid = library.start(code, 'video.mp4', 6, 'video')['id']
    library.chunk(code, aid, 0, b'abc')
    assert library.chunk(code, aid, 0, b'abc')['offset'] == 3
    library = MediaLibrary(tmp_path, lambda: now[0])
    assert library.snapshot(code)['assets'][0]['offset'] == 3
    with pytest.raises(LookupError): library.snapshot('ml_'+'a'*43)
    with pytest.raises(LookupError): library.chunk(code, '../../file', 0, b'a')
    library.chunk(code, aid, 3, b'def')
    library.finish(code, aid, None, 12.7, lambda *args: 'video/mp4')
    for _ in range(9): saved(library, code)
    with pytest.raises(ValueError, match='10'): saved(library, code)
    library.delete(code, aid)
    assert len(library.snapshot(code)['assets']) == 9
    saved(library, code)
    now[0] += 7201
    with pytest.raises(LookupError): library.snapshot(code)
    library.cleanup()
    assert not list(tmp_path.iterdir())


def test_provider_reuse_retry_key_rotation_and_delete_during_upload(tmp_path):
    library = MediaLibrary(tmp_path)
    code = library.create()['code']; aid = saved(library, code)
    calls = []; event = threading.Event(); slots = threading.BoundedSemaphore(2)
    def upload(path, *args):
        calls.append(path.read_bytes()); event.wait(2)
        return 'api/reference.png'
    assert library.use(code, aid, 'key1', upload, slots)['status'] == 'processing'
    assert library.use(code, aid, 'key1', upload, slots)['status'] == 'processing'
    event.set()
    for _ in range(100):
        result = library.use(code, aid, 'key1', upload, slots)
        if result['status'] == 'done': break
        time.sleep(.01)
    assert result['status'] == 'done' and calls == [png()]
    library = MediaLibrary(tmp_path)
    assert library.use(code, aid, 'key1', upload, slots)['status'] == 'done'
    event.clear()
    library.use(code, aid, 'key2', upload, slots)
    library.delete(code, aid)
    with pytest.raises(LookupError): library.use(code, aid, 'key2', upload, slots)
    event.set()
    for _ in range(100):
        if not list(tmp_path.glob('*/'+aid+'.bin')): break
        time.sleep(.01)
    assert not list(tmp_path.glob('*/'+aid+'.bin'))
    aid = saved(library, code)
    def fail(*args): raise OSError('offline')
    library.use(code, aid, 'key', fail, slots)
    for _ in range(100):
        if library.use(code, aid, 'key', fail, slots)['status'] == 'error': break
        time.sleep(.01)
    assert library.snapshot(code)['assets'][0]['ready']
    library.use(code, aid, 'key', upload, slots, retry=True)
    for _ in range(100):
        result = library.use(code, aid, 'key', upload, slots)
        if result['status'] == 'done': break
        time.sleep(.01)
    assert result['status'] == 'done'


def test_http_cross_device_capability_and_wrong_type(panel, monkeypatch):
    monkeypatch.setattr(panel, '_media_library', MediaLibrary(panel.DATA_DIR/'library'))
    calls=[]
    monkeypatch.setattr(panel,'rh_upload_temp_file',lambda *args: calls.append(1) or 'api/reference.png')
    with running_server(panel) as httpd:
        cookie=session_cookie(panel)
        def request(action='', body=None, code='', cookie_value=cookie, query=''):
            connection=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=5)
            raw=body if isinstance(body, bytes) else json.dumps(body or {}).encode()
            connection.request('POST' if action else 'GET','/api/media-library'+('/'+action if action else '')+query,raw if action else None,
                               {'Cookie':cookie_value,'X-Media-Library':code,'Content-Type':'application/json'})
            response=connection.getresponse(); result=json.loads(response.read()); status=response.status;connection.close();return status,result
        status, result=request('create'); assert status==200
        code=result['code']; raw=png()
        _, result=request('start',dict(filename='ref.png',type='image',size=len(raw)),code); aid=result['id']
        assert request('chunk',raw,code,query='?id='+aid+'&offset=0')[0]==200
        assert request('finish',{'id':aid},code)[0]==200
        second_cookie=session_cookie(panel,'another-session-1234567890123456')
        assert request(code=code,cookie_value=second_cookie)[0]==200
        assert request(code='ml_'+'z'*43,cookie_value=second_cookie)[0]==404
        assert request('use',{'id':aid,'workflow':'h3_edit_n','input_key':'source_video'},code)[0]==400
        body={'id':aid,'workflow':'h3_edit_n','input_key':'reference_image'}
        for _ in range(100):
            _, result=request('use',body,code)
            if result.get('uploadToken'): break
            time.sleep(.01)
        first=result['uploadToken']
        _, result=request('use',body,code,cookie_value=second_cookie)
        assert first!=result['uploadToken'] and calls==[1]
        row=panel._upload_capabilities[panel._upload_token_hash(result['uploadToken'])]
        assert row['session_hash']==panel._session_hash('another-session-1234567890123456')
        assert row['expires'] <= panel._media_library.snapshot(code)['expires']
        assert 'provider_name' not in result


def test_browser_library_batch_paste_pick_and_cross_device(browser, tmp_path):
    from test_app_shell import serve_page
    from playwright.sync_api import expect
    page=browser.new_page(viewport={'width':1280,'height':900}); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    requests=serve_page(page,block_scene=True)
    workflow={'id':'h3_edit_n','kind':'video','name':'MiniMax H3','rh_media':{
        'reference_image':{'type':'image','label':'人物参考图','required':True},
        'source_video':{'type':'video','label':'待编辑视频','required':True}},
        'rh_params':{'prompt':{'type':'text','label':'编辑指令'},'duration':{'type':'number','label':'时长','min':4,'max':15,'step':1,'default':5}}}
    page.route('**/api/workflows',lambda r:r.fulfill(json=[workflow]))
    assets=[]; calls=[]; code='ml_'+'a'*43
    def handler(route):
        action=route.request.url.split('/api/media-library')[-1].split('?')[0];calls.append(action)
        body=route.request.post_data_json if action not in ('','/chunk') else {}
        if action=='/create': return route.fulfill(json={'code':code,'expires':time.time()+7200,'assets':assets})
        if action=='/start':
            asset=dict(id=str(len(assets)),name=body['filename'],size=body['size'],type=body['type'],offset=0,ready=False,thumbnail=None,duration=None);assets.append(asset);return route.fulfill(json=asset)
        if action=='/chunk':
            asset=assets[-1];asset['offset']=asset['size'];return route.fulfill(json={'offset':asset['size']})
        if action=='/finish':
            assets[-1].update(ready=True,thumbnail=body.get('thumbnail'),duration=body.get('duration'));return route.fulfill(json={'ready':True})
        if action=='/use': return route.fulfill(json={'status':'done','uploadToken':'upl_test'})
        if action=='/delete': assets[:]=[a for a in assets if a['id']!=body['id']];return route.fulfill(json={'deleted':True})
        return route.fulfill(json={'assets':assets,'expires':time.time()+7200,'limit':10})
    page.route('**/api/media-library**',handler)
    try:
        page.goto('http://fixture.test/video')
        page.wait_for_timeout(800)
        assert not errors, errors
        page.get_by_role('button',name='临时素材库',exact=True).click(timeout=5000)
        dialog=page.locator('#tempMediaLibrary')
        dialog.locator('input[type=file]').set_input_files([{'name':'参考一.png','mimeType':'image/png','buffer':png()},{'name':'参考二.png','mimeType':'image/png','buffer':png()}])
        expect(dialog.locator('.temp-media-card')).to_have_count(2)
        expect(dialog.locator('.temp-media-card img')).to_have_count(2)
        expect(dialog.locator('video')).to_have_count(0)
        expect(dialog.get_by_role('button',name='删除').first).to_be_enabled()
        page.evaluate('''data=>{const blob=Uint8Array.from(atob(data),c=>c.charCodeAt(0)),dt=new DataTransfer();dt.items.add(new File([blob],'pasted.png',{type:'image/png'}));window.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true}))}''',base64.b64encode(png()).decode())
        expect(dialog.locator('.temp-media-card')).to_have_count(3)
        expect(dialog.get_by_role('button',name='删除').first).to_be_enabled()
        page.screenshot(path=str(tmp_path/'media-library.png'),full_page=True)
        dialog.get_by_role('button',name='关闭素材库').click()
        page.locator('[data-media-key=reference_image]').get_by_role('button',name='从素材库选择').click()
        dialog.get_by_role('button',name='选用').first.click()
        expect(page.locator('[data-media-key=reference_image] .fn')).to_contain_text('已选用')
        page.locator('[data-media-key=source_video]').get_by_role('button',name='从素材库选择').click()
        expect(dialog.get_by_role('button',name='选用').first).to_be_disabled()
        dialog.get_by_role('button',name='删除').last.click();expect(dialog.locator('.temp-media-card')).to_have_count(2)
        assert not errors
        assert not [r for r in requests if r[0]=='POST']  # All writes stayed inside this mock.
        assert calls.count('/start')==3 and calls.count('/use')==1
        # Encode a real portrait video: the library must keep its aspect ratio,
        # persist duration and select it without attaching a full video player.
        encoder=shutil.which('ffmpeg')
        if encoder:
            clip=tmp_path/'portrait.mp4'
            subprocess.run([encoder,'-v','error','-f','lavfi','-i','color=c=gold:s=60x100:d=5.4:r=10',
                            '-c:v','libx264','-pix_fmt','yuv420p',str(clip)],check=True)
            dialog.locator('input[type=file]').set_input_files(str(clip))
            expect(dialog.locator('.temp-media-card')).to_have_count(3)
            expect(dialog.get_by_role('button',name='选用').last).to_be_enabled(timeout=15000)
            assert 5.3 < assets[-1]['duration'] < 5.5
            page.screenshot(path=str(tmp_path/'media-library-video.png'),full_page=True)
            dialog.get_by_role('button',name='选用').last.click()
            expect(page.locator('[data-media-key=source_video] .fn')).to_contain_text('已选用')
            expect(page.locator('#param_duration')).to_have_value('5')
            expect(page.locator('[data-media-key=source_video] video')).to_have_count(0)
            expect(page.locator('[data-media-key=source_video] img')).to_have_count(1)
        assert not errors
    finally:
        if errors: print('BROWSER_ERRORS',errors)
        page.close()


from test_app_shell import browser
