"""Publish only video UI files, preserving the live process and generation queue."""
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import urllib.request

import prepare_dreamapi_native_canary as transport

r = transport.release
BASE = transport.BASE
ENTRYPOINTS = ('static/video.html', 'static/app-manifest.json', 'static/app.html')


def normalized(path, raw):
    return raw if path.endswith('.png') else raw.replace(b'\r\n', b'\n')


def payloads():
    manifest = json.loads((BASE / 'static/app-manifest.json').read_text(encoding='utf8'))
    assets = []
    for kind, suffix in (('module', 'js'), ('markup', 'html'), ('css', 'css')):
        url = manifest['pages']['/video'][kind]
        if not re.fullmatch(r'/static/assets/video\.[0-9a-f]{12}\.' + suffix, url):
            raise RuntimeError('Unexpected video asset path: ' + kind)
        assets.append(url.lstrip('/'))
    paths = assets + ['static/favicon.png'] + list(ENTRYPOINTS)
    data = {path: normalized(path, (BASE / path).read_bytes()) for path in paths}
    if not data['static/favicon.png'].startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Favicon is not a PNG')
    return data


def connect():
    client = transport._connect(BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    return client, client.open_sftp()


def service_snapshot(client):
    script = """import json,subprocess,urllib.request
names=('MainPID','ExecMainStartTimestampMonotonic','ActiveState')
state={name:subprocess.run(['systemctl','show','comfy-panel','--property='+name,'--value'],check=True,capture_output=True,text=True).stdout.strip() for name in names}
with urllib.request.urlopen('http://127.0.0.1:8189/api/health',timeout=20) as f: health=json.load(f)
state['draining']=bool(health.get('draining'))
print(json.dumps(state))
"""
    state = json.loads(r.command(client, 'python3 -c ' + shlex.quote(script), timeout=30))
    if state['ActiveState'] != 'active' or int(state['MainPID']) < 1 or state['draining']:
        raise RuntimeError('Production service is not active or is draining')
    return state


def baseline(client, sftp, data):
    before = {}
    for path, expected in data.items():
        previous = subprocess.run(['git', 'show', 'HEAD:' + path], cwd=BASE, capture_output=True)
        try:
            with sftp.open(r.REMOTE_ROOT + '/' + path, 'rb') as handle:
                current = handle.read()
        except FileNotFoundError:
            if previous.returncode == 0:
                raise RuntimeError('Production file missing: ' + path)
            before[path] = None
            continue
        if normalized(path, current) != expected and (
                previous.returncode != 0 or normalized(path, current) != normalized(path, previous.stdout)):
            raise RuntimeError('Production baseline differs: ' + path)
        before[path] = hashlib.sha256(current).hexdigest()
    return before, service_snapshot(client)


def verify_public(data):
    for path, expected in data.items():
        if path == 'static/favicon.png':
            with urllib.request.urlopen(r.PUBLIC_BASE + '/' + path, timeout=30) as response:
                if response.headers.get_content_type() != 'image/png':
                    raise RuntimeError('Public favicon MIME mismatch')
                actual = response.read(len(expected) + 1)
        else:
            actual = r.fetch_bytes_resilient(r.PUBLIC_BASE, '/' + path,
                                             timeout=30, max_bytes=len(expected))
        if actual != expected:
            raise RuntimeError('Public UI bytes differ: ' + path)
    expected = data['static/app.html']
    if r.fetch_bytes_resilient(r.PUBLIC_BASE, '/video', timeout=30, max_bytes=len(expected)) != expected:
        raise RuntimeError('Public video entry differs')


def restore_static(client, sftp, tx, backup, paths):
    """Restore prior static files only; new hash files remain for open browser tabs."""
    with sftp.open(tx['manifest'], 'rb') as handle:
        raw = handle.read()
    with sftp.open(tx['manifest_sha256'], 'rb') as handle:
        digest = handle.read().decode('ascii').strip()
    if hashlib.sha256(raw).hexdigest() != digest or json.loads(raw) != backup:
        raise RuntimeError('Static backup manifest is unverified')
    # Restore entrypoints before their assets; both generations of hash assets remain available.
    order = list(reversed(ENTRYPOINTS)) + [path for path in paths if path not in ENTRYPOINTS]
    for path in order:
        remote = r.REMOTE_ROOT + '/' + path
        item = backup[remote]
        if not item['exists']:
            continue
        saved = r.transaction_file(tx, remote, 'backup')
        with sftp.open(saved, 'rb') as handle:
            if hashlib.sha256(handle.read()).hexdigest() != item['sha256']:
                raise RuntimeError('Static backup bytes differ: ' + path)
        temporary = r.transaction_file(tx, remote, 'stage') + '.restore'
        r.command(client, 'cp -- ' + shlex.quote(saved) + ' ' + shlex.quote(temporary))
        sftp.chmod(temporary, item['mode'])
        r.fsync_remote_file(client, temporary)
        sftp.posix_rename(temporary, remote)
        r.fsync_remote_file(client, remote)
        with sftp.open(remote, 'rb') as handle:
            if hashlib.sha256(handle.read()).hexdigest() != item['sha256']:
                raise RuntimeError('Static rollback bytes differ: ' + path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--audit-dir', type=pathlib.Path)
    args = parser.parse_args(argv)
    data = payloads()
    tx = r.new_release_transaction()
    audit = (args.audit_dir or BASE / 'audit' / ('video-ui-' + tx['id'])) / 'release.json'
    state = {'transaction': tx, 'phase': 'preflight', 'static_only': True,
             'files': {p: hashlib.sha256(raw).hexdigest() for p, raw in data.items()}}
    client, sftp = connect()
    locked = swapped = False
    backup = None
    try:
        before, process = baseline(client, sftp, data)
        state.update(before=process, baseline=before, phase='preflight-ok')
        transport._atomic_json(audit, state)
        print('STATIC_UI_PREFLIGHT_OK', len(data), 'files; live process retained', flush=True)
        if not args.execute:
            return 0
        r.acquire_release_lock(client, tx)
        locked = True
        for path, raw in data.items():
            try:
                r.stage_file_resilient(client, sftp, BASE / path, r.REMOTE_ROOT + '/' + path, tx, raw)
            except (EOFError, OSError):
                sftp.close(); client.close()
                client, sftp = connect()
                r.stage_file_resilient(client, sftp, BASE / path, r.REMOTE_ROOT + '/' + path, tx, raw)
        remotes = [r.REMOTE_ROOT + '/' + path for path in data]
        backup = r.backup_release(client, sftp, remotes, tx)
        for path, digest in before.items():
            if backup[r.REMOTE_ROOT + '/' + path]['sha256'] != digest:
                raise RuntimeError('Production changed after preflight: ' + path)
        r.write_transaction_phase(client, tx, 'prepared')
        state['phase'] = 'prepared'; transport._atomic_json(audit, state)
        r.write_transaction_phase(client, tx, 'swapping')
        swapped = True
        for path, raw in data.items():
            remote = r.REMOTE_ROOT + '/' + path
            staged = r.transaction_file(tx, remote, 'stage')
            item = backup[remote]
            sftp.chmod(staged, item['mode'] if item['exists'] else 0o644)
            sftp.posix_rename(staged, remote)
            r.fsync_remote_file(client, remote)
            with sftp.open(remote, 'rb') as handle:
                if handle.read() != raw:
                    raise RuntimeError('Live UI bytes differ: ' + path)
        verify_public(data)
        after = service_snapshot(client)
        state['after'] = after
        if after != process:
            raise RuntimeError('Service process changed during static UI release')
        r.write_transaction_phase(client, tx, 'committed')
        state['phase'] = 'committed'; transport._atomic_json(audit, state)
        print('STATIC_UI_DEPLOYED_BYTES_VERIFIED', flush=True)
    except BaseException as error:
        state['error'] = str(error)
        if swapped and state['phase'] != 'committed':
            sftp.close(); client.close()
            client, sftp = connect()
            try:
                r.write_transaction_phase(client, tx, 'rolling-back')
                restore_static(client, sftp, tx, backup, data)
                r.write_transaction_phase(client, tx, 'rolled-back')
                state['phase'] = 'rolled-back'
            except BaseException as rollback_error:
                state.update(phase='rollback-failed', rollback_error=str(rollback_error))
                transport._atomic_json(audit, state)
                raise
        else:
            state['phase'] = 'failed'
        transport._atomic_json(audit, state)
        raise
    finally:
        if locked and (not swapped or state['phase'] in ('committed', 'rolled-back')):
            sftp.close(); client.close()
            client, sftp = connect()
            r.release_release_lock(client, tx)
            state['cleanup_complete'] = True
            transport._atomic_json(audit, state)
        sftp.close(); client.close()
    print('STATIC_UI_RELEASE_COMPLETE', tx['id'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
