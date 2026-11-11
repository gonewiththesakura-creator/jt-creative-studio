"""Publish the additive video queue plan field using the existing release transaction.

Default invocation only reads production. --execute naturally drains active
work, preserves every queued job, and makes a server-local SQLite backup.
Rollback restores code, never production data, and retains the additive column.
"""
import argparse
import concurrent.futures
import hashlib
import inspect
import json
import pathlib
import re
import shlex
import sqlite3
import stat
import subprocess
import sys
import time

import prepare_dreamapi_native_canary as t
from release_image_loading import fetch
from release_membership_cutover import queue, remote_json

r = t.release
sys.path.insert(0, str(t.BASE))
DATA = r.REMOTE_ROOT + '/panel_data'
# server.py's whole local-module closure. Releases built on this transaction append
# only non-Python payload; unchanged modules match production and are never staged.
RUNTIME_MODULES = r.SERVER_RUNTIME_MODULE_PATHS
MODULES = RUNTIME_MODULES
ENTRIES = ('static/app-manifest.json', 'static/app.html')
DEFAULT_STATE = t.BASE / 'audit/video-queue-plan-20261017/release.json'


def verify_database(before_path, after_path):
    """Compare every pre-existing column and row; the new column defaults to 100."""
    old = sqlite3.connect(pathlib.Path(before_path).resolve().as_uri() + '?mode=ro', uri=True)
    db = sqlite3.connect(pathlib.Path(after_path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        tables = lambda connection: {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables(old) == tables(db), 'Unexpected membership table changes'
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SQLite integrity check failed'
        counts = {}
        for table in sorted(tables(old)):
            assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table), 'Unexpected table identifier'
            old_columns = [row[1] for row in old.execute('PRAGMA table_info(' + table + ')')]
            columns = [row[1] for row in db.execute('PRAGMA table_info(' + table + ')')]
            # Reviewed additive columns: plans.max_video_queued (2026-10-17) and the nullable
            # reservations.slot_released_at (2026-11-11, frees a concurrency slot of an ended
            # but unconfirmed job; rollback code ignores it and keeps counting that slot).
            expected = set(old_columns) | ({'max_video_queued'} if table == 'plans' else
                                           {'slot_released_at'} if table == 'reservations' else set())
            assert set(columns) == expected, 'Unexpected columns: ' + table
            projection = ','.join('"' + name.replace('"', '""') + '"' for name in old_columns)
            query = 'SELECT ' + projection + ' FROM "' + table + '" ORDER BY rowid'
            previous = old.execute(query).fetchall()
            assert previous == db.execute(query).fetchall(), 'Existing membership data changed: ' + table
            counts[table] = len(previous)
        definition = next(row for row in db.execute('PRAGMA table_info(plans)') if row[1] == 'max_video_queued')
        assert definition[2].upper() == 'INTEGER' and definition[3] == 1 and str(definition[4]) == '100', 'Queue column contract changed'
        released = next(row for row in db.execute('PRAGMA table_info(reservations)') if row[1] == 'slot_released_at')
        assert released[2].upper() == 'INTEGER' and released[3] == 0 and released[4] is None, 'Slot release column contract changed'
        old_columns = {row[1] for row in old.execute('PRAGMA table_info(plans)')}
        if 'max_video_queued' not in old_columns:
            assert db.execute('SELECT COUNT(*) FROM plans WHERE max_video_queued != 100').fetchone()[0] == 0, 'Legacy plan defaults changed'
        assert db.execute('PRAGMA user_version').fetchone() == old.execute('PRAGMA user_version').fetchone(), 'Schema version must remain compatible with rollback code'
        return {'existing_membership_preserved': True, 'legacy_queue_default': 100, 'table_counts': counts}
    finally:
        old.close()
        db.close()


def preflight(client):
    # The shared require_* helpers reload systemd; avoid them in read-only mode.
    return remote_json(client, f'''import json,pathlib,shlex,subprocess,urllib.request,sqlite3
root=pathlib.Path({r.REMOTE_ROOT!r});start=pathlib.Path({r.RELEASE_START_DRAIN_DROPIN_FILE!r})
assert not (root/'.release.lock').exists(), 'Existing release lock requires recovery'
assert not start.exists() and not start.is_symlink(), 'Existing start-drain configuration requires recovery'
def show(name):return subprocess.check_output(['systemctl','show','comfy-panel','-p',name,'--value'],text=True).strip()
service_user=show('User');assert service_user in ('admin','jt-panel'), 'Unexpected panel service user'
assert str(start) not in shlex.split(show('DropInPaths')), 'Stale loaded start-drain configuration'
assert not any(v.split('=',1)[0]=='PANEL_RELEASE_DRAIN_ON_START' for v in shlex.split(show('Environment'))), 'Conflicting start-drain environment'
assert not any(v.split('=',1)[0]=='PANEL_RELEASE_DRAIN_ON_START' for v in shlex.split(show('UnsetEnvironment'))), 'Conflicting start-drain unset rule'
live=json.load(urllib.request.urlopen('http://127.0.0.1:8189/api/live',timeout=15))
assert live.get('ok') and live.get('service')=='comfy-panel', 'Service liveness failed'
db=sqlite3.connect('file:'+str(root/'panel_data/membership.sqlite3')+'?mode=ro',uri=True)
version=db.execute('PRAGMA user_version').fetchone()[0];db.close()
print(json.dumps({{'live':True,'release_lock':False,'start_drain':False,'membership_schema_version':version,'service_user':service_user}}))
''', root=True)


def verify_frontend_scope(baseline, manifest, data):
    """Permit only the account/admin modules and their main import references."""
    previous = json.loads(subprocess.check_output(
        ['git', 'show', baseline + ':' + ENTRIES[0]], cwd=t.BASE))
    removed = set(previous['assets']) - set(manifest['assets'])
    added = set(manifest['assets']) - set(previous['assets'])
    replacements = {}
    for name in ('account', 'membership-admin', 'main'):
        pattern = re.compile(r'/static/assets/' + name + r'\.[0-9a-f]{12}\.js')
        old = [path for path in removed if pattern.fullmatch(path)]
        new = [path for path in added if pattern.fullmatch(path)]
        assert len(old) == len(new) and len(old) <= 1, 'Unexpected frontend module change: ' + name
        if old:
            replacements[old[0]] = new[0]
    assert removed == set(replacements) and added == set(replacements.values()), 'Unrelated frontend assets changed'
    expected = dict(previous, main=replacements.get(previous['main'], previous['main']),
                    assets=sorted(replacements.get(path, path) for path in previous['assets']))
    assert manifest == expected, 'Unrelated workbench page changes'
    expected_html = subprocess.check_output(['git', 'show', baseline + ':' + ENTRIES[1]], cwd=t.BASE).replace(b'\r\n', b'\n')
    for old, new in replacements.items():
        expected_html = expected_html.replace(old.encode(), new.encode())
    assert data[ENTRIES[1]] == expected_html, 'Unexpected HTML entrypoint changes'
    for path in manifest['assets']:
        relative = path.removeprefix('/')
        assert hashlib.sha256(data[relative]).hexdigest()[:12] == relative.split('.')[-2], 'Asset filename hash mismatch: ' + relative


def main(argv=None):
    import retired_release
    retired_release.refuse_main(__file__)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--state', type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument('--drain-timeout', type=int, default=900)
    args = parser.parse_args(argv)
    assert 15 <= args.drain_timeout <= 3600, 'Drain timeout must be 15-3600 seconds'
    baseline = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=t.BASE, text=True).strip()
    manifest = json.loads((t.BASE / ENTRIES[0]).read_text(encoding='utf-8'))
    assets = [path.removeprefix('/') for path in manifest['assets']]
    assert assets and len(set(assets)) == len(assets), 'Invalid asset manifest'
    assert all(re.fullmatch(r'static/assets/[A-Za-z0-9_-]+\.[0-9a-f]{12}\.(?:js|css|html|json|txt|webp)', path) for path in assets), 'Unexpected asset path'
    paths = r.require_server_runtime_modules([*assets, *MODULES, *ENTRIES])
    normalize = lambda path, raw: raw if path.endswith('.webp') else raw.replace(b'\r\n', b'\n')
    data = {path: normalize(path, (t.BASE / path).read_bytes()) for path in paths}
    verify_frontend_scope(baseline, manifest, data)
    # A v3 version stamp prevents the old v2 runtime from starting on rollback.
    from membership_store import MembershipStore
    assert MembershipStore.SCHEMA_VERSION == 2, 'Use a rollback-compatible additive migration'
    if args.execute:
        assert not args.state.exists(), 'Inspect existing release state before retry'
        # Every release built on this transaction ships server.py's whole closure, so it
        # runs the whole gate, never a hand-picked subset of tests.
        r.run_feature_release_gate(data, normalize)
    client = t._connect(t.BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    sftp = client.open_sftp()
    tx = None
    locked = admission = isolated = stopped = swapped = False
    recovery_ready = True
    state = {}

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
        t._atomic_json(args.state, state)

    try:
        checked = preflight(client)
        assert checked['membership_schema_version'] == MembershipStore.SCHEMA_VERSION, 'Unexpected production schema version'
        hashes = remote_json(client, f'''import json,pathlib,hashlib,stat
root=pathlib.Path({r.REMOTE_ROOT!r});result={{}}
for name in {paths!r}:
 path=root/name
 if not path.exists():
  assert not path.is_symlink(), 'Dangling release symlink'
  result[name]=None
 else:
  assert stat.S_ISREG(path.lstat().st_mode), 'Release target is not a regular file'
  result[name]=hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result))
''')
        changed = [path for path in paths if hashes[path] != hashlib.sha256(data[path]).hexdigest()]
        for path in paths:
            if hashes[path] is None:
                assert path in assets, 'Missing production module: ' + path
            elif path in changed:
                original = subprocess.run(['git', 'show', baseline + ':' + path], cwd=t.BASE, capture_output=True)
                assert original.returncode == 0 and hashes[path] == hashlib.sha256(normalize(path, original.stdout)).hexdigest(), 'Production drift: ' + path
        before = {path: read(path) for path in changed}
        assert all((hashlib.sha256(raw).hexdigest() if raw is not None else None) == hashes[path]
                   for path, raw in before.items()), 'Production changed during preflight'
        current = queue(client)
        assert fetch('/api/jobs')[0] == 401
        print(json.dumps({'phase': 'preflight', 'baseline': baseline, 'changed': changed,
                          'active': len(current['active']), 'waiting': len(current['waiting']), **checked}), flush=True)
        if not args.execute or not changed:
            return
        r.require_persistent_release_drain_contract(client)
        r.require_release_start_draining_unset(client)
        tx = r.new_release_transaction()
        r.acquire_release_lock(client, tx)
        locked = True
        state = {'phase': 'preparing', 'transaction': tx, 'baseline': baseline,
                 'watchdog': r.capture_watchdog_state(client),
                 'files': {path: hashlib.sha256(raw).hexdigest() for path, raw in data.items()}}
        t._atomic_json(args.state, state)
        for path in changed:
            r.stage_file_resilient(client, sftp, t.BASE / path, r.REMOTE_ROOT + '/' + path, tx, data[path])
        backup = r.backup_release(client, sftp, [r.REMOTE_ROOT + '/' + path for path in changed], tx)
        phase('prepared')
        admission = True
        r.set_release_start_draining(client, True)
        busy = r.set_remote_release_drain(client, True)
        queued = queue(client)['waiting']
        deadline = time.monotonic() + args.drain_timeout
        while queue(client)['active'] or any(busy[key] for key in ('cloud_busy', 'local_busy', 'api_busy')):
            if time.monotonic() >= deadline:
                raise RuntimeError('Active work still running; no tasks cancelled')
            print('Waiting for active tasks to finish naturally; preserving queued tasks', flush=True)
            time.sleep(15)
            busy = r.set_remote_release_drain(client, True)
        isolated = True
        r.isolate_watchdog(client)
        stopped = True
        recovery_ready = False
        r.stop_panel_resilient(client)
        state['backup'] = remote_json(client, f'''import sqlite3,pathlib,json,shutil,os
root=pathlib.Path({DATA!r});target=pathlib.Path({tx['root']!r})
jobs=json.loads((root/'jobs.json').read_text())
assert all(key in jobs and jobs[key].get('status')=='queued' for key in {queued!r}), 'Queued jobs changed while draining'
src=sqlite3.connect('file:'+str(root/'membership.sqlite3')+'?mode=ro',uri=True)
dst=sqlite3.connect(str(target/'membership-before.sqlite3'));src.backup(dst);dst.close();src.close()
for name in ('jobs.json','favorites.json','upload_capabilities.json'):
 if (root/name).exists():shutil.copy2(root/name,target/('before-'+name))
for path in [target/'membership-before.sqlite3',*[target/('before-'+name) for name in ('jobs.json','favorites.json','upload_capabilities.json') if (target/('before-'+name)).exists()]]:
 os.chmod(path,0o600)
 with path.open('rb') as handle:os.fsync(handle.fileno())
fd=os.open(str(target),os.O_RDONLY);os.fsync(fd);os.close(fd)
print(json.dumps({{'server_local_backup':True,'jobs':len(jobs),'queued':sum(v.get('status')=='queued' for v in jobs.values())}}))
''', root=True)
        for path in changed:
            assert read(path) == before[path], 'Concurrent production change: ' + path
        phase('swapping')
        swapped = True
        for path in changed:
            remote = r.REMOTE_ROOT + '/' + path
            staged = r.transaction_file(tx, remote, 'stage')
            sftp.chmod(staged, 0o644)
            sftp.posix_rename(staged, remote)
            r.fsync_remote_file(client, remote)
        migration = ('import sys;sys.path.insert(0,' + repr(r.REMOTE_ROOT) + ');'
                     'from membership_store import MembershipStore;'
                     'MembershipStore(' + repr(DATA + '/membership.sqlite3') + ')')
        # Run the idempotent schema initialization as the service owner while
        # stopped, then compare all tables before logins can change session data.
        r.command(client, 'sudo -u ' + shlex.quote(checked['service_user']) + ' python3 -c ' + shlex.quote(migration))
        verifier = inspect.getsource(verify_database)
        state['data_verification'] = remote_json(client, f'''import pathlib,json,sqlite3,re
{verifier}
root=pathlib.Path({DATA!r});backup=pathlib.Path({tx['root']!r})
before=json.loads((backup/'before-jobs.json').read_text());after=json.loads((root/'jobs.json').read_text())
assert before==after, 'Job ledger changed during release'
for name in ('favorites.json','upload_capabilities.json'):
 if (backup/('before-'+name)).exists():assert (backup/('before-'+name)).read_bytes()==(root/name).read_bytes(),name
result=verify_database(backup/'membership-before.sqlite3',root/'membership.sqlite3')
result.update(jobs_preserved=len(after),queued_preserved=sum(v.get('status')=='queued' for v in after.values()))
print(json.dumps(result))
''', root=True)
        r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
        r.wait_for_loopback_live(client)
        r.set_remote_release_drain(client, True, require_start_draining=True)
        recovery_ready = True
        state['restart_verification'] = remote_json(client, f'''import pathlib,json
root=pathlib.Path({DATA!r});backup=pathlib.Path({tx['root']!r})
before=json.loads((backup/'before-jobs.json').read_text());after=json.loads((root/'jobs.json').read_text())
assert before==after, 'Restart changed the job ledger'
print(json.dumps({{'jobs_preserved':len(after),'queued_preserved':sum(v.get('status')=='queued' for v in after.values())}}))
''', root=True)
        status, raw, _ = fetch('/api/auth/me')
        me = json.loads(raw)
        assert status == 200 and me.get('login_method') == 'access_code' and not me.get('authenticated')
        assert fetch('/api/jobs')[0] == 401 and fetch('/api/admin/release-drain')[0] == 404

        def verify_asset(path):
            status, raw, _ = fetch('/' if path == 'static/app.html' else '/' + path)
            assert status == 200 and raw == data[path], 'Public asset mismatch: ' + path

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(verify_asset, [*[path for path in changed if path in assets], *ENTRIES]))
        assert all(read(path) == data[path] for path in MODULES), 'Published module mismatch'
        phase('committed')
    except BaseException:
        if swapped:
            try:
                recovery_ready = False
                phase('rolling-back')
                r.stop_panel_resilient(client)
                # Keep newly hashed assets: old entrypoints never reference them.
                # Restore modules and entrypoints, retain the additive DB column.
                for path in changed:
                    remote = r.REMOTE_ROOT + '/' + path
                    if not backup[remote]['exists']:
                        continue
                    assert read(path) in (before[path], data[path]), 'Concurrent rollback change: ' + path
                    rollback = remote + '.video-queue-plan-rollback'
                    r.command(client, 'cp -- ' + shlex.quote(r.transaction_file(tx, remote, 'backup')) + ' ' + shlex.quote(rollback))
                    sftp.chmod(rollback, backup[remote]['mode'])
                    sftp.posix_rename(rollback, remote)
                    r.fsync_remote_file(client, remote)
                    assert read(path) == before[path], 'Rollback bytes differ: ' + path
                r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
                r.wait_for_loopback_live(client)
                r.set_remote_release_drain(client, True, require_start_draining=True)
                recovery_ready = True
                phase('rolled-back')
            except BaseException:
                state['phase'] = 'rollback-failed'
                try:
                    r.write_transaction_phase(client, tx, 'rollback-failed')
                finally:
                    t._atomic_json(args.state, state)
                raise
        elif stopped:
            r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
            r.wait_for_loopback_live(client)
            recovery_ready = True
        raise
    finally:
        try:
            if locked and recovery_ready and (not swapped or state.get('phase') in ('committed', 'rolled-back')):
                if isolated:
                    r.restore_watchdog_state(client, state['watchdog'])
                if admission:
                    r.set_release_start_draining(client, False)
                    r.set_remote_release_drain(client, False)
                r.release_release_lock(client, tx)
                state['cleanup_complete'] = True
                t._atomic_json(args.state, state)
                if state.get('phase') == 'committed':
                    print('VIDEO_QUEUE_PLAN_RELEASE_COMPLETE', flush=True)
        finally:
            sftp.close()
            client.close()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
