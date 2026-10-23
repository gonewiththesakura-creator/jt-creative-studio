"""Image previews: real HTTP account boundary plus offline download fixtures."""
import concurrent.futures
import io
import os
import threading
import time
from types import SimpleNamespace

from PIL import Image
import pytest

import membership_media
import result_image_cache as cache_module
from result_image_cache import ResultImageCache, PreviewError
from test_membership_http import membership_env, put_job, request, json_request, wait_for_http_idle
from test_server_review_regressions import panel


def png(size=(1800, 1200), color=(30, 90, 180)):
    data = io.BytesIO()
    with Image.new('RGB', size, color) as image:
        image.save(data, 'PNG')
    return data.getvalue()


def test_two_sizes_share_one_source_and_disk_cache_is_reusable(tmp_path):
    cache = ResultImageCache(tmp_path / 'previews')
    calls = []
    def download(limit):
        calls.append(limit)
        return png()
    result = cache.get_or_create('alice', 'job', 0, 'https://cdn.example/one.png', download)
    assert calls == [cache_module.MAX_SOURCE_BYTES]
    for name, edge in [('thumb', 256), ('view', 1536)]:
        with Image.open(io.BytesIO(result[name])) as image:
            assert image.format == 'JPEG' and max(image.size) == edge
            assert abs(image.width * 2 - image.height * 3) <= 2
        assert cache.lookup('alice', 'job', 0, 'https://cdn.example/one.png', name) == result[name]
    restarted = ResultImageCache(cache.root)
    assert restarted.get_or_create('alice', 'job', 0, 'https://cdn.example/one.png', lambda _: pytest.fail('cached')) == result
    assert cache.lookup('bob', 'job', 0, 'https://cdn.example/one.png', 'thumb') is None
    assert cache.lookup('alice', 'job', 0, 'https://cdn.example/two.png', 'thumb') is None
    assert len(list(cache.root.iterdir())) == 2


def test_simultaneous_sizes_coalesce_and_release_key_state(tmp_path):
    cache = ResultImageCache(tmp_path)
    began, release = threading.Event(), threading.Event()
    calls = []
    def download(limit):
        calls.append(limit)
        began.set()
        assert release.wait(3)
        return png((90, 60))
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        first = pool.submit(cache.get_or_create, 'alice', 'job', 0, 'https://cdn.example/one.png', download)
        assert began.wait(2)
        following = [pool.submit(cache.get_or_create, 'alice', 'job', 0, 'https://cdn.example/one.png', download) for _ in range(7)]
        release.set()
        expected = first.result()
        assert all(f.result() == expected for f in following)
    assert len(calls) == 1 and cache._keys == {}


@pytest.mark.parametrize('source', [b'<html>not an image</html>', b'', b'\x89PNG\r\n\x1a\ntruncated'])
def test_invalid_sources_do_not_publish_or_leave_locks(tmp_path, source):
    cache = ResultImageCache(tmp_path)
    with pytest.raises(PreviewError):
        cache.get_or_create('alice', 'job', 0, 'https://cdn.example/bad.png', lambda _: source)
    assert list(tmp_path.iterdir()) == [] and cache._keys == {}


def test_pixel_limit_and_pillow_bomb_fail_before_publication(tmp_path, monkeypatch):
    cache = ResultImageCache(tmp_path)
    source = png((40, 40))
    monkeypatch.setattr(cache_module, 'MAX_SOURCE_PIXELS', 100)
    with pytest.raises(PreviewError, match='dimensions'):
        cache.get_or_create('alice', 'job', 0, 'https://cdn.example/huge.png', lambda _: source)
    monkeypatch.setattr(cache_module, 'MAX_SOURCE_PIXELS', 10000)
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)
    with pytest.raises(PreviewError):
        cache.get_or_create('alice', 'job', 0, 'https://cdn.example/bomb.png', lambda _: source)
    assert not list(tmp_path.iterdir()) and cache._keys == {}


