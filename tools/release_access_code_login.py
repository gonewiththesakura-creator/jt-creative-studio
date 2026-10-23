"""Scoped access-code rollout with production-only backup and queue preservation."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request

import prepare_dreamapi_native_canary as t
from release_membership_cutover import queue, remote_json

r = t.release
ORIGIN = 'https://studio.dreamapi.club'
STATE = t.BASE / 'audit/access-code-release-20261010/release.json'
DROPIN = '/etc/systemd/system/comfy-panel.service.d/zzz-access-code.conf'
NGINX = '/etc/nginx/conf.d/jt-workbench.conf'
DATA = r.REMOTE_ROOT + '/panel_data'


def read(sftp, relative):
    try:
        with sftp.open(r.REMOTE_ROOT + '/' + relative, 'rb') as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def fetch(path):
    try:
        with urllib.request.urlopen(urllib.request.Request(ORIGIN + path,
                headers={'Cache-Control': 'no-cache'}), timeout=40) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main():
    import retired_release
    retired_release.refuse_main(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((t.BASE/'static/app-manifest.json').read_text(encoding='utf-8'))
    assets = [p.lstrip('/') for p in manifest['assets']]
    assert all(re.fullmatch(r'static/assets/[A-Za-z0-9_-]+\.[0-9a-f]{12}\.(?:js|css|html|json|txt|webp)', p) for p in assets)
    paths = r.require_server_runtime_modules(
        [*assets, *r.SERVER_RUNTIME_MODULE_PATHS, 'static/app-manifest.json', 'static/app.html'])
    normalize = lambda p, raw: raw.replace(b'\r\n', b'\n') if not p.endswith('.webp') else raw
    data = {p: normalize(p, (t.BASE/p).read_bytes()) for p in paths}
    if args.execute:
        if STATE.exists():
            raise RuntimeError('Inspect the existing release transaction before another attempt')
        r.run_feature_release_gate(data, normalize)
    client = t._connect(t.BASE/'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    sftp = client.open_sftp()
    tx = None
    locked = admission = isolated = stopped = swapped = configured = False
    state = {}
    try:
        before = {p: read(sftp, p) for p in paths}
        for p in paths:
            if before[p] is None:
                assert p in assets, 'Missing production module: ' + p
            elif before[p] != data[p]:
                baseline = subprocess.run(['git', 'show', 'HEAD:'+p], cwd=t.BASE, capture_output=True)
                assert baseline.returncode == 0 and before[p] == baseline.stdout.replace(b'\r\n', b'\n'), 'Live baseline changed: '+p
        changed = [p for p in paths if before[p] != data[p]]
        assert json.loads(fetch('/api/auth/me')[1]).get('enabled')
        assert fetch('/api/jobs')[0] == 401
        with sftp.open(NGINX, 'rb') as handle:
            nginx_before = handle.read()
        old_rule = b'location ~ ^/api/(?:auth/login|membership/redeem)$ {'
        new_rule = b'location ~ ^/api/(?:auth/(?:login|code-login)|membership/redeem)$ {'
        assert nginx_before.count(old_rule) == 1, 'Unexpected production login rate-limit rule'
        nginx = nginx_before.replace(old_rule, new_rule, 1)
        r.command(client, 'test ! -e ' + shlex.quote(DROPIN))
        r.require_release_start_draining_unset(client)
        current = queue(client)
        print(json.dumps({'phase': 'preflight', 'changed': changed, 'queue': current}), flush=True)
        if not args.execute:
            return
        tx = r.new_release_transaction()
        r.acquire_release_lock(client, tx)
        locked = True
        state = {'phase': 'preparing', 'transaction': tx, 'watchdog': r.capture_watchdog_state(client),
                 'files': {p: hashlib.sha256(raw).hexdigest() for p, raw in data.items()}}
        t._atomic_json(STATE, state)
        for p in changed:
            r.stage_file_resilient(client, sftp, t.BASE/p, r.REMOTE_ROOT+'/'+p, tx, data[p])
        backup = r.backup_release(client, sftp, [r.REMOTE_ROOT+'/'+p for p in changed], tx)
        t._upload(sftp, tx['stage_root']+'/access-code.conf', b'[Service]\nEnvironment=JT_LOGIN_MODE=access_code\n')
        t._upload(sftp, tx['stage_root']+'/nginx.conf', nginx)
        r.command(client, 'sudo cp -- '+shlex.quote(NGINX)+' '+shlex.quote(tx['root']+'/nginx-before.conf'))
        r.write_transaction_phase(client, tx, 'prepared')
        admission = True
        r.set_release_start_draining(client, True)
        busy = r.set_remote_release_drain(client, True)
        deadline = time.monotonic()+900
        while queue(client)['active'] or any(busy[k] for k in ('cloud_busy', 'local_busy', 'api_busy')):
            if time.monotonic() >= deadline:
                raise RuntimeError('Active work has not finished; no jobs were cancelled')
            print('Waiting for existing active work to finish naturally', flush=True)
            time.sleep(15)
            busy = r.set_remote_release_drain(client, True)
        isolated = True
        r.isolate_watchdog(client)
        stopped = True
        r.stop_panel_resilient(client)
        # A server-local online backup also preserves a valid database if WAL exists.
        remote_json(client, f'''import sqlite3,pathlib,json,shutil,os
root=pathlib.Path({DATA!r}); target=pathlib.Path({tx['root']!r})
src=sqlite3.connect(str(root/'membership.sqlite3')); dst=sqlite3.connect(str(target/'membership-before.sqlite3'))
src.backup(dst);dst.close();src.close();os.chmod(target/'membership-before.sqlite3',0o600)
for name in ('jobs.json','favorites.json','upload_capabilities.json'):
 if (root/name).exists(): shutil.copy2(root/name,target/('before-'+name));os.chmod(target/('before-'+name),0o600)
print(json.dumps({{'server_data_backed_up':True}}))
''')
        for p in changed:
            assert read(sftp, p) == before[p], 'Concurrent change during preparation: '+p
        with sftp.open(NGINX, 'rb') as handle:
            assert handle.read() == nginx_before, 'Concurrent nginx configuration change'
        r.write_transaction_phase(client, tx, 'swapping')
        swapped = True
        for p in changed:
            remote = r.REMOTE_ROOT+'/'+p
            staged = r.transaction_file(tx, remote, 'stage')
            sftp.chmod(staged, 0o644)
            sftp.posix_rename(staged, remote)
            r.fsync_remote_file(client, remote)
        configured = True
        r.command(client, 'sudo install -m 644 '+shlex.quote(tx['stage_root']+'/access-code.conf')+' '+shlex.quote(DROPIN))
        r.command(client, 'sudo install -m 644 '+shlex.quote(tx['stage_root']+'/nginx.conf')+' '+shlex.quote(NGINX))
        r.command(client, 'sudo nginx -t')
        r.command(client, 'sudo systemctl daemon-reload')
        r.command(client, 'sudo systemctl reload nginx')
        r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
        r.wait_for_loopback_live(client)
        r.set_remote_release_drain(client, True, require_start_draining=True)
        me = json.loads(fetch('/api/auth/me')[1])
        assert me.get('login_method') == 'access_code' and not me.get('authenticated')
        assert fetch('/api/jobs')[0] == 401 and fetch('/api/admin/release-drain')[0] == 404
        def verify(p):
            status, raw = fetch('/' if p == 'static/app.html' else '/'+p)
            assert status == 200 and raw == data[p], 'Public byte mismatch: '+p
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(verify, assets+['static/app.html','static/app-manifest.json']))
        state['verification'] = remote_json(client, f'''import pathlib,json,sqlite3
root=pathlib.Path({DATA!r}); backup=pathlib.Path({tx['root']!r})
before=json.loads((backup/'before-jobs.json').read_text());after=json.loads((root/'jobs.json').read_text())
assert before==after,'Job data changed during release'
for name in ('favorites.json','upload_capabilities.json'):
 if (backup/('before-'+name)).exists(): assert (backup/('before-'+name)).read_bytes()==(root/name).read_bytes(),name
db=sqlite3.connect('file:'+str(root/'membership.sqlite3')+'?mode=ro',uri=True)
old=sqlite3.connect('file:'+str(backup/'membership-before.sqlite3')+'?mode=ro',uri=True)
for table in ('users','plans','entitlements','activation_codes','reservations'):
 assert db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()==old.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall(),table
assert db.execute('PRAGMA user_version').fetchone()[0]==2
print(json.dumps({{'jobs_preserved':len(after),'queued_preserved':sum(j.get('status')=='queued' for j in after.values()),'existing_membership_preserved':True}}))
''')
        state['phase'] = 'committed'
        r.write_transaction_phase(client, tx, 'committed')
        t._atomic_json(STATE, state)
        print('ACCESS_CODE_RELEASE_COMPLETE', flush=True)
    except BaseException:
        if swapped:
            r.stop_panel_resilient(client)
            # v2 is additive. Retain the compatible store on rollback so live
            # membership activity is never discarded by restoring an old DB.
            for p in changed:
                remote = r.REMOTE_ROOT+'/'+p
                if p == 'membership_store.py' or not backup[remote]['exists']:
                    continue
                r.command(client, 'cp -- '+shlex.quote(r.transaction_file(tx,remote,'backup'))+' '+shlex.quote(remote+'.access-rollback'))
                sftp.chmod(remote+'.access-rollback', backup[remote]['mode'])
                sftp.posix_rename(remote+'.access-rollback', remote)
                r.fsync_remote_file(client, remote)
            if configured:
                r.command(client, 'sudo rm -f -- '+shlex.quote(DROPIN))
                r.command(client, 'sudo install -m 644 '+shlex.quote(tx['root']+'/nginx-before.conf')+' '+shlex.quote(NGINX))
                r.command(client, 'sudo systemctl daemon-reload')
                r.command(client, 'sudo nginx -t')
                r.command(client, 'sudo systemctl reload nginx')
            r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
            r.wait_for_loopback_live(client)
            state['phase'] = 'rolled-back'
            r.write_transaction_phase(client, tx, 'rolled-back')
            t._atomic_json(STATE, state)
        elif stopped:
            r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
            r.wait_for_loopback_live(client)
        raise
    finally:
        if locked and (not swapped or state.get('phase') in ('committed','rolled-back')):
            if isolated:
                r.restore_watchdog_state(client, state['watchdog'])
            if admission:
                r.set_release_start_draining(client, False)
                r.set_remote_release_drain(client, False)
            r.release_release_lock(client, tx)
            state['cleanup_complete'] = True
            t._atomic_json(STATE, state)
        sftp.close()
        client.close()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
