#!/usr/bin/env python3
"""Public-HTTPS login-code verification with zero-quota disposable test data.

Run only after release and owner binding. Never generates, uploads, fetches a
provider, imports the server or modifies a production ledger/database directly.
All requests are allowlisted; every test credential exists only in memory.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request

ROOT = Path('/opt/jt-identity')
DATA = Path('/home/admin/comfy-panel/panel_data')
ORIGIN = 'https://studio.dreamapi.club'
WRITES = frozenset(('/api/auth/code-login','/api/auth/logout','/api/admin/membership/plans',
    '/api/admin/membership/access-codes','/api/admin/membership/access-codes/revoke',
    '/api/admin/membership/users/rotate-code','/api/admin/membership/users/disable'))


class CheckFailed(Exception):
    pass


def require(condition, label):
    if not condition:
        raise CheckFailed(label)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), NoRedirect())
        self.csrf = None

    def request(self, path, body=None):
        if body is None:
            require(path in ('/api/auth/me','/api/jobs','/api/favorites','/api/admin/membership/users')
                or re.fullmatch(r'/api/job/[0-9a-f]{12}',path), 'read_path_not_allowlisted')
        else:
            require(path in WRITES, 'write_path_not_allowlisted')
        headers = {'Accept':'application/json','Accept-Encoding':'identity'}
        if body is not None:
            headers.update({'Origin':ORIGIN,'Sec-Fetch-Site':'same-origin','Content-Type':'application/json'})
            if self.csrf:
                headers['X-CSRF-Token'] = self.csrf
        request = urllib.request.Request(ORIGIN+path,headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            response = self.client.open(request,timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        except Exception:
            raise CheckFailed('http_transport_failed') from None
        with response:
            try:
                result = json.loads(response.read(4*1024*1024))
            except ValueError:
                raise CheckFailed('non_json_response') from None
            return response.code,result

    def login(self, code):
        status,_ = self.request('/api/auth/code-login',{'code':code})
        require(status == 200,'code_login_failed')
        status,account = self.request('/api/auth/me')
        require(status == 200 and account.get('authenticated') is True
            and account.get('login_method') == 'access_code','code_session_missing')
        self.csrf = account['csrf_token']
        return account


def private_report(path, report):
    temporary = path.with_name(path.name+'.pending')
    with temporary.open('w',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary,0o600)
    os.replace(temporary,path)


def rows(sql, values=()):
    with sqlite3.connect('file:'+str(DATA/'membership.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql,values)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    require(os.geteuid() == 0,'root_required')
    os.umask(0o077)
    run = time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+secrets.token_hex(6)
    report_path = (args.report or ROOT/('verify-access-code-'+run+'.json')).resolve()
    require(report_path.parent == ROOT and report_path.name.startswith('verify-access-code-')
        and report_path.suffix == '.json' and not report_path.exists(),'report_path_invalid_or_exists')
    handoff = json.loads((ROOT/'owner-access-code.json').read_text())
    owner_id = handoff['user_id']
    owner,owner_again,member,member_again,replacement = [Browser() for _ in range(5)]
    note = 'JT activation login verification '+run
    plan_name = '登录验证（零额度） '+run
    plan_values = {'name':plan_name,'duration_days':1,'image_units':0,'video_units':0,
        'max_concurrent':1,'features':['history','favorites'],'backends':['cloud'],
        'active':True,'price_display':'仅上线验证，不销售'}
    before = {name:(DATA/name).read_bytes() for name in ('jobs.json','favorites.json')}
    jobs = json.loads(before['jobs.json'])
    original_owner_jobs = [row for row in jobs.values() if row.get('owner_user_id') == owner_id]
    require(bool(original_owner_jobs),'original_owner_jobs_missing')
    cross_job = original_owner_jobs[0]['id']
    report = {'phase':'started','checks':{},'cleanup':{},'generation_upload_provider_requests':0}
    private_report(report_path,report)
    checks,cleanup = report['checks'],report['cleanup']
    failure = None
    test_user_id = None
    try:
        first = owner.login(handoff['code'])
        require(first['user']['id'] == owner_id and first['user']['is_admin'] is True,'owner_identity_or_admin_mismatch')
        checks['owner_code_login_admin'] = True
        initial_lists = {}
        for path in ('/api/jobs','/api/favorites'):
            status,result = owner.request(path)
            require(status == 200 and isinstance(result,list),'owner_list_read_failed')
            initial_lists[path] = result
        report['owner_jobs_in_ledger'] = len(original_owner_jobs)
        report['owner_history_page_count'] = len(initial_lists['/api/jobs'])
        report['owner_favorites_count'] = len(initial_lists['/api/favorites'])
        owner_rows = rows('SELECT owner_key FROM users WHERE id=?',(owner_id,))
        require(len(owner_rows) == 1,'original_owner_row_missing')
        owner_hash = hashlib.sha256(('jt-session:'+owner_rows[0]['owner_key']).encode()).hexdigest()
        expected_favorites = {row['id'] for row in json.loads(before['favorites.json']).values()
            if row.get('owner_session_hash') == owner_hash}
        require({row['id'] for row in initial_lists['/api/favorites']} == expected_favorites,'owner_favorites_not_original')
        require(all(row['id'] in jobs and jobs[row['id']].get('owner_user_id') == owner_id
            for row in initial_lists['/api/jobs']),'owner_history_not_original')
        second = owner_again.login(handoff['code'])
        require(second['user']['id'] == owner_id and second['membership'] == first['membership'],'owner_relogin_changed_identity_or_entitlement')
        for path,initial in initial_lists.items():
            status,result = owner_again.request(path)
            require(status == 200 and {row['id'] for row in result} == {row['id'] for row in initial},'owner_relogin_changed_visible_data')
        checks['owner_repeat_login_preserves_account_entitlement_data'] = True
        status,result = owner.request('/api/admin/membership/plans',plan_values)
        require(status == 200,'test_plan_create_failed')
        plan_id = result['plan']['id']
        status,result = owner.request('/api/admin/membership/access-codes',{'plan_id':plan_id,'count':1,'note':note})
        require(status == 200 and len(result.get('codes',[])) == 1,'test_credential_issue_failed')
        original_code = result['codes'][0]['code']
        first_member = member.login(original_code)
        test_user_id = first_member['user']['id']
        require(test_user_id != owner_id and first_member['user']['is_admin'] is False,'test_account_identity_unsafe')
        entitlement = first_member['membership']
        require(entitlement['image_remaining'] == entitlement['video_remaining'] == 0
            and set(entitlement['plan']['features']) == {'history','favorites'},'test_plan_not_zero_quota')
        for path in ('/api/jobs','/api/favorites'):
            status,result = member.request(path)
            require(status == 200 and result == [],'new_account_private_data_not_empty')
        require(member.request('/api/admin/membership/users')[0] == 403,'ordinary_admin_not_denied')
        require(member.request('/api/job/'+cross_job)[0] == 404,'cross_account_task_not_denied')
        checks['ordinary_empty_lists_admin403_cross_task404'] = True
        repeated = member_again.login(original_code)
        require(repeated['user']['id'] == test_user_id and repeated['membership'] == entitlement,'test_relogin_changed_identity_or_entitlement')
        checks['test_repeat_login_does_not_redeem_again'] = True
        # Exactly one replacement request. A lost response is cleaned by the
        # unique run note; it is never retried or used to rotate another user.
        status,result = owner.request('/api/admin/membership/users/rotate-code',{'user_id':test_user_id,'note':note})
        require(status == 200,'test_rotation_failed')
        new_code = result['code']['code']
        status,rejected = Browser().request('/api/auth/code-login',{'code':original_code})
        require(status == 401 and rejected.get('code') == 'invalid_access_code','old_code_not_revoked')
        require(member.request('/api/jobs')[0] == 401 and member_again.request('/api/jobs')[0] == 401,'old_sessions_not_revoked')
        new_account = replacement.login(new_code)
        require(new_account['user']['id'] == test_user_id and new_account['membership'] == entitlement,'rotation_changed_account_or_entitlement')
        checks['rotation_once_revokes_old_code_sessions_preserves_account'] = True
    except Exception as error:
        failure = str(error) if isinstance(error,CheckFailed) else type(error).__name__
    finally:
        # Resolve only this run's unique note, including requests whose response
        # was lost. No database writes or broad account deletion are used.
        try:
            credentials = rows('SELECT id,user_id FROM login_credentials WHERE created_by=? AND note=?',(owner_id,note))
            test_users = {row['user_id'] for row in credentials if row['user_id']}
            safe_users = rows('SELECT id FROM users WHERE issuer=?',('urn:jt:access-code',))
            require(owner_id not in test_users and test_users <= {row['id'] for row in safe_users},'cleanup_scope_unsafe')
            cleanup['test_users_disabled'] = all(owner.request('/api/admin/membership/users/disable',
                {'user_id':user_id,'disabled':True})[0] == 200 for user_id in test_users)
            cleanup['test_credentials_revoked'] = all(owner.request('/api/admin/membership/access-codes/revoke',
                {'code_id':row['id']})[0] == 200 for row in credentials)
            plans = rows('SELECT id FROM plans WHERE name=?',(plan_name,))
            require(len(plans) <= 1,'cleanup_plan_ambiguous')
            cleanup['test_plan_disabled'] = all(owner.request('/api/admin/membership/plans',
                {**plan_values,'plan_id':row['id'],'active':False})[0] == 200 for row in plans)
            if test_user_id:
                checks['disabled_test_session401'] = replacement.request('/api/jobs')[0] == 401
        except Exception as error:
            cleanup['complete'] = False
            report['cleanup_error'] = str(error) if isinstance(error,CheckFailed) else type(error).__name__
        else:
            cleanup['complete'] = all(cleanup.values())
        # Revoke only the two verifier-owned owner sessions, not the owner's
        # credential or the browser the operator is currently using.
        for label,browser in (('owner_verifier_session_logged_out',owner),('second_owner_verifier_session_logged_out',owner_again)):
            try:
                cleanup[label] = browser.request('/api/auth/logout',{})[0] == 200 if browser.csrf else True
            except Exception:
                cleanup[label] = False
        after = {name:(DATA/name).read_bytes() for name in before}
        report['ledger_hashes_unchanged'] = {name:hashlib.sha256(raw).digest() == hashlib.sha256(after[name]).digest() for name,raw in before.items()}
        after_jobs = json.loads(after['jobs.json'])
        report['jobs_added_during_verification'] = len(set(after_jobs)-set(jobs))
        report['original_job_ids_still_present'] = set(jobs) <= set(after_jobs)
        report['ledger_restore_attempted'] = False
        report['test_audit_records_retained'] = True
        report['success'] = failure is None and all(checks.values()) and all(cleanup.values()) and all(report['ledger_hashes_unchanged'].values())
        report['phase'] = 'verified' if report['success'] else 'needs_review'
        if failure:
            report['failed_check'] = failure
        private_report(report_path,report)
        print(json.dumps(report,ensure_ascii=False))
        print(json.dumps({'private_report':str(report_path),'report_mode_0600':report_path.stat().st_mode & 0o777 == 0o600}))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # No traceback or arbitrary HTTP exception text can reveal credentials.
        print(json.dumps({'success':False,'setup_failed':str(error) if isinstance(error,CheckFailed) else type(error).__name__}))
        sys.exit(1)