def test_ttl_and_disk_budget_cleanup_does_not_remove_original_material(tmp_path):
    cache = ResultImageCache(tmp_path / 'cache', ttl=20, max_bytes=1000, max_files=2)
    original = tmp_path / 'original.png'; original.write_bytes(png((3, 3)))
    unmanaged = cache.root / 'source-interrupted.png'; unmanaged.write_bytes(b'not-cache')
    files = []
    for index in range(4):
        path = cache.root / (str(index) + '.thumb.jpg')
        path.write_bytes(b'x' * 400)
        os.utime(path, (100 + index, 100 + index))
        files.append(path)
    cache.cleanup(now=110)
    assert [file.exists() for file in files] == [False, False, True, True]
    cache.cleanup(now=130)
    assert not list(cache.root.glob('*.jpg'))
    assert original.exists() and unmanaged.read_bytes() == b'not-cache'


@pytest.fixture
def image_env(membership_env, tmp_path, monkeypatch):
    env = membership_env
    env.downloads = []
    cache = ResultImageCache(tmp_path / 'result-cache')
    monkeypatch.setattr(env.panel, '_result_image_cache', cache)
    def download(url, destination, **kwargs):
        env.downloads.append((url, kwargs))
        destination.write_bytes(png())
    monkeypatch.setattr(env.panel, 'download_media', download)
    env.source = {'remote': True, 'url': 'https://cdn.example/private.png', 'file': 'result.png', 'file_type': 'png'}
    env.job = put_job(env, images=[dict(env.source)], style_id='draw', workflow='draw')
    return env


def test_http_projection_cache_hit_ownership_revocation_and_original_download(image_env):
    env = image_env
    status, details, _ = json_request(env, 'GET', '/api/job/' + env.job['id'], user='alice')
    image = details['images'][0]
    assert status == 200 and image['url'] == '/api/result-media/' + env.job['id'] + '/0'
    assert image['thumb_url'].endswith('/0?size=thumb') and image['preview_url'].endswith('/0?size=view')
    assert 'cdn.example' not in str(details)
    for path, edge in [(image['thumb_url'], 256), (image['preview_url'], 1536)]:
        for _ in range(2):
            status, body, headers = request(env, 'GET', path, user='alice')
            assert status == 200 and dict(headers)['Cache-Control'] == 'private, no-store'
            assert dict(headers)['Vary'] == 'Cookie'
            with Image.open(io.BytesIO(body)) as decoded:
                assert max(decoded.size) == edge
        assert request(env, 'GET', path, user='bob')[0] == 404
        assert request(env, 'GET', path)[0] == 401
    assert len(env.downloads) == 1
    assert env.downloads[0][1] == {'timeout': 25, 'max_bytes': cache_module.MAX_SOURCE_BYTES}
    assert len(list(env.panel._result_image_cache.root.iterdir())) == 2
    assert request(env, 'GET', image['url'], user='alice')[1] == b'private-output-bytes'
    assert env.media_calls == [(env.source['url'], env.source['file'])]
    env.store.revoke_session(env.sessions['alice']['token'])
    assert request(env, 'GET', image['thumb_url'], user='alice')[0] == 401
    assert len(env.downloads) == 1


@pytest.mark.parametrize('query', ['?size=bad', '?size=', '?size=thumb&size=view', '?url=https://bad.example/'])
def test_untrusted_preview_query_cannot_control_url_or_geometry(image_env, query):
    env = image_env
    assert request(env, 'GET', '/api/rh-preview/' + env.job['id'] + '/0' + query, user='alice')[0] == 400
    assert not env.downloads


def test_source_url_change_does_not_reuse_old_pixels_and_video_projection_is_unchanged(image_env):
    env = image_env
    path = '/api/rh-preview/' + env.job['id'] + '/0?size=thumb'
    assert request(env, 'GET', path, user='alice')[0] == 200
    env.job['images'][0]['url'] = 'https://cdn.example/replaced.png'
    assert request(env, 'GET', path, user='alice')[0] == 200
    assert len(env.downloads) == 2
    env.job['images'] = [{'remote': True, 'url': 'https://cdn.example/video.mp4', 'file': 'video.mp4', 'file_type': 'video/mp4'}]
    projected = env.panel.public_job_images(env.job)[0]
    assert projected['preview_url'] == projected['url'] and 'thumb_url' not in projected
    assert request(env, 'GET', path, user='alice')[0] == 404


