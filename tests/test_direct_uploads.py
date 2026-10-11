import hashlib
import hmac
import time

import pytest
import direct_uploads
from test_server_review_regressions import panel, running_server, json_request, session_cookie


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


# The retired browser-direct path has been replaced by the server-only upload
# and no-secret-storage regressions in test_client_secret_retirement.py.
