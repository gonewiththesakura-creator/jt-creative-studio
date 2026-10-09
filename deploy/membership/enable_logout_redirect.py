#!/usr/bin/env python3
"""Add only the exact JT home logout redirect through Casdoor's admin API."""
import http.cookiejar
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request


def main():
    os.umask(0o077)
    root = Path('/opt/jt-identity')
    credentials = json.loads((root/'bootstrap-credentials.json').read_text())
    origin = credentials['issuer']
    desired = [credentials['public_origin']+'/api/auth/callback', credentials['public_origin']+'/']
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        req = urllib.request.Request(origin+path, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json', 'Accept':'application/json', 'Origin':origin})
        with client.open(req, timeout=20) as response:
            result = json.load(response)
        if result.get('status') != 'ok':
            raise RuntimeError('Identity configuration API did not accept the operation')
        return result.get('data')

    request('/api/login', {'application':'app-built-in', 'organization':'built-in', 'username':'admin',
        'password':credentials['identity_admin_password'], 'type':'login',
        'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
    path = '/api/get-application?id=admin%2Fjt-workbench'
    app = request(path)
    before = app.get('redirectUris')
    if before not in (desired, desired[:1]):
        raise RuntimeError('Unexpected existing redirect allowlist; refusing to replace it')
    if before != desired:
        (root/'logout-redirect-before.json').write_text(json.dumps({'redirectUris':before}, indent=2)+'\n')
        app['redirectUris'] = desired
        request('/api/update-application?id=admin%2Fjt-workbench&columns=redirectUris', app)
    current = request(path)
    if current.get('redirectUris') != desired:
        raise RuntimeError('Redirect allowlist did not persist')
    # This is an API update only. A sealed installation must never reapply init_data.
    state = json.loads((root/'state.json').read_text())
    assert state['phase'] == 'sealed'
    assert 'initDataFile = ""' in (root/'conf/app.conf').read_text()
    request('/api/logout')
    print(json.dumps({'exact_logout_redirect_added':True, 'callback_preserved':True,
                      'sealed_bootstrap_unchanged':True, 'identity_restart_required':False}))


if __name__ == '__main__':
    main()