def test_cache_miss_respects_media_owner_slots_and_frees_them_on_failure(image_env, monkeypatch):
    env = image_env
    path = '/api/rh-preview/' + env.job['id'] + '/0?size=thumb'
    handler = SimpleNamespace(server=env.httpd, path=path, _membership_session={'user': env.users['alice']})
    leases = [membership_media.acquire_media_slot(handler), membership_media.acquire_media_slot(handler)]
    try:
        status, _, headers = request(env, 'GET', path, user='alice')
        assert status == 503 and dict(headers)['Retry-After'] == '2' and not env.downloads
    finally:
        for lease in leases:
            membership_media.release_media_slot(lease)
    monkeypatch.setattr(env.panel, 'download_media', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('offline timeout')))
    assert request(env, 'GET', path, user='alice')[0] == 502
    wait_for_http_idle(env)
    assert not env.httpd._media_owner_slots._active
    assert list(env.panel._result_image_cache.root.iterdir()) == []
    assert all(env.httpd._large_response_slots.acquire(False) for _ in range(4))


def test_small_cache_hit_still_loads_when_owner_streams_are_busy(image_env):
    env = image_env
    path = '/api/rh-preview/' + env.job['id'] + '/0?size=thumb'
    assert request(env, 'GET', path, user='alice')[0] == 200
    wait_for_http_idle(env)
    handler = SimpleNamespace(server=env.httpd, path=path, _membership_session={'user': env.users['alice']})
    leases = [membership_media.acquire_media_slot(handler), membership_media.acquire_media_slot(handler)]
    try:
        status, body, _ = request(env, 'GET', path, user='alice')
        assert status == 200 and len(body) < env.panel.LARGE_RESPONSE_THRESHOLD
        assert request(env, 'GET', path, user='bob')[0] == 404
        assert len(env.downloads) == 1
    finally:
        for lease in leases:
            membership_media.release_media_slot(lease)


def test_large_view_reuses_miss_lease_and_cache_hits_remain_capacity_limited(image_env, monkeypatch):
    env = image_env
    source = io.BytesIO()
    with Image.effect_noise((1800, 1500), 80).convert('RGB') as noisy:
        noisy.save(source, 'PNG')
    def download(url, destination, **kwargs):
        destination.write_bytes(source.getvalue())
    monkeypatch.setattr(env.panel, 'download_media', download)
    path = '/api/rh-preview/' + env.job['id'] + '/0?size=view'
    handler = SimpleNamespace(server=env.httpd, path=path, _membership_session={'user': env.users['alice']})
    first = membership_media.acquire_media_slot(handler)
    second = None
    try:
        status, body, _ = request(env, 'GET', path, user='alice')
        assert status == 200 and len(body) >= env.panel.LARGE_RESPONSE_THRESHOLD
        wait_for_http_idle(env)
        assert env.httpd._media_owner_slots._active[env.users['alice']['id']] == 1
        second = membership_media.acquire_media_slot(handler)
        assert second
        assert request(env, 'GET', path, user='alice')[0] == 503
        assert request(env, 'GET', path.replace('size=view', 'size=thumb'), user='alice')[0] == 200
    finally:
        if second:
            membership_media.release_media_slot(second)
        membership_media.release_media_slot(first)


def test_parallel_thumb_and_view_http_download_source_once(image_env, monkeypatch):
    env = image_env
    entered, resume = threading.Event(), threading.Event()
    def slow(url, path, **kwargs):
        env.downloads.append((url, kwargs))
        entered.set()
        assert resume.wait(4)
        path.write_bytes(png())
    monkeypatch.setattr(env.panel, 'download_media', slow)
    path = '/api/rh-preview/' + env.job['id'] + '/0'
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        thumb = pool.submit(request, env, 'GET', path + '?size=thumb', user='alice')
        assert entered.wait(2)
        view = pool.submit(request, env, 'GET', path + '?size=view', user='alice')
        resume.set()
        assert thumb.result()[0] == view.result()[0] == 200
    wait_for_http_idle(env)
    assert len(env.downloads) == 1 and not env.httpd._media_owner_slots._active
