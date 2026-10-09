#!/usr/bin/env python3
"""Verify forced reauthentication and current-browser OIDC logout without JT jobs."""
import base64
import hashlib
import http.cookiejar
import json
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def main():
    root = Path('/opt/jt-identity')
    credentials = json.loads((root/'bootstrap-credentials.json').read_text())
    origin = credentials['issuer']
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect())

    def request(path, data=None):
        req = urllib.request.Request(origin+path, data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': origin})
        try:
            response = client.open(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            try:
                result = json.loads(body)
            except ValueError:
                result = {}
            return response.code, result, response.headers

    _, login, _ = request('/api/login', {'application':'jt-workbench', 'organization':'jt-users',
        'username':'owner', 'password':credentials['workbench_owner_password'], 'type':'login',
        'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
    report = {'password_login_succeeded': login.get('status') == 'ok'}
    cookie = next((item for item in jar if item.name == 'casdoor_session_id'), None)
    report['cookie_secure'] = bool(cookie and cookie.secure)
    report['cookie_http_only'] = bool(cookie and cookie.has_nonstandard_attr('HttpOnly'))
    report['cookie_samesite_lax'] = bool(cookie and cookie.get_nonstandard_attr('SameSite', '').lower() == 'lax')
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    redirect = credentials['public_origin']+'/api/auth/callback'
    params = {'clientId': credentials['client_id'], 'responseType':'code', 'redirectUri':redirect, 'type':'code',
        'scope':'openid profile email', 'state':secrets.token_urlsafe(24), 'nonce':secrets.token_urlsafe(24),
        'code_challenge_method':'S256', 'code_challenge':challenge}
    payload = {'application':'jt-workbench', 'organization':'jt-users', 'type':'code', 'language':'zh'}
    _, quick_login, _ = request('/api/login?'+urllib.parse.urlencode(params), payload)
    report['session_sso_available_before_logout'] = quick_login.get('status') == 'ok' and isinstance(quick_login.get('data'), str)
    params['prompt'] = 'login'
    _, forced, _ = request('/api/login?'+urllib.parse.urlencode(params), payload)
    report['prompt_login_rejects_session_only'] = forced.get('status') == 'error' and forced.get('data') == 'login_required'
    logout_state = secrets.token_urlsafe(24)
    logout_redirect = credentials['public_origin']+'/'
    logout_query = urllib.parse.urlencode({'client_id':credentials['client_id'],
        'post_logout_redirect_uri':logout_redirect, 'state':logout_state})
    status, _, headers = request('/api/logout?'+logout_query)
    location = urllib.parse.urlsplit(headers.get('Location', ''))
    report['logout_redirect_exact'] = status == 302 and location.scheme+'://'+location.netloc+(location.path or '/') == logout_redirect
    report['logout_returns_state'] = urllib.parse.parse_qs(location.query).get('state') == [logout_state]
    params.pop('prompt')
    _, after_logout, _ = request('/api/login?'+urllib.parse.urlencode(params), payload)
    report['session_sso_denied_after_logout'] = after_logout.get('status') == 'error'
    _, login_again, _ = request('/api/login', {'application':'jt-workbench', 'organization':'jt-users',
        'username':'owner', 'password':credentials['workbench_owner_password'], 'type':'login',
        'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
    report['password_login_succeeds_after_logout'] = login_again.get('status') == 'ok'
    request('/api/logout?'+logout_query)
    if not all(report.values()):
        raise RuntimeError('Logout checks failed: '+json.dumps(report))
    (root/'logout-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
