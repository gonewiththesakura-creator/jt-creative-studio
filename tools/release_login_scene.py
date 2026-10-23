"""Publish immutable login assets and entry points without restarting live jobs."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import shlex
import urllib.error
import urllib.request

import prepare_dreamapi_native_canary as t

r = t.release
ORIGIN = 'https://studio.dreamapi.club'
STATE = t.BASE / 'audit/login-scene-release-20261009/release.json'
ENTRY = ('static/app-manifest.json', 'static/app.html')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_remote(sftp, path):
    try:
        with sftp.open(r.REMOTE_ROOT + '/' + path, 'rb') as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def public(path):
    request = urllib.request.Request(ORIGIN + path, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((t.BASE / ENTRY[0]).read_text(encoding='utf-8'))
    paths = sorted({url.lstrip('/') for url in manifest['assets']}) + list(ENTRY)
    assert all(re.fullmatch(r'static/assets/[A-Za-z0-9_-]+\.[0-9a-f]{12}\.(?:js|css|html|json|txt|webp)', path)
               or path in ENTRY for path in paths), 'Unexpected static resource path'
    data = {path: (t.BASE / path).read_bytes().replace(b'\r\n', b'\n')
            if path.endswith(('.js', '.css', '.html', '.json', '.txt'))
            else (t.BASE / path).read_bytes() for path in paths}
    client = t._connect(t.BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    sftp = client.open_sftp()
    tx = None
    locked = False
    state = {}
    swapped = False
    try:
        before = {path: read_remote(sftp, path) for path in paths}
        binary_repairs = []
        for path in paths:
            if path not in ENTRY and before[path] is not None:
                if (path.endswith('.webp') and before[path] != data[path]
                        and before[path] == data[path].replace(b'\r\n', b'\n')):
                    # The preceding text-oriented release normalized these binary
                    # previews. Restore only that exact, known byte transformation.
                    binary_repairs.append(path)
                else:
                    assert before[path] == data[path], 'Immutable asset differs: ' + path
        assert all(before[path] is not None for path in ENTRY), 'Missing production entry'
        changed = [path for path in paths if before[path] != data[path]]
        live_me = json.loads(public('/api/auth/me'))
        assert live_me.get('enabled') and not live_me.get('authenticated')
        assert json.loads(public('/api/live'))['service'] == 'comfy-panel'
        pid = r.command(client, 'systemctl show comfy-panel -p MainPID --value').strip()
        print(json.dumps({'changed_files': changed, 'membership_enabled': True,
                          'binary_preview_repairs': binary_repairs,
                          'restart_required': False}), flush=True)
        if not args.execute:
            return
        if STATE.exists():
            raise RuntimeError('Inspect existing release state before another publish')
        tx = r.new_release_transaction()
        r.acquire_release_lock(client, tx)
        locked = True
        state = {'transaction': tx, 'phase': 'preparing', 'process_id': pid,
                 'files': {path: digest(data[path]) for path in paths}}
        t._atomic_json(STATE, state)
        for path in changed:
            r.stage_file_resilient(client, sftp, t.BASE / path,
                                   r.REMOTE_ROOT + '/' + path, tx, data[path])
        backed_up = [*ENTRY, *binary_repairs]
        backup = r.backup_release(client, sftp, [r.REMOTE_ROOT + '/' + p for p in backed_up], tx)
        r.write_transaction_phase(client, tx, 'prepared')
        for path in backed_up:
            assert read_remote(sftp, path) == before[path], 'Concurrent entry change'
        r.write_transaction_phase(client, tx, 'swapping')
        # All hashed files are available before either entry point references them.
        for path in changed:
            remote = r.REMOTE_ROOT + '/' + path
            staged = r.transaction_file(tx, remote, 'stage')
            sftp.chmod(staged, 0o644)
            if path in backed_up:
                swapped = True
            sftp.posix_rename(staged, remote)
            r.fsync_remote_file(client, remote)
        def verify(path):
            assert public('/' if path == 'static/app.html' else '/' + path) == data[path], path
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(verify, paths))
        assert r.command(client, 'systemctl show comfy-panel -p MainPID --value').strip() == pid
        try:
            public('/api/jobs')
            raise AssertionError('Anonymous jobs unexpectedly accessible')
        except urllib.error.HTTPError as error:
            assert error.code == 401
        state.update(phase='committed', verified_assets=len(manifest['assets']),
                     process_unchanged=True, anonymous_jobs_denied=True)
        r.write_transaction_phase(client, tx, 'committed')
        t._atomic_json(STATE, state)
        print('LOGIN_SCENE_RELEASE_COMPLETE', flush=True)
    except BaseException:
        if swapped:
            # Restore existing files only. New immutable assets can safely remain.
            for path in backed_up:
                remote = r.REMOTE_ROOT + '/' + path
                r.command(client, 'cp -- ' + shlex.quote(r.transaction_file(tx, remote, 'backup'))
                          + ' ' + shlex.quote(remote + '.login-rollback'))
                sftp.chmod(remote + '.login-rollback', backup[remote]['mode'])
                sftp.posix_rename(remote + '.login-rollback', remote)
                r.fsync_remote_file(client, remote)
            r.write_transaction_phase(client, tx, 'rolled-back')
            state['phase'] = 'rolled-back'
            t._atomic_json(STATE, state)
        raise
    finally:
        if locked and (not swapped or state.get('phase') in ('committed', 'rolled-back')):
            r.release_release_lock(client, tx)
        sftp.close()
        client.close()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
