"""Real account + upload HTTP chain; only provider file transfer is stubbed."""
import io
import time
from PIL import Image
from video_uploads import UploadStaging
from test_membership_http import membership_env, panel, activate, json_request


def test_account_image_upload_and_owner_boundary(membership_env,monkeypatch):
    env=membership_env;activate(env);activate(env,user='bob')
    monkeypatch.setattr(env.panel,'_video_upload_staging',UploadStaging())
    output=io.BytesIO();Image.new('RGB',(32,32),'navy').save(output,format='PNG');raw=output.getvalue();calls=[]
    def provider(path,name,ctype):
        calls.append((path.read_bytes(),name,ctype));return 'api/offline-image.png'
    monkeypatch.setattr(env.panel,'rh_upload_temp_file',provider)
    payload=dict(workflow='qwen21_wardrobe',input_key='person',filename='image.png',size=len(raw))
    assert json_request(env,'POST','/api/upload-start',payload,None)[0]==401
    assert json_request(env,'POST','/api/upload-start',payload,'alice',{'X-CSRF-Token':'bad'})[0]==403
    for bad in (dict(payload,workflow='missing'),dict(payload,input_key='not-a-slot')):
        assert json_request(env,'POST','/api/upload-start',bad,'alice')[0]==400
    status,body,_=json_request(env,'POST','/api/upload-start',payload,'alice')
    assert status==200,body
    uid=body['upload_id'];path='/api/upload-chunk?id='+uid+'&offset=0'
    assert json_request(env,'POST',path,None,'bob',{'Content-Type':'application/octet-stream'},raw=raw)[0]==404
    status,body,_=json_request(env,'POST',path,None,'alice',{'Content-Type':'application/octet-stream'},raw=raw)
    assert status==200 and body['offset']==len(raw)
    assert json_request(env,'POST','/api/upload-finish',{'upload_id':uid},'bob')[0]==404
    for _ in range(50):
        status,body,_=json_request(env,'POST','/api/upload-finish',{'upload_id':uid},'alice')
        if body.get('uploadToken'):break
        time.sleep(.01)
    assert status==200 and body['uploadToken'].startswith('upl_'),body
    assert calls==[(raw,'image.png','image/png')]
    assert not env.panel._jobs
