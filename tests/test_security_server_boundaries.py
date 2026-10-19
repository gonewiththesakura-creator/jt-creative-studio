"""Adversarial regressions: local fixtures only, no paid/provider traffic."""
import copy
import http.server
import io
import json
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

import membership_media as media
from test_membership_http import membership_env, put_job, request
from test_server_review_regressions import panel


@pytest.mark.parametrize('action,index,expected', [('top', 4, [4, 1, 0, 3, 2]),
    ('up', 4, [0, 1, 4, 3, 2]), ('down', 0, [2, 1, 0, 3, 4])])
@pytest.mark.parametrize('tied_order', [False, True])
def test_reorder_cannot_move_another_owner_or_change_their_revision(membership_env, action, index, expected, tied_order):
    env = membership_env
    rows = [put_job(env, 'alice' if i % 2 == 0 else 'bob', format(i, '012x'), status='queued',
                    queue_order=0 if tied_order else i, created=100 + i) for i in range(5)]
    foreign = [copy.deepcopy(rows[i]) for i in (1, 3)]
    env.panel.edit_video_queue(env.users['alice']['owner_key'], {
        'job_id': rows[index]['id'], 'revision': 0, 'action': action})
    assert [row['id'] for row in env.panel._video_waiting()] == [rows[i]['id'] for i in expected]
    assert [rows[i] for i in (1, 3)] == foreign
    env.panel.load_jobs()
    assert [row['id'] for row in env.panel._video_waiting()] == [rows[i]['id'] for i in expected]


def test_reorder_failed_save_restores_all_slots(membership_env, monkeypatch):
    env = membership_env
    for i in range(3):
        put_job(env, 'alice' if i != 1 else 'bob', format(i, '012x'), status='queued', queue_order=i)
    previous = copy.deepcopy(env.panel._jobs)
    def fail():
        raise OSError('offline disk fixture')
    monkeypatch.setattr(env.panel, 'save_jobs', fail)
    with pytest.raises(OSError):
        env.panel.edit_video_queue(env.users['alice']['owner_key'], {'job_id': format(2, '012x'), 'revision': 0, 'action': 'top'})
    assert env.panel._jobs == previous


def test_private_favorite_cache_cannot_survive_account_change(membership_env):
    env = membership_env
    origin = 'http://127.0.0.1:' + str(env.httpd.server_port)
    env.gateway.origin, env.gateway.COOKIE = origin, 'offline_security_session'
    fid, value = 'f' * 12, b'private-alice-favorite-offline-fixture'
    fixture = env.panel.FAVORITES_DIR / (fid + '.png')
    fixture.write_bytes(value)
    env.panel._favorites[fid] = {'id': fid, 'image_path': str(fixture), 'favorite_media_type': 'image/png',
        'owner_session_hash': env.panel._session_hash(env.users['alice']['owner_key'])}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        def account(name):
            context.clear_cookies()
            context.add_cookies([{'name': env.gateway.COOKIE, 'value': env.sessions[name]['token'], 'url': origin}])
        def fetch():
            return page.evaluate('''async path=>{const r=await fetch(path); return {status:r.status,body:await r.text(),cache:r.headers.get('cache-control'),vary:r.headers.get('vary')}}''', '/api/favorite-image/' + fid)
        try:
            account('alice')
            page.goto(origin + '/api/auth/me')
            first = fetch()
            assert first['status'] == 200 and first['body'] == value.decode()
            assert first['cache'] == 'private, no-store' and first['vary'] == 'Cookie'
            env.store.revoke_session(env.sessions['alice']['token'])
            account('bob')
            second = fetch()
            assert second['status'] == 404 and second['body'] != value.decode()
        finally:
            context.close()
            browser.close()


def test_member_static_routes_publish_only_manifest_assets(membership_env):
    env = membership_env
    manifest = json.loads((env.panel.BASE / 'static/app-manifest.json').read_text(encoding='utf-8'))
    for path in ['/', '/video', '/realism', '/static/app.html', '/static/app-manifest.json',
                 '/static/favicon.png', *manifest['assets']]:
        assert request(env, 'GET', path)[0] == 200, path
    for path in ['/static/video.html', '/static/index.html', '/static/realism.html', '/promptgen',
                 '/static/singularity/workbench.js', '/static/assets/video.000000000000.js',
                 '/static/../server.py', '/static/assets/../../server.py']:
        assert request(env, 'GET', path)[0] == 404, path


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_provider_redirect_cannot_forward_header_or_body_credentials(panel, status):
    seen = []
    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(('target', self.headers.get('Authorization')))
            self.send_response(200); self.end_headers()
        do_POST = do_GET
        def log_message(self, *args): pass
    target = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Target)
    class Source(Target):
        def do_POST(self):
            seen.append(('source', self.headers.get('Authorization')))
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(status)
            self.send_header('Location', f'http://127.0.0.1:{target.server_port}/stolen')
            self.end_headers()
    source = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Source)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (source, target)]
    for thread in threads: thread.start()
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{source.server_port}/api', data=b'{"apiKey":"offline-body-sentinel"}',
                                     headers={'Authorization': 'Bearer offline-header-sentinel'})
        with pytest.raises(urllib.error.HTTPError) as failure:
            panel._urlopen_bounded(req, None, 2)
        assert failure.value.code == status
        assert seen == [('source', 'Bearer offline-header-sentinel')]
    finally:
        for server in (source, target): server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=2)


