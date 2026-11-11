"""Authenticated security smoke test, no generation/cancellation/account changes.

Credentials remain on the server, loaded in memory, never included in results.
Only temporary login sessions are created and revoked using the public APIs.
"""
import http.cookiejar
import base64
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import time


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Browser:
    def __init__(self):
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),NoRedirect())
        self.csrf=None

    def request(self,origin,path,body=None,headers=None,binary=False):
        h={'Accept':'application/json','Cache-Control':'no-cache'}
        if body is not None:
            h.update({'Content-Type':'application/json','Origin':origin})
            if self.csrf:h['X-CSRF-Token']=self.csrf
        h.update(headers or {})
        req=urllib.request.Request(origin+path,data=None if body is None else body if isinstance(body,bytes) else json.dumps(body).encode(),headers=h)
        try:response=self.client.open(req,timeout=40)
        except urllib.error.HTTPError as error:response=error
        with response:
            raw=response.read(33 if binary else 8*1024*1024)
            value=raw if binary else {} if 300<=response.code<400 else json.loads(raw) if raw else {}
            return response.code,value,response.headers


def main(upload=False):
    assert os.geteuid()==0
    root=Path('/opt/jt-identity')
    credentials=json.loads((root/'bootstrap-credentials.json').read_text())
    code=json.loads((root/'owner-access-code.json').read_text())['code']
    public,issuer=credentials['public_origin'],credentials['issuer']
    report={}
    user=Browser()
    try:
        status,_,headers=user.request(public,'/api/auth/code-login',{'code':code})
        assert status==200 and headers.get('Clear-Site-Data')=='"cache"'
        status,me,_=user.request(public,'/api/auth/me')
        # 2026-11-11: an administrator's own login code carries management for that session (27c4212),
        # so the code session reads the admin API without a second account verification.
        assert me['authenticated'] and me['user']['is_admin'] and not me['admin_verification_required']
        user.csrf=me['csrf_token']
        assert user.request(public,'/api/admin/membership/users')[0]==200
        report['code_session_admin_read_allowed']=True
        report['code_login_account_preserved']=True
        assert user.request(public,'/api/upload-direct-config')[0]==410
        status,_,_=user.request(public,'/api/auth/login?return_to=%2F%09%2Fevil.invalid')
        assert status==400
        report['unsafe_login_redirect_rejected']=True
        status,_,headers=user.request(public,'/api/auth/login?return_to=%2Fvideo')
        assert status==302
        redirect=urllib.parse.urlsplit(headers['Location'])
        assert redirect.scheme+'://'+redirect.netloc==issuer
        query={k:v[0] for k,v in urllib.parse.parse_qs(redirect.query).items()}
        assert query['prompt']=='login' and query['code_challenge_method']=='S256'
        fields={'clientId':query['client_id'],'responseType':query['response_type'],'redirectUri':query['redirect_uri'],
            'type':'code','scope':query['scope'],'state':query['state'],'nonce':query['nonce'],'prompt':'login',
            'code_challenge':query['code_challenge'],'code_challenge_method':'S256'}
        status,result,_=user.request(issuer,'/api/login?'+urllib.parse.urlencode(fields),{
            'application':'jt-workbench','organization':'jt-users','username':'owner','password':credentials['workbench_owner_password'],
            'type':'code','autoSignin':False,'signinMethod':'Password','loginMethod':'password','language':'zh'})
        assert status==200 and result.get('status')=='ok' and isinstance(result.get('data'),str)
        status,_,headers=user.request(public,'/api/auth/callback?'+urllib.parse.urlencode({'state':query['state'],'code':result['data']}))
        assert status==302 and headers.get('Location')=='/video'
        _,verified,_=user.request(public,'/api/auth/me');user.csrf=verified['csrf_token']
        assert verified['user']['id']==me['user']['id'] and not verified['admin_verification_required']
        assert user.request(public,'/api/admin/membership/users')[0]==200
        report['real_oidc_admin_verification_passed']=True
        status,jobs,_=user.request(public,'/api/jobs')
        assert status==200
        status,favorites,_=user.request(public,'/api/favorites')
        assert status==200
        data=Path('/home/admin/comfy-panel/panel_data')
        favs=json.loads((data/'favorites.json').read_text())
        rows=favs.values() if isinstance(favs,dict) else favs
        archived=[f for f in rows if f.get('image_path') and Path(f['image_path']).is_file()]
        if archived:
            f=archived[0]
            status,raw,headers=user.request(public,'/api/favorite-image/'+f['id'],headers={'Range':'bytes=0-31'},binary=True)
            assert status in (200,206) and raw
            assert 'no-store' in headers.get('Cache-Control','') and 'Cookie' in headers.get('Vary','')
            report['existing_favorite_range_no_store']=True
        else:report['existing_favorite_range_no_store']='no-local-archive'
        local_jobs=json.loads((data/'jobs.json').read_text())
        report['jobs_readable']=len(local_jobs)
        report['favorites_readable']=len(favs)
        if upload:
            # One synthetic PNG, no user material and no generation request.
            config=json.loads(Path('/home/admin/comfy-panel/config.json').read_text())
            workflow=next(w for w in config['workflows'] if w.get('kind')=='video' and 'reference_image' in w.get('rh_media',{}))
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=')
            status,started,_=user.request(public,'/api/upload-start',{'workflow':workflow['id'],'input_key':'reference_image','filename':'jt-security-upload-check.png','size':len(png)})
            assert status==200 and started.get('upload_id')
            status,chunk,_=user.request(public,'/api/upload-chunk?'+urllib.parse.urlencode({'id':started['upload_id'],'offset':0}),png,headers={'Content-Type':'application/octet-stream'})
            assert status==200 and chunk.get('offset')==len(png)
            deadline=time.monotonic()+90
            result={}
            while time.monotonic()<deadline:
                status,result,_=user.request(public,'/api/upload-finish',{'upload_id':started['upload_id']})
                assert status==200 and result.get('status')!='error', 'Synthetic upload was not accepted'
                if result.get('uploadToken'):break
                assert result.get('status')=='processing'
                time.sleep(1)
            assert result.get('uploadToken') and not any(k in result for k in ('apiKey','key','fileName','url'))
            report['synthetic_png_backend_chunk_upload']=True
            report['uploaded_test_bytes']=len(png)
            report['upload_response_contains_no_provider_credentials']=True
        report['provider_generation_requests']=0
        report['production_jobs_modified']=False
    finally:
        if user.csrf:
            user.request(public,'/api/auth/logout',{})
        # Explicitly end only this check's identity session as well.
        try:user.request(issuer,'/api/logout')
        except Exception:pass
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upload',action='store_true',help='Upload one synthetic 68-byte PNG, never generate')
    main(parser.parse_args().upload)
