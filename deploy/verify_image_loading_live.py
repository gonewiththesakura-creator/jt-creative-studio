"""Measure authenticated existing image previews without submitting work.

Run privately on the production host. Credentials stay in memory on that host;
only timings, byte counts and boundary checks are returned.
"""
import concurrent.futures
import http.cookiejar
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def request(self, origin, path, body=None, headers=None):
        request_headers = {'Cache-Control': 'no-cache'}
        if body is not None:
            request_headers.update({'Content-Type': 'application/json', 'Origin': origin})
            if self.csrf:
                request_headers['X-CSRF-Token'] = self.csrf
        request_headers.update(headers or {})
        request = urllib.request.Request(origin + path, headers=request_headers,
            data=None if body is None else json.dumps(body).encode())
        started = time.monotonic()
        try:
            response = self.opener.open(request, timeout=50)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(8 * 1024 * 1024)
            return response.code, raw, dict(response.headers), round(time.monotonic() - started, 3)


def main():
    assert os.geteuid() == 0
    identity = Path('/opt/jt-identity')
    origin = json.loads((identity / 'bootstrap-credentials.json').read_text())['public_origin']
    code = json.loads((identity / 'owner-access-code.json').read_text())['code']
    client, anonymous = Client(), Client()
    report = {'provider_generation_requests': 0, 'task_mutations': 0}
    try:
        assert client.request(origin, '/api/auth/code-login', {'code': code})[0] == 200
        status, raw, first_headers, _ = client.request(origin, '/api/auth/me')
        me = json.loads(raw)
        assert status == 200 and me['authenticated']
        client.csrf = me['csrf_token']
        again = client.request(origin, '/api/auth/me')
        assert first_headers.get('Clear-Site-Data') == '"cache"'
        assert 'Clear-Site-Data' not in again[2]
        report['cache_migration_once_per_session'] = True

        # Only inspect metadata for an existing completed image task. Never
        # print job contents, source URLs, prompts, filenames or credentials.
        ledger = json.loads(Path('/home/admin/comfy-panel/panel_data/jobs.json').read_text())
        candidates = sorted((j for j in ledger.values() if j.get('status') in ('done', 'completed')
                             and j.get('style_id') != 'video' and len(j.get('images') or []) >= 4),
                            key=lambda j: j.get('created', 0), reverse=True)
        selected = None
        for row in candidates[:6]:
            status, raw, _, _ = client.request(origin, '/api/job/' + row['id'])
            if status != 200:
                continue
            public = json.loads(raw)
            images = [im for im in public.get('images', []) if im.get('thumb_url')]
            if len(images) >= 4:
                selected = images[:4]
                break
        assert selected, 'No owned four-image task found for read-only verification'

        def measure(image, variant):
            path = image['thumb_url' if variant == 'thumb' else 'preview_url']
            status, raw, headers, seconds = client.request(origin, path)
            assert status == 200, 'Preview endpoint failed: ' + str(status)
            assert 'no-store' in headers.get('Cache-Control', '') and 'Cookie' in headers.get('Vary', '')
            with Image.open(io.BytesIO(raw)) as preview:
                width, height = preview.size
                assert preview.format == 'JPEG' and max(width, height) <= (256 if variant == 'thumb' else 1536)
            return {'bytes': len(raw), 'seconds': seconds, 'width': width, 'height': height}

        report['first_thumbnail_requests'] = [measure(im, 'thumb') for im in selected]
        report['selected_preview'] = measure(selected[0], 'view')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            report['four_cached_thumbnails'] = list(pool.map(lambda im: measure(im, 'thumb'), selected))
        report['anonymous_preview_denied'] = anonymous.request(origin, selected[0]['thumb_url'])[0] == 401
        assert report['anonymous_preview_denied']
        # A 32-byte Range read confirms the unchanged original download size.
        status, _, headers, _ = client.request(origin, selected[0]['url'], headers={'Range': 'bytes=0-31'})
        match = re.fullmatch(r'bytes 0-31/(\d+)', headers.get('Content-Range', ''))
        assert status == 206 and match, 'Original range download unavailable'
        report['original_bytes'] = int(match.group(1))
        report['thumbnail_reduction_percent'] = round(100 * (1 - report['first_thumbnail_requests'][0]['bytes'] / report['original_bytes']), 2)
        report['original_download_preserved'] = True
    finally:
        if client.csrf:
            client.request(origin, '/api/auth/logout', {})
    print(json.dumps(report))


if __name__ == '__main__':
    main()
