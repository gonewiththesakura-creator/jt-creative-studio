"""Keep the old-cache isolation migration without clearing assets on refresh."""
from test_membership_http import membership_env, json_request
from test_server_review_regressions import panel
import pytest


def test_me_migrates_once_but_switching_account_migrates_again(membership_env):
    env = membership_env
    def session_cookie(name):
        return env.gateway.COOKIE + '=' + env.sessions[name]['token']
    status, _, first = json_request(env, 'GET', '/api/auth/me', headers={'Cookie':session_cookie('alice')})
    assert status == 200 and first['Clear-Site-Data'] == '"cache"'
    marker = first['Set-Cookie'].split(';',1)[0]
    assert 'Secure' in first['Set-Cookie'] and 'HttpOnly' in first['Set-Cookie']
    status, _, again = json_request(env, 'GET', '/api/auth/me', headers={'Cookie':session_cookie('alice')+'; '+marker})
    assert status == 200 and 'Clear-Site-Data' not in again and 'Set-Cookie' not in again
    status, data, switched = json_request(env, 'GET', '/api/auth/me', headers={'Cookie':session_cookie('bob')+'; '+marker})
    assert status == 200 and data['user']['id'] == env.users['bob']['id']
    assert switched['Clear-Site-Data'] == '"cache"'
    assert switched['Set-Cookie'].split(';',1)[0] != marker


def test_migration_marker_never_authenticates_anonymous_requests(membership_env):
    env = membership_env
    _, _, first = json_request(env, 'GET', '/api/auth/me')
    marker = first['Set-Cookie'].split(';',1)[0]
    _, me, again = json_request(env, 'GET', '/api/auth/me', headers={'Cookie':marker})
    assert not me['authenticated'] and 'Clear-Site-Data' not in again
    assert json_request(env, 'GET', '/api/jobs', headers={'Cookie':marker})[0] == 401


@pytest.mark.parametrize('value', ['"é"', '20251012.'+'a'*24, 'a'*4096])
def test_malformed_migration_marker_is_replaced_without_authenticating(membership_env, value):
    env = membership_env
    status, me, headers = json_request(env, 'GET', '/api/auth/me', headers={
        'Cookie': env.gateway.CACHE_MIGRATION_COOKIE + '=' + value})
    assert status == 200 and not me['authenticated']
    assert headers['Clear-Site-Data'] == '"cache"'
    assert env.gateway.CACHE_MIGRATION_COOKIE + '=' in headers['Set-Cookie']
