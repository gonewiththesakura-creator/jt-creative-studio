"""2026-11-12: clearing failed / expired creator records, and the administrator's showcase cards.

Both go through the real bounded HTTP server with the membership gateway on, fully offline.
"""
import base64

import pytest

from test_membership_http import json_request, membership_env, put_job, request
from test_server_review_regressions import panel

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
PNG_URL = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


def creator_job(env, job_id, owner='alice', status='done', **changes):
    return put_job(env, owner, job_id, status, workflow='anima02', style_id='cold', video_queued=False,
                   images=[{'url': '/static/favicon.png', 'file': 'a.png'}] if status == 'done' else [], **changes)


def creator_ids(env, user='alice'):
    status, rows, _ = json_request(env, 'GET', '/api/jobs?scope=creator&limit=30', user=user)
    assert status == 200
    return sorted(row['id'] for row in rows)


def test_creator_clear_hides_failed_and_listed_records_of_the_caller_only(membership_env):
    env = membership_env
    creator_job(env, 'a' * 12)
    creator_job(env, 'b' * 12, status='error', error='boom')
    creator_job(env, 'c' * 12, status='cancelled')
    creator_job(env, 'd' * 12, status='running')
    creator_job(env, 'e' * 12, owner='bob', status='error')
    put_job(env, 'alice', 'f' * 12, 'error')  # a video record is not the creator's to clear
    assert creator_ids(env) == ['a' * 12, 'b' * 12, 'c' * 12, 'd' * 12]

    status, body, _ = json_request(env, 'POST', '/api/creator-clear', {'scope': 'errors'}, user='alice')
    assert (status, body['cleared_ids']) == (200, ['b' * 12, 'c' * 12])
    assert creator_ids(env) == ['a' * 12, 'd' * 12]
    assert creator_ids(env, 'bob') == ['e' * 12]
    assert not env.panel._jobs['f' * 12].get('history_cleared')
    status, counts, _ = json_request(env, 'GET', '/api/library-counts?scope=creator', user='alice')
    assert counts['history'] == 2

    # Listed records: a finished one goes, a running one and someone else's stay.
    status, body, _ = json_request(env, 'POST', '/api/creator-clear',
                                   {'ids': ['a' * 12, 'd' * 12, 'e' * 12, 'f' * 12]}, user='alice')
    assert (status, body['cleared_ids']) == (200, ['a' * 12])
    assert creator_ids(env) == ['d' * 12]
    assert env.panel._jobs['a' * 12]['images'], 'clearing is display only'
    assert not env.panel._jobs['e' * 12].get('history_cleared')
    # The record itself stays readable by its owner (favourites and prompts keep working).
    assert json_request(env, 'GET', '/api/job/' + 'a' * 12, user='alice')[0] == 200


def test_creator_clear_takes_unconfirmed_failures_and_a_recovered_job_shows_again(membership_env):
    """2026-11-12 (owner): a failure whose provider outcome was never confirmed could not be cleared."""
    env = membership_env
    creator_job(env, 'a' * 12, status='error', error='comfyui timeout after 1800s', provider_status='RUNNING',
                queue_hold=True)
    creator_job(env, 'b' * 12, status='recovering')
    assert not env.panel.video_ui_terminal(env.panel._jobs['a' * 12])
    status, body, _ = json_request(env, 'POST', '/api/creator-clear', {'scope': 'errors', 'ids': ['b' * 12]}, user='alice')
    assert (status, body['cleared_ids']) == (200, ['a' * 12])
    assert creator_ids(env) == ['b' * 12]
    # A later provider check finds the picture after all: the record is back in the library.
    env.panel._jobs['a' * 12].update(status='done', queue_hold=False, provider_status='SUCCESS',
                                     images=[{'url': '/static/favicon.png', 'file': 'a.png'}])
    assert creator_ids(env) == ['a' * 12, 'b' * 12]
    # Cleared again as a finished record, it stays hidden.
    assert json_request(env, 'POST', '/api/creator-clear', {'ids': ['a' * 12]}, user='alice')[1]['cleared_ids'] == ['a' * 12]
    assert creator_ids(env) == ['b' * 12]


@pytest.mark.parametrize('payload', [{}, {'scope': 'history'}, {'ids': 'x'}, {'ids': ['nope']}, {'ids': ['a' * 12] * 61},
                                     {'scope': 'errors', 'extra': 1}])
def test_creator_clear_rejects_bad_requests(membership_env, payload):
    creator_job(membership_env, 'a' * 12, status='error')
    assert json_request(membership_env, 'POST', '/api/creator-clear', payload, user='alice')[0] == 400
    assert creator_ids(membership_env) == ['a' * 12]


def test_creator_clear_needs_a_session_and_csrf(membership_env):
    creator_job(membership_env, 'a' * 12, status='error')
    assert request(membership_env, 'POST', '/api/creator-clear', {'scope': 'errors'})[0] == 401
    assert request(membership_env, 'POST', '/api/creator-clear', {'scope': 'errors'}, user='alice',
                   headers={'X-CSRF-Token': None})[0] == 403
    assert creator_ids(membership_env) == ['a' * 12]


