"""Real Chromium HTTP-cache verification, with an offline upstream and real auth checks."""
import io
import shutil
import subprocess
from types import SimpleNamespace
import membership_media
from test_app_shell import browser
from test_server_review_regressions import panel, SESSION_ID, running_server, session_cookie


def test_video_replay_reuses_cached_byte_ranges_and_other_session_cannot_read(panel, browser, monkeypatch, tmp_path):
    video=tmp_path/'sample.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=24',
                    '-t','1','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
    content=video.read_bytes()
    job={'id':'a'*12,'images':[{'remote':True,'url':'https://cdn.example/private.mp4','file':'private.mp4'}],
         'request_session_hash':panel._session_hash(SESSION_ID),'style_id':'video','status':'done'}
    panel._jobs[job['id']]=job
    reads=[]
    def opened(url, byte_range, **kwargs):
        assert url=='https://cdn.example/private.mp4'
        reads.append(byte_range)
        assert byte_range in (None,'bytes=0-')
        body=io.BytesIO(content)
        headers={'Content-Type':'video/mp4','Content-Length':str(len(content)),
                 'Content-Range':f'bytes 0-{len(content)-1}/{len(content)}'}
        response=SimpleNamespace(status=206 if byte_range else 200,getheader=lambda k,d=None:headers.get(k,d),read1=body.read)
        return SimpleNamespace(close=lambda:None),response
    monkeypatch.setattr(membership_media,'open_media',opened)
    with running_server(panel) as httpd:
        origin=f'http://127.0.0.1:{httpd.server_port}'
        context=browser.new_context()
        name,value=session_cookie(panel).split('=',1)
        context.add_cookies([{'name':name,'value':value,'url':origin}])
        page=context.new_page()
        try:
            page.goto(origin+'/api/live')
            fetch="""async path => {const r=await fetch(path,{headers:{Range:'bytes=0-'}});return {status:r.status,length:(await r.arrayBuffer()).byteLength,cache:r.headers.get('Cache-Control'),etag:r.headers.get('ETag')}}"""
            path='/api/result-media/'+job['id']+'/0'
            play="""async path => {const v=document.createElement('video');v.muted=true;v.preload='auto';document.body.append(v);v.src=path;await v.play();await new Promise((resolve,reject)=>{v.onended=resolve;v.onerror=()=>reject(Error('video failed'))});v.removeAttribute('src');v.load();v.remove()}"""
            page.evaluate(play,path)
            first_reads=len(reads)
            page.evaluate(play,path)
            assert len(reads)==first_reads, 'Replay must not transfer upstream bytes again'
            # The cookie is part of the cache key; changing accounts must not hit it.
            name,value=session_cookie(panel,'other-video-owner-1234567890').split('=',1)
            context.add_cookies([{'name':name,'value':value,'url':origin}])
            other=page.evaluate(fetch,path)
            assert other['status']==404 and len(reads)==1
            context.clear_cookies()
            anonymous=page.evaluate(fetch,path)
            assert anonymous['status']==404 and len(reads)==1
        finally:context.close()
