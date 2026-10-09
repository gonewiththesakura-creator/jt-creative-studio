#!/usr/bin/env python3
"""Verify live HTTPS membership with a disposable identity and zero admitted jobs.

Run as root on the production host only after the coordinated cutover. Uses
normal public HTTP flows; never imports server.py or edits production ledgers.
Only this run's test account, test plan and test activation codes are changed.
Secrets, codes, prompts and media addresses are never printed or saved in audit.
"""
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path('/opt/jt-identity')
DATA = Path('/home/admin/comfy-panel/panel_data')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), NoRedirect())
        self.csrf = None

    def request(self, origin, path, body=None, headers=None, binary=False):
        if not path.startswith('/') or path.startswith('//'):
            raise RuntimeError('Refused a non-local request path')
        request_headers = {'Accept':'application/json', 'Accept-Encoding':'identity'}
        if body is not None:
            request_headers.update({'Content-Type':'application/json', 'Origin':origin})
            if self.csrf:
                request_headers['X-CSRF-Token'] = self.csrf
        request_headers.update(headers or {})
        req = urllib.request.Request(origin+path,
            data=None if body is None else json.dumps(body).encode(), headers=request_headers)
        try:
            response = self.client.open(req, timeout=45)
        except urllib.error.HTTPError as error:
            response = error
        except Exception:
            raise RuntimeError('HTTP transport failed') from None
        with response:
            # Reading a range response never downloads a whole user video.
            content = response.read(33 if binary else 8*1024*1024)
            if binary:
                result = content
            elif 300 <= response.code < 400:
                # OIDC logout uses an HTML redirect body; do not parse it as JSON.
                result = {}
            else:
                try:
                    result = json.loads(content) if content else {}
                except ValueError:
                    raise RuntimeError('Expected JSON response') from None
            return response.code, result, response.headers


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def clean_result_urls(value, public_origin):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('original_url', 'provider_media', 'owner_session_hash', 'request_session_hash'):
                return False
            if ('url' in key.lower() and isinstance(child, str) and child.startswith(('http:', 'https:'))
                    and not child.startswith(public_origin+'/')):
                return False
            if not clean_result_urls(child, public_origin):
                return False
    elif isinstance(value, list):
        return all(clean_result_urls(child, public_origin) for child in value)
    return True


