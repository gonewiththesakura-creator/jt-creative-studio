#!/usr/bin/env python3
"""Apply or restore only approved JT login appearance columns via official API."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path('/opt/jt-identity')
FIELDS = ('themeData','formOffset','title','favicon','logo','logoDark','formCss','formCssMobile')
PROTECTED = ('clientId','clientSecret','redirectUris','grantTypes','enableSignUp','organization',
             'tokenFormat','tokenSigningMethod','cert','providers','signinMethods','signupItems')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run on identity host as root')
    os.umask(0o077)
    if args.restore:
        backup = args.restore.resolve()
        if backup.parent != ROOT or not backup.name.startswith('identity-brand-before-'):
            raise RuntimeError('Restore must name a managed identity appearance backup')
        saved = json.loads(backup.read_text())
        if saved.get('application') != 'admin/jt-workbench' or set(saved.get('fields',{})) != set(FIELDS):
            raise RuntimeError('Appearance backup shape mismatch')
        desired = saved['fields']
    else:
        here = Path(__file__).resolve().parent
        desired = json.loads((here/'identity-brand-fields.json').read_text())
        css = (here/'identity-brand.css').read_text()
        if any(unsafe in css.lower() for unsafe in ('<script','<style','javascript:', '@import', 'url(')):
            raise RuntimeError('Appearance CSS must be self-contained')
        desired.update(formCss=css, formCssMobile=css)
        if set(desired) != set(FIELDS):
            raise RuntimeError('Unexpected appearance fields')
    credentials = json.loads((ROOT/'bootstrap-credentials.json').read_text())
    origin = credentials['issuer']
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        req = urllib.request.Request(origin+path, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json', 'Origin':origin, 'Accept':'application/json'})
        with client.open(req, timeout=30) as response:
            result = json.load(response)
        if result.get('status') != 'ok':
            raise RuntimeError('Identity appearance API operation failed')
        return result.get('data')

    path = '/api/get-application?id=admin%2Fjt-workbench'
    update_path = '/api/update-application?id=admin%2Fjt-workbench&columns='+urllib.parse.quote(','.join(FIELDS))
    request('/api/login', {'application':'app-built-in', 'organization':'built-in', 'username':'admin',
        'password':credentials['identity_admin_password'], 'type':'login',
        'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
    try:
        app = request(path)
        before = {key:app.get(key) for key in FIELDS}
        protected = {key:app.get(key) for key in PROTECTED}
        backup = ROOT/('identity-brand-before-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]+'.json')
        with backup.open('x',encoding='utf-8') as handle:
            json.dump({'application':'admin/jt-workbench','fields':before},handle,ensure_ascii=False,indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(backup,0o600)
        app.update(desired)
        try:
            request(update_path,app)
            actual = request(path)
            if any(actual.get(key) != value for key,value in desired.items()):
                raise RuntimeError('Appearance did not persist')
            if any(actual.get(key) != value for key,value in protected.items()):
                raise RuntimeError('Protected authentication settings changed unexpectedly')
        except Exception:
            app.update(before)
            request(update_path,app)
            raise
        print(json.dumps({'appearance_restored' if args.restore else 'appearance_updated':True,
            'appearance_readback_matches':True,'authentication_settings_unchanged':True,
            'backup':str(backup),'backup_mode_0600':backup.stat().st_mode & 0o777 == 0o600,'restart_required':False}))
    finally:
        request('/api/logout')


if __name__ == '__main__':
    main()
