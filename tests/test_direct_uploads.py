import hashlib
import hmac
import io
import json
import time

import pytest
from PIL import Image
import direct_uploads
from test_server_review_regressions import panel, running_server, json_request, session_cookie
from test_app_shell import browser, serve_page
from playwright.sync_api import expect


def proof(key, challenge, name=''):
    return hmac.new(key.encode(),(challenge+'\n'+name).encode(),hashlib.sha256).hexdigest()


def test_proof_binds_session_expiry_and_provider_reference(monkeypatch):
    token=direct_uploads.challenge(b'secret','session',{'filename':'图片.png'})
    signature=proof('private-key',token,'openapi/test.png')
    assert direct_uploads.verify(b'secret','private-key','session',token,signature,'openapi/test.png')['filename']=='图片.png'
    for owner,key,name in [('other','private-key','openapi/test.png'),('session','wrong','openapi/test.png'),('session','private-key','openapi/other.png'),('session','private-key','openapi/../private.png')]:
        with pytest.raises(ValueError):direct_uploads.verify(b'secret',key,owner,token,signature,name)
    monkeypatch.setattr(direct_uploads.time,'time',lambda:time.monotonic()+10**11)
    with pytest.raises(ValueError):direct_uploads.verify(b'secret','private-key','session',token,signature,'openapi/test.png')


def test_direct_http_registration_without_file_or_key(panel,monkeypatch):
    monkeypatch.setattr(panel,'RH_KEY','offline-personal-key-1234')
    monkeypatch.setattr(panel,'rh_upload_temp_file',lambda *a:pytest.fail('must not transfer files'))
    monkeypatch.setattr(panel,'reserve_upload_attempt',lambda *a,**k:pytest.fail('personal direct upload must not consume proxy quota'))
    with running_server(panel) as httpd:
        cookie=session_cookie(panel)
        status,row,_=json_request(httpd,'POST','/api/upload-direct-start',dict(workflow='h3_edit_n',input_key='reference_image',filename='test.png',size=123),cookie=cookie)
        assert status==200;token=row['challenge']
        status,_,_=json_request(httpd,'POST','/api/upload-direct-verify',dict(challenge=token,proof=proof(panel.RH_KEY,token)),cookie=cookie)
        assert status==200
        body=dict(challenge=token,provider_name='openapi/direct.png',proof=proof(panel.RH_KEY,token,'openapi/direct.png'))
        status,row,_=json_request(httpd,'POST','/api/upload-direct-register',body,cookie=cookie)
        assert status==200
        record=panel._upload_capabilities[panel._upload_token_hash(row['uploadToken'])]
        assert record['provider_name']=='openapi/direct.png' and record['input_key']=='reference_image'
        status,_,_=json_request(httpd,'POST','/api/upload-direct-register',body,cookie=session_cookie(panel,'another-session-1234567890123456'))
        assert status==400
        status,_,_=json_request(httpd,'POST','/api/media-library/create',{},cookie=cookie)
        assert status==410


def test_browser_direct_transfer_receipt_retry_and_no_library(browser,tmp_path):
    page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    requests=serve_page(page,block_scene=True);receipts=[];uploads=[];attempts=[]
    page.route('**/api/workflows',lambda r:r.fulfill(json=[dict(id='h3_edit_n',kind='video',name='MiniMax H3',rh_media={'reference_image':dict(type='image',label='参考图',required=True)},rh_params={'prompt':dict(type='text',label='编辑指令')})]))
    page.route('**/api/video-queue',lambda r:r.fulfill(json={'jobs':[],'running':0,'waiting':0,'limit':2}))
    personal='test-personal-key-123456789'
    def direct(route):
        body=route.request.post_data_json;receipts.append(body);action=route.request.url.rsplit('-',1)[-1]
        if action=='start':return route.fulfill(json={'challenge':'offline-challenge'})
        assert body['proof']==proof(personal,'offline-challenge',body.get('provider_name',''))
        if action=='verify':return route.fulfill(json={'ok':True})
        attempts.append(1)
        if len(attempts)==1:return route.fulfill(status=503,json={'error':'receipt interrupted'})
        return route.fulfill(json={'uploadToken':'upl_fixture'})
    page.route('**/api/upload-direct-*',direct)
    def provider(route):
        uploads.append(route.request.url)
        assert route.request.headers['authorization']=='Bearer '+personal
        assert b'image/png' in route.request.post_data_buffer
        return route.fulfill(json={'code':200,'data':{'filename':'openapi/test.png'}},headers={'Access-Control-Allow-Origin':'*'})
    page.route('https://www.runninghub.ai/openapi/v2/media/upload/binary',provider)
    output=io.BytesIO();Image.new('RGB',(4,8),'gold').save(output,'PNG')
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#tempMediaLibrary')).to_have_count(0)
        expect(page.get_by_role('button',name='临时素材库')).to_have_count(0)
        page.locator('#personalUpload summary').click()
        page.get_by_role('textbox',name='个人 RunningHub API Key').fill(personal)
        page.get_by_role('button',name='保存',exact=True).click()
        expect(page.get_by_role('textbox',name='个人 RunningHub API Key')).to_have_value('')
        page.locator('.drop input[type=file]').set_input_files({'name':'test.png','mimeType':'image/png','buffer':output.getvalue()})
        expect(page.locator('.upload-retry')).to_be_visible()
        page.locator('.upload-retry').click()
        expect(page.locator('.drop .fn')).to_contain_text('已上传')
        assert len(uploads)==1 and len(attempts)==2
        assert personal not in json.dumps(receipts)
        assert not [r for r in requests if r[1] in ['/api/upload','/api/upload-start','/api/upload-chunk','/api/upload-finish']]
        page.screenshot(path=str(tmp_path/'direct-upload.png'),full_page=True)
        page.get_by_role('button',name='清除',exact=True).click()
        assert page.evaluate('sessionStorage.getItem("jt-personal-rh-key")') is None
        assert not errors,errors
    finally:page.close()
