#!/usr/bin/env python3
"""Create one ordinary signup identity, probe access, then delete only that identity."""
import http.cookiejar
import json
from pathlib import Path
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request


def main():
    root=Path('/opt/jt-identity')
    credentials=json.loads((root/'bootstrap-credentials.json').read_text())
    origin=credentials['issuer']
    username='jt-security-test-'+secrets.token_hex(6)
    password='Jt!9'+secrets.token_urlsafe(24)
    user_client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    admin_client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(client,path,body=None):
        req=urllib.request.Request(origin+path,data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','Origin':origin,'Accept':'application/json'})
        try:
            with client.open(req,timeout=20) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())
    report={}
    created=False
    try:
        status,signup=request(user_client,'/api/signup',{'application':'jt-workbench','organization':'jt-users',
            'username':username,'name':'Security Test','password':password,'confirm':password,'language':'zh','type':'signup',
            'isAdmin':True,'roles':['admin']})
        if signup.get('status')!='ok':raise RuntimeError('Public signup failed: '+str(signup.get('msg',''))[:200])
        created=True
        report['public_signup_succeeded']=True
        with sqlite3.connect('file:'+str(root/'data/casdoor.db')+'?mode=ro',uri=True) as db:
            row=db.execute('SELECT is_admin, owner FROM user WHERE owner=? AND name=?',('jt-users',username)).fetchone()
        report['signup_admin_injection_ignored']=row==(0,'jt-users')
        _,login=request(user_client,'/api/login',{'application':'jt-workbench','organization':'jt-users','username':username,
            'password':password,'type':'login','signinMethod':'Password','loginMethod':'password','language':'zh'})
        report['normal_login_succeeded']=login.get('status')=='ok'
        for label,path in [('global_users','/api/get-users?owner=built-in'),
                           ('other_user_profile','/api/get-user?id=jt-users%2Fowner'),
                           ('other_org_profile','/api/get-user?id=built-in%2Fadmin')]:
            result_status,result=request(user_client,path)
            report[label+'_denied']=result_status in [401,403] or result.get('status')=='error'
        _,forbidden_signup=request(user_client,'/api/signup',{'application':'app-built-in','organization':'built-in',
            'username':username,'name':'Security Test','password':password,'confirm':password,'type':'signup'})
        report['builtin_public_signup_denied']=forbidden_signup.get('status')=='error'
        if not all(report.values()):raise RuntimeError('Signup authorization checks failed: '+json.dumps(report))
    finally:
        if created:
            _,admin_login=request(admin_client,'/api/login',{'application':'app-built-in','organization':'built-in','username':'admin',
                'password':credentials['identity_admin_password'],'type':'login','signinMethod':'Password','loginMethod':'password','language':'zh'})
            if admin_login.get('status')!='ok':raise RuntimeError('Test account cleanup login failed')
            _,removed=request(admin_client,'/api/delete-user',{'owner':'jt-users','name':username})
            if removed.get('status')!='ok':raise RuntimeError('Test account cleanup failed')
            with sqlite3.connect('file:'+str(root/'data/casdoor.db')+'?mode=ro',uri=True) as db:
                report['test_identity_removed']=db.execute('SELECT count(*) FROM user WHERE owner=? AND name=?',('jt-users',username)).fetchone()[0]==0
            if not report['test_identity_removed']:raise RuntimeError('Test account remained after cleanup')
    (root/'signup-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
