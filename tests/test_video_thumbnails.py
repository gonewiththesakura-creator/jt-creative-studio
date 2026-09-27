import base64
import io
from PIL import Image
from test_server_review_regressions import panel, SESSION_ID, running_server, json_request, session_cookie, request


def jpeg(size=(160,90)):
    out=io.BytesIO();Image.new('RGB',size,'red').save(out,format='JPEG')
    return base64.b64encode(out.getvalue()).decode()


def test_thumbnail_persists_private_and_bounded(panel):
    jid='abcdef123456'
    panel._jobs[jid]=dict(id=jid, workflow='h3_edit_n', style_id='video', status='queued',
        created=1, media={'source_video':'clip.mp4'}, request_session_hash=panel._session_hash(SESSION_ID))
    with running_server(panel) as httpd:
        payload=dict(job_id=jid,key='source_video',data=jpeg())
        code,_,_=json_request(httpd,'POST','/api/video-thumbnail',payload,cookie=session_cookie(panel,'other-session-1234567890'))
        assert code==404
        code,_,_=json_request(httpd,'POST','/api/video-thumbnail',{**payload,'data':jpeg((161,90))},cookie=session_cookie(panel))
        assert code==400
        code,_,_=json_request(httpd,'POST','/api/video-thumbnail',payload,cookie=session_cookie(panel))
        assert code==200
        panel.load_jobs()
        row=panel.video_queue_snapshot(SESSION_ID)['jobs'][0]
        url=row['thumbnails']['source_video']
        assert 'data' not in row and len(str(row))<2000
        code,raw,headers=request(httpd,'GET',url,cookie=session_cookie(panel))
        assert code==200 and Image.open(io.BytesIO(raw)).size==(160,90)
        assert 'private' in headers['Cache-Control']
        code,_,_=request(httpd,'GET',url,cookie=session_cookie(panel,'other-session-1234567890'))
        assert code==404