@pytest.fixture
def showcase_env(membership_env, tmp_path, monkeypatch):
    monkeypatch.setattr(membership_env.panel, 'SHOWCASE_DIR', tmp_path / 'showcase')
    membership_env.gateway.showcase_callback = membership_env.panel.showcase_admin
    return membership_env


def test_showcase_admin_saves_name_and_picture_and_members_read_them(showcase_env):
    env = showcase_env
    assert json_request(env, 'GET', '/api/showcase', user='alice')[:2] == (200, {'items': {}})
    status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase',
                                   {'workflow_id': 'member-video', 'name': ' 让照片动起来 ', 'image': PNG_URL}, user='admin')
    assert status == 200, body
    card = body['items']['member-video']
    assert card['name'] == '让照片动起来' and card['image'].startswith('/api/showcase-image/') and card['image'].endswith('.png')
    assert json_request(env, 'GET', '/api/admin/membership/showcase', user='admin')[1] == body
    assert json_request(env, 'GET', '/api/showcase', user='bob')[1] == body

    status, raw, headers = request(env, 'GET', card['image'], user='alice')
    assert (status, raw) == (200, PNG) and dict(headers)['Content-Type'] == 'image/png'
    assert request(env, 'GET', card['image'])[0] == 401

    # Name only keeps the picture; remove_image drops it and deletes the unreferenced file.
    status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase',
                                   {'workflow_id': 'member-video', 'name': '新名字'}, user='admin')
    assert body['items']['member-video'] == {'name': '新名字', 'image': card['image']}
    status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase',
                                   {'workflow_id': 'member-video', 'remove_image': True}, user='admin')
    assert body['items']['member-video'] == {'name': '新名字', 'image': ''}
    assert request(env, 'GET', card['image'], user='alice')[0] == 404
    status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase/delete',
                                   {'workflow_id': 'member-video'}, user='admin')
    assert (status, body) == (200, {'items': {}})


def test_showcase_covers_creator_style_cards(showcase_env):
    """2026-11-12: a creator style is addressed as style.<style id>; unknown styles are refused."""
    env = showcase_env
    style = next(iter(env.panel.STYLE_PRESETS))
    status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase',
                                   {'workflow_id': 'style.' + style, 'name': '我的画风', 'image': PNG_URL}, user='admin')
    assert status == 200, body
    card = json_request(env, 'GET', '/api/showcase', user='alice')[1]['items']['style.' + style]
    assert card['name'] == '我的画风' and card['image'].endswith('.png')
    for bad in ('style.no-such-style', 'style.', 'style'):
        assert json_request(env, 'POST', '/api/admin/membership/showcase',
                            {'workflow_id': bad, 'name': 'x'}, user='admin')[0] == 400


def test_showcase_is_administrator_only_and_validated(showcase_env):
    env = showcase_env
    good = {'workflow_id': 'member-video', 'name': 'x'}
    assert json_request(env, 'POST', '/api/admin/membership/showcase', good, user='alice')[0] == 403
    assert json_request(env, 'GET', '/api/admin/membership/showcase', user='alice')[0] == 403
    assert request(env, 'POST', '/api/admin/membership/showcase', good)[0] == 401
    assert request(env, 'GET', '/api/showcase')[0] == 401
    for bad in ({'workflow_id': 'no-such-workflow', 'name': 'x'}, {'workflow_id': '../x', 'name': 'x'},
                {'workflow_id': 'member-video', 'name': 'x' * 41}, {'workflow_id': 'member-video', 'name': 5},
                {'workflow_id': 'member-video', 'image': 'data:image/png;base64,' + base64.b64encode(b'<svg/>').decode()},
                {'workflow_id': 'member-video', 'image': 'data:image/svg+xml;base64,AAAA'},
                {'workflow_id': 'member-video', 'image': 'https://example.com/a.png'},
                {'workflow_id': 'member-video', 'name': 'x', 'other': 1}):
        status, body, _ = json_request(env, 'POST', '/api/admin/membership/showcase', bad, user='admin')
        assert status == 400, (bad, body)
    assert json_request(env, 'GET', '/api/showcase', user='alice')[1] == {'items': {}}
    assert request(env, 'GET', '/api/showcase-image/' + '0' * 32 + '.png', user='alice')[0] == 404
    assert request(env, 'GET', '/api/showcase-image/..%2Fshowcase.json', user='alice')[0] == 404


def test_showcase_rejects_an_oversized_picture(showcase_env, monkeypatch):
    monkeypatch.setattr(showcase_env.panel, 'SHOWCASE_MAX_IMAGE_BYTES', 60)
    big = 'data:image/png;base64,' + base64.b64encode(PNG + b'\0' * 64).decode()
    status, body, _ = json_request(showcase_env, 'POST', '/api/admin/membership/showcase',
                                   {'workflow_id': 'member-video', 'image': big}, user='admin')
    assert status == 400 and '2MB' in body['error']
