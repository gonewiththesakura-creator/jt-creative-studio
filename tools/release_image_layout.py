"""Publish the creator image-fit CSS using the existing static transaction.

Only one stylesheet and its two entrypoint references may change. No restart,
queue draining, data upload, or provider request is performed.
"""
import copy
import http.client
import json
import stat
import subprocess
import time
import urllib.error

import release_login_scene as static_release


def main():
    base = static_release.t.BASE

    def baseline(path):
        return subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=base).replace(b'\r\n', b'\n')

    entries = {path: baseline(path) for path in static_release.ENTRY}
    previous = json.loads(entries['static/app-manifest.json'])
    candidate = json.loads((base / 'static/app-manifest.json').read_text(encoding='utf-8'))
    old_css = previous['pages']['/']['css']
    new_css = candidate['pages']['/']['css']
    assert new_css != old_css and new_css.endswith('.css'), 'Expected one creator CSS change'
    expected = copy.deepcopy(previous)
    expected['pages']['/']['css'] = new_css
    expected['assets'] = sorted(new_css if item == old_css else item for item in expected['assets'])
    assert candidate == expected, 'This release must not change scripts or other pages'
    assert (base / 'static/app.html').read_bytes().replace(b'\r\n', b'\n') == entries['static/app.html'].replace(
        old_css.encode(), new_css.encode()), 'Unexpected shell change'

    # Retain the proven locking, backup, atomic swap, public byte verification,
    # rollback, and unchanged-process checks of the existing static publisher.
    original_read = static_release.read_remote

    def checked_read(sftp, path):
        raw = original_read(sftp, path)
        if raw is not None:
            metadata = sftp.lstat(static_release.r.REMOTE_ROOT + '/' + path)
            assert stat.S_ISREG(metadata.st_mode), 'Non-regular release target: ' + path
        if path in entries:
            assert raw == entries[path], 'Production entrypoint drift: ' + path
        return raw

    original_public = static_release.public

    def retry_public(path):
        # Static GET retries cannot submit work. Keep exact byte verification;
        # a transient connection timeout must never become a skipped check.
        for attempt in range(3):
            try:
                return original_public(path)
            except urllib.error.HTTPError as error:
                if error.code not in (502, 503, 504) or attempt == 2:
                    raise
            except (OSError, http.client.HTTPException):
                if attempt == 2:
                    raise
            time.sleep(attempt + 1)

    static_release.read_remote = checked_read
    static_release.public = retry_public
    static_release.STATE = base / 'audit/image-layout-20261013/release-retry1.json'
    static_release.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
