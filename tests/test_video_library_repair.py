import json
from urllib.parse import quote
from test_server_review_regressions import panel, running_server, json_request, session_cookie, SESSION_ID


def test_video_favorite_returns_before_download_retries_and_preserves_ownership(panel,monkeypatch):
    panel._jobs['v']={'id':'v','status':'done','style_id':'video','request_session_hash':panel._session_hash(SESSION_ID),
        'images':[{'remote':True,'url':'https://example.com/result.mp4','file_type':'mp4'}]}
    calls=[]
    def fail(url,dest,timeout):calls.append(url);raise TimeoutError()
    monkeypatch.setattr(panel,'download_file_resilient',fail)
    with running_server(panel) as httpd:
        def post(cookie=None):return json_request(httpd,'POST','/api/favorites',{'job_id':'v','image_index':0},cookie=cookie or session_cookie(panel))
        status,f,_=post();assert status==202 and f['archive_status']=='saving' and not calls
        assert 'original_url' not in f and 'image_path' not in f
        assert post()[1]['id']==f['id'] and len(panel._favorites)==1
        assert post(session_cookie(panel,'other-owner-123456789'))[0]==404
        panel.archive_next_video_favorite();assert panel._favorites[f['id']]['archive_status']=='error'
        assert post()[0]==202
        monkeypatch.setattr(panel,'download_file_resilient',lambda url,dest,timeout:dest.write_bytes(b'\x00\x00\x00\x18ftypmp42fixture'))
        panel.load_favorites();panel.archive_next_video_favorite()
        assert post()[1]['archive_status']=='ready'
        assert len(panel._favorites)==1


def test_video_history_paginates_including_retired_workflows(panel):
    owner=panel._session_hash(SESSION_ID)
    panel._jobs={str(i):{'id':str(i),'style_id':'video','workflow':'retired-workflow','created':100,'request_session_hash':owner,'status':'done'} for i in range(31)}
    panel._jobs['other']={'id':'other','created':999,'workflow':'h3_edit_n','style_id':'video','request_session_hash':'someone-else'}
    with running_server(panel) as httpd:
        status,first,_=json_request(httpd,'GET','/api/jobs?scope=video&limit=20',cookie=session_cookie(panel))
        assert status==200 and len(first)==20
        cursor=quote(json.dumps([first[-1]['created'],first[-1]['id']]))
        status,second,_=json_request(httpd,'GET','/api/jobs?scope=video&limit=20&before='+cursor,cookie=session_cookie(panel))
        assert status==200 and len(second)==11 and not ({j['id'] for j in first}&{j['id'] for j in second})
