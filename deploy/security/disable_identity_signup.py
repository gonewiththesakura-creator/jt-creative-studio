"""Disable unused public signup for JT only; preserve identities and login."""
import http.cookiejar
import json
import os
from pathlib import Path
import urllib.request

ROOT=Path('/opt/jt-identity')


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    credentials=json.loads((ROOT/'bootstrap-credentials.json').read_text())
    origin=credentials['issuer']
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, body=None):
        req=urllib.request.Request(origin+path, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','Origin':origin,'Accept':'application/json'})
        with client.open(req,timeout=30) as response:
            result=json.load(response)
        if result.get('status')!='ok':raise RuntimeError('Identity operation failed')
        return result.get('data')
    request('/api/login',{'application':'app-built-in','organization':'built-in','username':'admin',
        'password':credentials['identity_admin_password'],'type':'login','signinMethod':'Password',
        'loginMethod':'password','language':'zh'})
    path='/api/get-application?id=admin%2Fjt-workbench'
    update='/api/update-application?id=admin%2Fjt-workbench&columns=enableSignUp'
    try:
        app=request(path)
        before=dict(app)
        backup=ROOT/'signup-before-security-20261011.json'
        if not backup.exists():
            with backup.open('x',encoding='utf-8') as handle:json.dump({'enableSignUp':app.get('enableSignUp')},handle)
        app['enableSignUp']=False
        request(update,app)
        after=request(path)
        assert after.get('enableSignUp') is False
        for field in ('clientId','clientSecret','redirectUris','grantTypes','organization','providers','signinMethods','signupItems'):
            assert before.get(field)==after.get(field), 'Unrelated identity field changed'
        print(json.dumps({'public_signup_disabled':True,'existing_identities_and_login_preserved':True}))
    finally:
        request('/api/logout')


if __name__=='__main__':main()
