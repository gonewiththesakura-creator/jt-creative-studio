"""Reusable credentials through the real HTTP boundary, without provider calls."""
import json
from urllib.parse import urlencode

import pytest

from test_membership_http import membership_env, json_request, request, put_job
from test_server_review_regressions import panel


@pytest.fixture
def env(membership_env):
    membership_env.gateway.login_mode = 'access_code'
    return membership_env


def issue(env):
    plan = env.store.save_plan(env.users['admin']['id'], {
        'name': 'Monthly', 'duration_days': 30, 'image_units': 10, 'video_units': 3,
    })
    return env.store.issue_access_codes(env.users['admin']['id'], plan['id'])[0]


def login(env, code, **kwargs):
    return json_request(env, 'POST', '/api/auth/code-login', {'code': code},
                        headers={'Origin': env.gateway.origin, **kwargs})


def cookie(headers):
    return headers['Set-Cookie'].split(';', 1)[0]


def test_same_code_two_browsers_preserves_identity_and_entitlement(env):
    code = issue(env)['code']
    status, result, first = login(env, code)
    assert status == 200 and result == {'ok': True}
    assert all(flag in first['Set-Cookie'] for flag in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'))
    status, result, second = login(env, code.lower())
    assert status == 200 and cookie(first) != cookie(second)
    users = []
    for response in (first, second):
        status, me, _ = json_request(env, 'GET', '/api/auth/me', headers={'Cookie': cookie(response)})
        assert status == 200 and me['authenticated'] and me['membership']['image_remaining'] == 10
        users.append(me['user']['id'])
        assert not any(field in me['user'] for field in ('owner_key', 'access_credential_id', 'code_hash'))
        assert code not in json.dumps(me)
    assert users[0] == users[1]


@pytest.mark.parametrize('headers', [
    {'Origin': None}, {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'},
    {'Content-Type': 'application/x-www-form-urlencoded'},
])
def test_login_rejects_cross_origin_and_non_json(env, headers):
    before = len(env.store.list_users(env.users['admin']['id']))
    status, _, _ = login(env, issue(env)['code'], **headers)
    assert status in (400, 403)
    assert len(env.store.list_users(env.users['admin']['id'])) == before


def test_code_cannot_be_supplied_in_query_or_extra_fields(env):
    value = issue(env)['code']
    status, _, _ = json_request(env, 'POST', '/api/auth/code-login?code=redacted', {'code': value},
                               headers={'Origin': env.gateway.origin})
    assert status == 400
    status, _, _ = json_request(env, 'POST', '/api/auth/code-login', {'code': value, 'is_admin': True},
                               headers={'Origin': env.gateway.origin})
    assert status == 400
    assert json_request(env, 'GET', '/api/auth/code-login')[0] == 404


def test_invalid_revoked_and_disabled_have_same_public_error(env):
    item = issue(env)
    invalid = login(env, 'invalid')[:2]
    env.store.revoke_access_code(env.users['admin']['id'], item['id'])
    assert login(env, item['code'])[:2] == invalid
    item = issue(env)
    user = env.store.authenticate_access_code(item['code'])
    env.store.set_user_disabled(env.users['admin']['id'], user['id'], True)
    assert login(env, item['code'])[:2] == invalid
    assert invalid[0] == 401


def test_login_rate_limit(env):
    for _ in range(20):
        assert login(env, 'invalid')[0] == 401
    assert login(env, issue(env)['code'])[0] == 429


def test_code_login_cannot_view_legacy_owner_jobs_or_admin(env):
    put_job(env, owner='admin')
    _, _, headers = login(env, issue(env)['code'])
    authenticated = {'Cookie': cookie(headers)}
    status, jobs, _ = json_request(env, 'GET', '/api/jobs', headers=authenticated)
    assert status == 200 and jobs == []
    assert json_request(env, 'GET', '/api/admin/membership/users', headers=authenticated)[0] == 403
    assert request(env, 'GET', '/api/result-media/'+'a'*12+'/0', headers=authenticated)[0] == 404


def test_admin_rotate_preserves_original_user_and_invalidates_old_sessions(env):
    item = issue(env)
    _, _, first = login(env, item['code'])
    _, me, _ = json_request(env, 'GET', '/api/auth/me', headers={'Cookie': cookie(first)})
    status, result, _ = json_request(env, 'POST', '/api/admin/membership/users/rotate-code',
                                    {'user_id': me['user']['id'], 'note': 'Verified lost credential'}, user='admin')
    assert status == 200
    assert login(env, item['code'])[0] == 401
    assert json_request(env, 'GET', '/api/jobs', headers={'Cookie': cookie(first)})[0] == 401
    _, _, new = login(env, result['code']['code'])
    _, after, _ = json_request(env, 'GET', '/api/auth/me', headers={'Cookie': cookie(new)})
    assert after['user']['id'] == me['user']['id']
    assert after['membership']['id'] == me['membership']['id']


def test_admin_code_writes_require_csrf_and_ordinary_users_cannot_issue(env):
    item = issue(env)
    body = {'plan_id': item['plan_id']}
    assert json_request(env, 'POST', '/api/admin/membership/access-codes', body, user='alice')[0] == 403
    assert json_request(env, 'POST', '/api/admin/membership/access-codes', body, user='admin', headers={'X-CSRF-Token': None})[0] == 403
    status, result, _ = json_request(env, 'POST', '/api/admin/membership/access-codes', body, user='admin')
    assert status == 200 and len(result['codes']) == 1
    _, listing, _ = json_request(env, 'GET', '/api/admin/membership/access-codes', user='admin')
    assert not any('code' in row or 'code_hash' in row for row in listing['codes'])


def test_code_logout_revokes_local_session_without_external_redirect(env):
    _, _, headers = login(env, issue(env)['code'])
    _, me, _ = json_request(env, 'GET', '/api/auth/me', headers={'Cookie': cookie(headers)})
    status, result, _ = json_request(env, 'POST', '/api/auth/logout', {}, headers={
        'Cookie': cookie(headers), 'Origin': env.gateway.origin, 'X-CSRF-Token': me['csrf_token']})
    assert status == 200 and result['logout_url'] == ''
    assert json_request(env, 'GET', '/api/jobs', headers={'Cookie': cookie(headers)})[0] == 401


def test_non_admin_oidc_callback_cannot_bypass_code_login(env):
    _, _, response = json_request(env, 'GET', '/api/auth/login')
    state = env.oidc.authorizations[-1][0]
    status, result, _ = json_request(env, 'GET', '/api/auth/callback?' + urlencode({
        'state': state, 'code': 'valid-authorization-code'}),
        headers={'Cookie': response['Set-Cookie'].split(';', 1)[0]})
    assert status == 403 and result['code'] == 'access_code_required'


def test_mode_can_be_switched_without_reinterpreting_existing_sessions(env):
    assert json_request(env, 'GET', '/api/auth/me', user='admin')[1]['user']['is_admin']
    env.gateway.login_mode = 'oidc'
    assert login(env, issue(env)['code'])[0] == 404
