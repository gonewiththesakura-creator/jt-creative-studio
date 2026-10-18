import json, threading, time
import pytest
from video_uploads import UploadStaging
from test_server_review_regressions import panel
from test_server_review_regressions import running_server,json_request,session_cookie,SESSION_ID
import http.client


def test_chunk_retry_owner_boundary_and_finish_once(tmp_path):
    upload=UploadStaging();uid=upload.start(tmp_path,'owner',('w','video','a.mp4'),6)
    assert upload.chunk(uid,'owner',0,b'abc')==3
    assert upload.chunk(uid,'owner',0,b'abc')==3
    with pytest.raises(LookupError):upload.chunk(uid,'other',3,b'def')
    with pytest.raises(ValueError):upload.chunk(uid,'owner',0,b'bad')
    assert upload.chunk(uid,'owner',3,b'def')==6
    calls=[];done=threading.Event()
    def process(row):calls.append(row['path'].read_bytes());done.wait(1);return {'uploadToken':'test'}
    assert upload.finish(uid,'owner',process)['status']=='processing'
    assert upload.finish(uid,'owner',process)['status']=='processing'
    done.set()
    for _ in range(100):
        result=upload.finish(uid,'owner',process)
        if result['status']=='done':break
        time.sleep(.01)
    assert result['uploadToken']=='test' and calls==[b'abcdef']


def test_multi_reference_graph_has_real_separate_connections(panel,monkeypatch):
    w=panel.WORKFLOWS['h3_edit_n'];calls=[]
    def provider(req,**kw):calls.append(json.loads(req.data));return {'code':0,'data':{'taskId':'fake-task'}}
    monkeypatch.setattr(panel,'_provider_json_request',provider)
    job={'provider_media':{'reference_image':'api/one.png','reference_image_2':'api/two.png','reference_image_4':'api/four.png','source_video':'api/video.mp4'},'prompt':'change clothing color','params':{'duration':5,'seed':123,'short_edge':436}}
    assert panel.rh_submit_h3_multi(job,w)=='fake-task'
    graph=json.loads(calls[0]['workflow']);refs=graph['225']['inputs']
    assert refs['ref_images.ref_image_0']==['293',0]
    assert refs['ref_images.ref_image_1']==['294',0]
    assert refs['ref_images.ref_image_3']==['296',0]
    assert 'ref_images.ref_image_2' not in refs
    assert graph['294']['inputs']['image']=='api/two.png'
    assert graph['244']['inputs']['text']==job['prompt']
    assert refs['ref_videos.ref_video_1']==['276',0]


@pytest.mark.parametrize('workflow,key', [
    ('h3_edit_n','reference_image_2'),
    ('qwen21_wardrobe','person'),
    ('qwen21_wardrobe','clothing'),
    ('realcomic','source_image'),
    ('realism_krea2','image'),
])
def test_resumable_http_provider_receives_complete_file_once(panel,monkeypatch,workflow,key):
    from PIL import Image
    import io
    image=io.BytesIO();Image.new('RGB',(5,5)).save(image,format='PNG');data=image.getvalue();calls=[]
    monkeypatch.setattr(panel,'_video_upload_staging',UploadStaging())
    def provider(path,*args):calls.append(path.read_bytes());return 'api/test.png'
    monkeypatch.setattr(panel,'rh_upload_temp_file',provider)
    with running_server(panel) as httpd:
        cookie=session_cookie(panel)
        status,body,_=json_request(httpd,'POST','/api/upload-start',dict(workflow=workflow,input_key=key,filename='image.png',size=len(data)),cookie=cookie)
        assert status==200;uid=body['upload_id']
        for raw,offset in [(data[:20],0),(data[:20],0),(data[20:],20)]:
            c=http.client.HTTPConnection('127.0.0.1',httpd.server_port)
            c.request('POST','/api/upload-chunk?id='+uid+'&offset='+str(offset),raw,{'Cookie':cookie,'Content-Type':'application/octet-stream'})
            response=c.getresponse();assert response.status==200,response.read();response.read();c.close()
        for _ in range(50):
            status,body,_=json_request(httpd,'POST','/api/upload-finish',dict(upload_id=uid),cookie=cookie)
            if body.get('uploadToken'):break
            time.sleep(.01)
        assert status==200 and body['uploadToken'].startswith('upl_')
        assert calls==[data]
        row=panel._upload_capabilities[panel._upload_token_hash(body['uploadToken'])]
        assert row['workflow']==workflow and row['input_key']==key and row['media_type']=='image'