def test_one_owner_cannot_exhaust_global_media_capacity():
    server = SimpleNamespace(_large_response_slots=threading.BoundedSemaphore(4), _media_owner_slots=media.MediaOwnerSlots(2))
    handler = lambda user: SimpleNamespace(server=server, path='/api/result-media/a/0', _membership_session={'user': {'id': user}})
    alice, bob = handler('alice'), handler('bob')
    leases = [media.acquire_media_slot(alice), media.acquire_media_slot(alice)]
    assert all(leases) and media.acquire_media_slot(alice) is None
    leases.extend([media.acquire_media_slot(bob), media.acquire_media_slot(bob)])
    assert all(leases) and media.acquire_media_slot(bob) is None
    for lease in leases: media.release_media_slot(lease)
    assert server._media_owner_slots._active == {}
    for _ in range(4): assert server._large_response_slots.acquire(False)


def test_account_media_limit_is_enforced_by_real_http_and_releases_on_completion(membership_env):
    env = membership_env
    value = b'media-fixture-' * 24000
    for name, fid in [('alice', 'a' * 12), ('bob', 'b' * 12)]:
        target = env.panel.FAVORITES_DIR / (fid + '.mp4')
        target.write_bytes(value)
        env.panel._favorites[fid] = {'id': fid, 'image_path': str(target), 'favorite_media_type': 'video/mp4',
            'owner_session_hash': env.panel._session_hash(env.users[name]['owner_key'])}
    handler = SimpleNamespace(server=env.httpd, path='/api/favorite-image/' + 'a' * 12,
                              _membership_session={'user': env.users['alice']})
    leases = [media.acquire_media_slot(handler), media.acquire_media_slot(handler)]
    try:
        assert all(leases)
        assert request(env, 'GET', '/api/favorite-image/' + 'a' * 12, user='alice')[0] == 503
        status, raw, headers = request(env, 'GET', '/api/favorite-image/' + 'b' * 12, user='bob')
        assert status == 200 and raw == value
        assert env.users['bob']['id'] not in env.httpd._media_owner_slots._active
        # 4aa41f6: private video replay may be cached by the owner's browser; logout sends Clear-Site-Data.
        assert dict(headers)['Cache-Control'] == 'private, max-age=3600'
        assert dict(headers)['Vary'] == 'Cookie'
    finally:
        for lease in leases: media.release_media_slot(lease)
    assert request(env, 'GET', '/api/favorite-image/' + 'a' * 12, user='alice')[0] == 200
    assert env.httpd._media_owner_slots._active == {}


class DownloadResponse(io.BytesIO):
    status = 200
    def __init__(self, value, *, length=None, content_type='video/mp4'):
        super().__init__(value)
        self.headers = {'Content-Type': content_type, 'Content-Length': str(len(value)) if length is None else length}
    def getheader(self, name, default=None): return self.headers.get(name, default)


@pytest.mark.parametrize('failure', ['declared-too-large', 'actual-too-large', 'truncated', 'html', 'signature'])
def test_archive_download_rejects_bad_content_and_preserves_original(tmp_path, monkeypatch, failure):
    old = tmp_path / 'archive.mp4'; old.write_bytes(b'original-file')
    response = DownloadResponse(b'\x00\x00\x00\x18ftypmp42fixture', length='999' if failure == 'declared-too-large' else
                                '' if failure == 'actual-too-large' else '40' if failure == 'truncated' else None,
                                content_type='text/html' if failure == 'html' else 'video/mp4')
    closed = []
    connection = SimpleNamespace(sock=None, close=lambda: closed.append(True))
    monkeypatch.setattr(media, 'open_media', lambda *a, **kw: (connection, response))
    with pytest.raises(ValueError):
        media.download_media('https://fixture.invalid/media', old, max_bytes=10 if 'too-large' in failure else 100,
                             validator=lambda *a: failure != 'signature')
    assert old.read_bytes() == b'original-file' and closed
    assert list(tmp_path.iterdir()) == [old]


def test_archive_download_validates_each_redirect_and_pins_public_address(monkeypatch):
    connected, requested = [], []
    addresses = {'cdn.example': '8.8.8.8', 'private.example': '127.0.0.1'}
    monkeypatch.setattr(media.socket, 'getaddrinfo', lambda host, *a, **kw: [(2,1,6,'',(addresses[host],443))])
    monkeypatch.setattr(media.socket, 'create_connection', lambda address, *a: connected.append(address))
    class Connection:
        def __init__(self, host, *args, **kwargs): self.host = host
        def request(self, method, path, headers):
            self._create_connection((self.host, 443))
            requested.append((self.host, path, headers))
        def getresponse(self): return SimpleNamespace(status=302, getheader=lambda *a: 'https://private.example/secret', close=lambda: None)
        def close(self): pass
    monkeypatch.setattr(media.http.client, 'HTTPSConnection', Connection)
    with pytest.raises(ValueError, match='non-public'):
        media.open_media('https://cdn.example/media')
    assert connected == [('8.8.8.8', 443)]
    assert len(requested) == 1 and not {'Authorization', 'Cookie'} & requested[0][2].keys()


def test_archive_dns_deadline_returns_without_late_file_write(tmp_path, monkeypatch):
    def delayed(*args):
        time.sleep(.2)
        return None, '8.8.8.8'
    monkeypatch.setattr(media, 'public_endpoint', delayed)
    target = tmp_path / 'media.mp4'
    started = time.monotonic()
    with pytest.raises(TimeoutError): media.download_media('https://fixture.invalid/a', target, timeout=.03)
    assert time.monotonic() - started < .15
    time.sleep(.25)
    assert not target.exists() and not list(tmp_path.iterdir())