def login(browser, credentials, username, password):
    public, issuer = credentials['public_origin'], credentials['issuer']
    status, _, headers = browser.request(public, '/api/auth/login')
    require(status == 302, 'JT login redirect failed')
    redirect = urllib.parse.urlsplit(headers.get('Location', ''))
    require(redirect.scheme+'://'+redirect.netloc == issuer, 'Unexpected authorization origin')
    query = {k:v[0] for k,v in urllib.parse.parse_qs(redirect.query).items()}
    require(query.get('prompt') == 'login' and query.get('code_challenge_method') == 'S256', 'Reauthentication or PKCE absent')
    fields = {'clientId':query['client_id'], 'responseType':query['response_type'],
        'redirectUri':query['redirect_uri'], 'type':'code', 'scope':query['scope'],
        'state':query['state'], 'nonce':query['nonce'], 'prompt':'login',
        'code_challenge':query['code_challenge'], 'code_challenge_method':'S256'}
    status, result, _ = browser.request(issuer, '/api/login?'+urllib.parse.urlencode(fields), {
        'application':'jt-workbench', 'organization':'jt-users', 'username':username, 'password':password,
        'type':'code', 'autoSignin':False, 'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
    require(status == 200 and result.get('status') == 'ok' and isinstance(result.get('data'), str), 'Identity login failed')
    status, _, _ = browser.request(public, '/api/auth/callback?'+urllib.parse.urlencode({'state':query['state'], 'code':result['data']}))
    require(status == 302, 'JT callback failed')
    status, account, _ = browser.request(public, '/api/auth/me')
    require(status == 200 and account.get('authenticated') is True, 'JT session missing')
    browser.csrf = account['csrf_token']
    return account


def verify_logout_only():
    os.umask(0o077)
    require(os.geteuid() == 0, 'Run on production host as root')
    credentials = json.loads((ROOT/'bootstrap-credentials.json').read_text())
    public, issuer = credentials['public_origin'], credentials['issuer']
    owner = Browser()
    login(owner, credentials, 'owner', credentials['workbench_owner_password'])
    status, result, _ = owner.request(public, '/api/auth/logout', {})
    target = urllib.parse.urlsplit(result.get('logout_url',''))
    require(status == 200 and target.scheme+'://'+target.netloc == issuer and target.path == '/api/logout', 'JT logout URL invalid')
    query = urllib.parse.parse_qs(target.query)
    require(query.get('post_logout_redirect_uri') == [public+'/'], 'JT logout return URL invalid')
    status, _, headers = owner.request(issuer, target.path+'?'+target.query)
    target = urllib.parse.urlsplit(headers.get('Location',''))
    require(status == 302 and target.scheme+'://'+target.netloc+(target.path or '/') == public+'/', 'Identity logout return failed')
    report = {'jt_logout_ok':True, 'casdoor_logout_redirect_ok':True,
        'owner_logout_session401':owner.request(public, '/api/jobs')[0] == 401}
    require(all(report.values()), 'Owner logout verification failed')
    (ROOT/'workbench-live-logout-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0


def main():
    os.umask(0o077)
    require(os.geteuid() == 0, 'Run on production host as root')
    credentials = json.loads((ROOT/'bootstrap-credentials.json').read_text())
    public, issuer = credentials['public_origin'], credentials['issuer']
    run = secrets.token_hex(6)
    username = 'jt-live-test-'+run
    password = 'Jt!9'+secrets.token_urlsafe(24)
    owner, ordinary, identity_admin = Browser(), Browser(), Browser()
    report, cleanups = {}, {}
    test_user_id = plan = None
    identity_created = False
    issued, redeemed = [], set()
    snapshots = {name:(DATA/name).read_bytes() for name in ('jobs.json','favorites.json')}
    jobs = json.loads(snapshots['jobs.json'])
    favorites = json.loads(snapshots['favorites.json'])
    original_job_ids = set(jobs)
    failure = None
    try:
        account = login(owner, credentials, 'owner', credentials['workbench_owner_password'])
        owner_id = account['user']['id']
        require(account['user']['is_admin'] is True, 'Owner not administrator')
        report['owner_real_oidc_login_admin'] = True
        require(all(job.get('owner_user_id') == owner_id for job in jobs.values()), 'Legacy job owner mismatch')
        report['legacy_jobs_owned'] = len(jobs)
        report['legacy_favorites_preserved'] = len(favorites)
        for path in ('/api/jobs', '/api/favorites', '/api/health'):
            status, result, _ = owner.request(public, path)
            require(status == 200 and clean_result_urls(result, public), 'Owner private response or URL sanitization failed')
        report['owner_data_access_and_provider_urls_hidden'] = True
        # Select only a completed, already-existing remote video; no generation.
        candidates = [(job, index) for job in sorted(jobs.values(), key=lambda row:row.get('created',0), reverse=True)
            if job.get('status') == 'done' for index, media in enumerate(job.get('images') or [])
            if media.get('remote') and (str(media.get('file','')).lower().endswith(('.mp4','.webm','.mov'))
                or str(media.get('file_type','')).lower() in ('mp4','video/mp4','webm','video/webm'))]
        require(bool(candidates), 'No existing video available for range validation')
        range_ok = False
        for job, index in candidates[:3]:
            status, data, headers = owner.request(public, '/api/result-media/'+job['id']+'/'+str(index),
                headers={'Range':'bytes=0-31'}, binary=True)
            if status == 206 and len(data) == 32 and headers.get('Content-Range','').startswith('bytes 0-31/'):
                range_ok = True
                break
        require(range_ok, 'Existing result range playback failed')
        report['existing_video_range_206_bytes'] = 32
        cross_job = next(iter(jobs))
        _, signup, _ = ordinary.request(issuer, '/api/signup', {'application':'jt-workbench', 'organization':'jt-users',
            'username':username, 'name':'上线隔离验证 '+run, 'password':password, 'confirm':password,
            'language':'zh', 'type':'signup', 'isAdmin':True, 'roles':['admin']})
        require(signup.get('status') == 'ok', 'Disposable signup failed')
        identity_created = True
        member = login(ordinary, credentials, username, password)
        test_user_id = member['user']['id']
        require(member['user']['is_admin'] is False and member.get('membership') is None, 'New member gained privilege')
        for path in ('/api/jobs', '/api/favorites'):
            status, result, _ = ordinary.request(public, path)
            require(status == 200 and result == [], 'New account private lists are not empty')
        report['new_member_private_lists_empty'] = True
        require(ordinary.request(public, '/api/admin/membership/users')[0] == 403, 'Ordinary account reached administration')
        require(ordinary.request(public, '/api/job/'+cross_job)[0] == 404, 'Cross-account task read allowed')
        require(ordinary.request(public, '/api/result-media/'+cross_job+'/0', binary=True)[0] == 404, 'Cross-account media allowed')
        report['ordinary_admin403_cross_account404'] = True
        # The reviewed service reserves membership before creating/admitting work.
        # Precheck the sole disposable identity has no entitlement, then exercise
        # the actual denial once, before issuing any test activation code.
        with sqlite3.connect('file:'+str(DATA/'membership.sqlite3')+'?mode=ro', uri=True) as db:
            require(db.execute('SELECT COUNT(*) FROM entitlements WHERE user_id=?',(test_user_id,)).fetchone()[0] == 0,
                    'Refused denial test for an entitled identity')
        status, denied, _ = ordinary.request(public, '/api/generate', {'workflow':'anima02', 'prompt':'Membership boundary verification',
            'prompt_mode':'manual', 'width':768, 'height':1024, 'batch':1, 'hd':0, 'seed':321,
            'seed_mode':'fixed', 'style_id':'sketch', 'style_variant':'default', 'mode':'character',
            'generation_backend':'cloud', 'client_request_id':'membership-denial-'+run})
        require(status == 403 and denied.get('code') == 'plan_required', 'Missing-plan generation was not rejected')
        require(set(json.loads((DATA/'jobs.json').read_bytes())) == original_job_ids, 'Denial test admitted a task')
        report['no_plan_generate403_no_job_created'] = True
        values = {'name':'上线验证套餐 '+run, 'duration_days':1, 'image_units':1, 'video_units':1,
            'max_concurrent':1, 'features':['image','video','upload','history','favorites'],
            'backends':['cloud'], 'active':True, 'price_display':'仅测试，不销售'}
        status, result, _ = owner.request(public, '/api/admin/membership/plans', values)
        require(status == 200, 'Test plan creation failed')
        plan = result['plan']
        status, result, _ = owner.request(public, '/api/admin/membership/codes', {'plan_id':plan['id'], 'count':2, 'note':'上线隔离验证 '+run})
        require(status == 200, 'Test code creation failed')
        issued = result['codes']
        require(len(issued) == 2, 'Test code count mismatch')
        status, result, _ = ordinary.request(public, '/api/membership/redeem', {'code':issued[0]['code']})
        require(status == 200, 'First test redemption failed')
        redeemed.add(issued[0]['id'])
        entitlement = result['membership']
        require(entitlement['image_remaining'] == 1 and entitlement['video_remaining'] == 1
            and entitlement['plan']['duration_days'] == 1 and entitlement['active'], 'Test entitlement mismatch')
        status, repeated, _ = ordinary.request(public, '/api/membership/redeem', {'code':issued[0]['code']})
        require(status == 400 and repeated.get('code') == 'invalid_code', 'Activation code reuse allowed')
        report['plan_issue_redeem_once_and_replay_denied'] = True
        status, _, _ = owner.request(public, '/api/admin/membership/users/disable', {'user_id':test_user_id, 'disabled':True})
        require(status == 200 and ordinary.request(public, '/api/jobs')[0] == 401, 'Disabled account retained session')
        cleanups['test_jt_user_disabled'] = True
        report['account_disable_revokes_session401'] = True
    except Exception as error:
        # Error messages in this file are fixed labels, never HTTP bodies.
        failure = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        for label, action in [
            ('test_jt_user_disabled', lambda: owner.request(public, '/api/admin/membership/users/disable', {'user_id':test_user_id,'disabled':True})[0] == 200 if test_user_id else True),
            ('test_plan_disabled', lambda: owner.request(public, '/api/admin/membership/plans',
                {**{k:plan[k] for k in ('name','duration_days','image_units','video_units','max_concurrent','features','backends','price_display')},
                    'plan_id':plan['id'],'active':False})[0] == 200 if plan else True),
        ]:
            try:
                cleanups[label] = action()
            except Exception:
                cleanups[label] = False
        try:
            cleanups['unused_test_codes_revoked'] = all(owner.request(public, '/api/admin/membership/codes/revoke',
                {'code_id':row['id']})[0] == 200 for row in issued if row['id'] not in redeemed)
        except Exception:
            cleanups['unused_test_codes_revoked'] = False
        if identity_created:
            try:
                _, admin_login, _ = identity_admin.request(issuer, '/api/login', {'application':'app-built-in', 'organization':'built-in',
                    'username':'admin', 'password':credentials['identity_admin_password'], 'type':'login',
                    'signinMethod':'Password', 'loginMethod':'password', 'language':'zh'})
                require(admin_login.get('status') == 'ok', 'Identity cleanup authentication failed')
                _, removed, _ = identity_admin.request(issuer, '/api/delete-user', {'owner':'jt-users','name':username})
                cleanups['test_identity_removed'] = removed.get('status') == 'ok'
                identity_admin.request(issuer, '/api/logout')
            except Exception:
                cleanups['test_identity_removed'] = False
        try:
            status, logout, _ = owner.request(public, '/api/auth/logout', {})
            logout_url = urllib.parse.urlsplit(logout.get('logout_url',''))
            require(status == 200 and logout_url.scheme+'://'+logout_url.netloc == issuer and logout_url.path == '/api/logout',
                'JT logout URL invalid')
            owner.request(issuer, logout_url.path+'?'+logout_url.query)
            report['owner_logout_session401'] = owner.request(public, '/api/jobs')[0] == 401
        except Exception:
            report['owner_logout_session401'] = False
        report['no_real_job_or_favorite_changes'] = all((DATA/name).read_bytes() == contents for name,contents in snapshots.items())
        report['cleanup'] = cleanups
        report['paid_generation_admitted'] = False if set(json.loads((DATA/'jobs.json').read_bytes())) == original_job_ids else 'unexpected_job_change'
        report['success'] = failure is None and all(cleanups.values()) and report.get('owner_logout_session401',False) and report['no_real_job_or_favorite_changes']
        if failure:
            report['failed_check'] = failure
        (ROOT/('workbench-live-verification-'+run+'.json')).write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    sys.exit(verify_logout_only() if sys.argv[1:] == ['--logout-only'] else main())
