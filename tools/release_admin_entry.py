"""Publish only the admin-entry shell assets using the static release transaction."""
import http.client
import json
import re
import stat
import subprocess
import time
import urllib.error

import release_login_scene as release


def main():
    import retired_release
    retired_release.refuse_main(__file__)
    base = release.t.BASE
    entries = {path: subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=base)
               .replace(b'\r\n', b'\n') for path in release.ENTRY}
    previous = json.loads(entries['static/app-manifest.json'])
    candidate = json.loads((base / 'static/app-manifest.json').read_text(encoding='utf-8'))
    removed = set(previous['assets']) - set(candidate['assets'])
    added = set(candidate['assets']) - set(previous['assets'])
    replacements = {}
    for name, suffix in [('account', 'js'), ('membership-admin', 'js'), ('main', 'js'), ('app', 'css')]:
        pattern = re.compile(r'/static/assets/' + name + r'\.[0-9a-f]{12}\.' + suffix)
        old = [path for path in removed if pattern.fullmatch(path)]
        new = [path for path in added if pattern.fullmatch(path)]
        assert len(old) == len(new) == 1, 'Unexpected admin shell asset change: ' + name
        replacements[old[0]] = new[0]
    assert removed == set(replacements) and added == set(replacements.values())
    expected = dict(previous, main=replacements[previous['main']],
                    assets=sorted(replacements.get(path, path) for path in previous['assets']))
    assert candidate == expected, 'Business pages or unrelated assets changed'
    expected_html = entries['static/app.html']
    for old, new in replacements.items():
        expected_html = expected_html.replace(old.encode(), new.encode())
    assert (base / 'static/app.html').read_bytes().replace(b'\r\n', b'\n') == expected_html

    original_read = release.read_remote
    def checked_read(sftp, path):
        raw = original_read(sftp, path)
        if raw is not None:
            assert stat.S_ISREG(sftp.lstat(release.r.REMOTE_ROOT + '/' + path).st_mode)
        if path in entries:
            assert raw == entries[path], 'Production entrypoint drift: ' + path
        return raw

    original_public = release.public
    def retry_public(path):
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

    release.read_remote = checked_read
    release.public = retry_public
    release.STATE = base / 'audit/admin-entry-20261015/release.json'
    release.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
