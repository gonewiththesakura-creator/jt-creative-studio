"""Publish image-loading changes without changing host security or user data.

Default preflight is read-only. --execute uses the existing release lock and
drain contract, waits for active work without cancelling queued tasks, and
backs up production data on the server. Rollback restores code only; it never
replaces a live task ledger or membership database.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
import shlex
import stat
import subprocess
import time
import urllib.error
import urllib.request

import prepare_dreamapi_native_canary as t
from release_membership_cutover import queue, remote_json

r = t.release
ORIGIN = 'https://studio.dreamapi.club'
STATE = t.BASE / 'audit/image-loading-20261012/release.json'
DATA = r.REMOTE_ROOT + '/panel_data'
MODULES = list(r.SERVER_RUNTIME_MODULE_PATHS)


def new_module(path):
    """A runtime module absent from the git baseline is new in this candidate, not production drift."""
    return path in MODULES and subprocess.run(['git', 'show', 'HEAD:' + path], cwd=t.BASE,
                                              capture_output=True).returncode != 0


def fetch(path):
    try:
        request = urllib.request.Request(ORIGIN + path, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((t.BASE / 'static/app-manifest.json').read_text(encoding='utf-8'))
    assets = [p.removeprefix('/') for p in manifest['assets']]
    assert assets and len(set(assets)) == len(assets), 'Invalid asset manifest'
    assert all(re.fullmatch(
        r'static/assets/[A-Za-z0-9_-]+\.[0-9a-f]{12}\.(?:js|css|html|json|txt|webp)', p
    ) for p in assets), 'Unexpected asset path'
    paths = r.require_server_runtime_modules([*assets, *MODULES, 'static/app-manifest.json', 'static/app.html'])
    normalize = lambda p, raw: raw if p.endswith('.webp') else raw.replace(b'\r\n', b'\n')
    data = {p: normalize(p, (t.BASE / p).read_bytes()) for p in paths}
    if args.execute:
        assert not STATE.exists(), 'Inspect existing release state before retry'
        r.run_feature_release_gate(data, normalize)
    client = t._connect(t.BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    sftp = client.open_sftp()

    def read(path):
        remote = r.REMOTE_ROOT + '/' + path
        try:
            metadata = sftp.lstat(remote)
        except FileNotFoundError:
            return None
        assert stat.S_ISREG(metadata.st_mode), 'Release target is not a regular file: ' + path
        with sftp.open(remote, 'rb') as handle:
            return handle.read()

    def phase(name):
        state['phase'] = name
        r.write_transaction_phase(client, tx, name)
        t._atomic_json(STATE, state)

    tx = None
    locked = admission = isolated = stopped = swapped = False
    state = {}
    try:
        before = {p: read(p) for p in paths}
        for p in paths:
            if before[p] is None:
                assert p in assets or new_module(p), 'Missing existing release file: ' + p
            elif before[p] != data[p]:
                baseline = subprocess.run(['git', 'show', 'HEAD:' + p], cwd=t.BASE, capture_output=True)
                baseline_raw = baseline.stdout if p.endswith('.webp') else baseline.stdout.replace(b'\r\n', b'\n')
                assert baseline.returncode == 0 and before[p] == baseline_raw, 'Production drift: ' + p
        changed = [p for p in paths if before[p] != data[p]]
        assert fetch('/api/jobs')[0] == 401
        r.require_release_start_draining_unset(client)
        print(json.dumps({'phase': 'preflight', 'changed_count': len(changed), 'queue': queue(client)}), flush=True)
        if not args.execute:
            return
        if not changed:
            print('IMAGE_LOADING_RELEASE_UNCHANGED', flush=True)
            return

        tx = r.new_release_transaction()
        r.acquire_release_lock(client, tx)
        locked = True
        state = {'phase': 'preparing', 'transaction': tx, 'watchdog': r.capture_watchdog_state(client),
                 'files': {p: hashlib.sha256(raw).hexdigest() for p, raw in data.items()}}
        t._atomic_json(STATE, state)
        for p in changed:
            r.stage_file_resilient(client, sftp, t.BASE / p, r.REMOTE_ROOT + '/' + p, tx, data[p])
        backup = r.backup_release(client, sftp, [r.REMOTE_ROOT + '/' + p for p in changed], tx)
        phase('prepared')
        admission = True
        r.set_release_start_draining(client, True)
        busy = r.set_remote_release_drain(client, True)
        deadline = time.monotonic() + 900
        while queue(client)['active'] or any(busy[k] for k in ('cloud_busy', 'local_busy', 'api_busy')):
            if time.monotonic() >= deadline:
                raise RuntimeError('Existing work still active; no tasks cancelled')
            print('Waiting for active tasks to finish naturally; queued tasks are preserved', flush=True)
            time.sleep(15)
            busy = r.set_remote_release_drain(client, True)
        isolated = True
        r.isolate_watchdog(client)
        stopped = True
        r.stop_panel_resilient(client)
        state['backup'] = remote_json(client, f'''import sqlite3,pathlib,json,shutil,os
root=pathlib.Path({DATA!r});target=pathlib.Path({tx['root']!r})
src=sqlite3.connect('file:'+str(root/'membership.sqlite3')+'?mode=ro',uri=True)
dst=sqlite3.connect(str(target/'membership-before.sqlite3'))
src.backup(dst);dst.close();src.close();os.chmod(target/'membership-before.sqlite3',0o600)
for name in ('jobs.json','favorites.json','upload_capabilities.json'):
 if (root/name).exists():
  shutil.copy2(root/name,target/('before-'+name));os.chmod(target/('before-'+name),0o600)
print(json.dumps({{'server_local_backup':True}}))
''', root=True)
        for p in changed:
            assert read(p) == before[p], 'Concurrent modification: ' + p
        phase('swapping')
        swapped = True
        # Publish hashed assets and modules before the manifest/HTML entrypoints.
        # Files are owned by the deploy account and readable by jt-panel (0644).
        for p in changed:
            remote = r.REMOTE_ROOT + '/' + p
            staged = r.transaction_file(tx, remote, 'stage')
            sftp.chmod(staged, 0o644)
            sftp.posix_rename(staged, remote)
            r.fsync_remote_file(client, remote)
        r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
        r.wait_for_loopback_live(client)
        r.set_remote_release_drain(client, True, require_start_draining=True)
        status, raw, _ = fetch('/api/auth/me')
        me = json.loads(raw)
        assert status == 200 and me.get('login_method') == 'access_code' and not me.get('authenticated')
        assert fetch('/api/jobs')[0] == 401 and fetch('/api/admin/release-drain')[0] == 404
        assert fetch('/static/video.html')[0] == 404 and fetch('/static/index.html')[0] == 404

        def verify_asset(p):
            code, raw, _ = fetch('/' if p == 'static/app.html' else '/' + p)
            assert code == 200 and raw == data[p], 'Public asset mismatch: ' + p

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(verify_asset, assets + ['static/app.html', 'static/app-manifest.json']))
        for p in MODULES:
            assert read(p) == data[p], 'Runtime module mismatch: ' + p
        state['data_verification'] = remote_json(client, f'''import pathlib,json,sqlite3
root=pathlib.Path({DATA!r});backup=pathlib.Path({tx['root']!r})
before=json.loads((backup/'before-jobs.json').read_text());after=json.loads((root/'jobs.json').read_text())
assert before==after,'Job ledger changed during release'
for name in ('favorites.json','upload_capabilities.json'):
 if (backup/('before-'+name)).exists():
  assert (backup/('before-'+name)).read_bytes()==(root/name).read_bytes(),name
db=sqlite3.connect('file:'+str(root/'membership.sqlite3')+'?mode=ro',uri=True)
old=sqlite3.connect('file:'+str(backup/'membership-before.sqlite3')+'?mode=ro',uri=True)
for table in ('users','plans','entitlements','activation_codes','reservations','login_credentials'):
 assert db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()==old.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall(),table
db.close();old.close()
print(json.dumps({{'jobs_preserved':len(after),'favorites_preserved':len(json.loads((root/'favorites.json').read_text())),
 'accounts_and_plans_preserved':True}}))
''', root=True)
        phase('committed')
        print('IMAGE_LOADING_RELEASE_COMPLETE', flush=True)
    except BaseException:
        if swapped:
            try:
                phase('rolling-back')
                r.stop_panel_resilient(client)
                for p in changed:
                    remote = r.REMOTE_ROOT + '/' + p
                    if not backup[remote]['exists']:
                        # Also remove a new runtime module or asset when rolling back.
                        # Delete only the exact new bytes from this transaction.
                        remote_json(client, f'''import pathlib,hashlib,json,os
p=pathlib.Path({remote!r});root=pathlib.Path({r.REMOTE_ROOT!r})
assert p.is_relative_to(root) and p!=root and not p.is_symlink()
if p.exists():
 assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()=={hashlib.sha256(data[p]).hexdigest()!r}
 p.unlink()
 d=os.open(str(p.parent),os.O_RDONLY);os.fsync(d);os.close(d)
print(json.dumps({{'new_release_file_removed':True}}))
''')
                        continue
                    current = read(p)
                    assert current in (before[p], data[p]), 'Concurrent modification during rollback: ' + p
                    rollback_path = remote + '.image-loading-rollback'
                    r.command(client, 'cp -- ' + shlex.quote(r.transaction_file(tx, remote, 'backup')) + ' ' + shlex.quote(rollback_path))
                    sftp.chmod(rollback_path, backup[remote]['mode'])
                    sftp.posix_rename(rollback_path, remote)
                    r.fsync_remote_file(client, remote)
                    assert read(p) == before[p], 'Rollback file mismatch: ' + p
                r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
                r.wait_for_loopback_live(client)
                r.set_remote_release_drain(client, True, require_start_draining=True)
                phase('rolled-back')
            except BaseException:
                state['phase'] = 'rollback-failed'
                try:
                    r.write_transaction_phase(client, tx, 'rollback-failed')
                finally:
                    t._atomic_json(STATE, state)
                raise
        elif stopped:
            r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
            r.wait_for_loopback_live(client)
        raise
    finally:
        # Failed rollback keeps the lock, admission fence and watchdog isolation
        # for recovery. Successful rollback never restores database/JSON backups.
        try:
            if locked and (not swapped or state.get('phase') in ('committed', 'rolled-back')):
                if isolated:
                    r.restore_watchdog_state(client, state['watchdog'])
                if admission:
                    r.set_release_start_draining(client, False)
                    r.set_remote_release_drain(client, False)
                r.release_release_lock(client, tx)
                state['cleanup_complete'] = True
                t._atomic_json(STATE, state)
        finally:
            sftp.close()
            client.close()


if __name__ == '__main__':
    main()
