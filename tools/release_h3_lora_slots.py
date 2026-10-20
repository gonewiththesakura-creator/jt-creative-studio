"""Scoped H3 release using the established backup/drain/rollback transaction."""
import argparse
import hashlib
import json
import pathlib
import shlex
import subprocess

import prepare_dreamapi_native_canary as transport

r = transport.release
BASE = r.BASE
STATE = BASE / 'audit/h3_lora_revision_20260928/release-state.json'
CORE = [*r.SERVER_RUNTIME_MODULE_PATHS, 'config.json', 'video_wf/h3_edit_multi_api.json',
        'static/video.html', 'static/app.html', 'static/app-manifest.json']


def payloads():
    manifest = json.loads((BASE/'static/app-manifest.json').read_text(encoding='utf8'))
    paths = set(CORE)
    paths.update(url.lstrip('/') for url in manifest['pages']['/video'].values() if url.startswith('/static/'))
    r.require_server_runtime_modules(paths)
    return {path: (BASE/path).read_bytes().replace(b'\r\n', b'\n') for path in sorted(paths)}


def baseline(client, data):
    with client.open_sftp() as sftp:
        for path in data:
            previous = subprocess.run(['git', 'show', 'HEAD:'+path], cwd=BASE, capture_output=True)
            try:
                with sftp.open(r.REMOTE_ROOT+'/'+path, 'rb') as f:
                    current = f.read().replace(b'\r\n', b'\n')
            except FileNotFoundError:
                if previous.returncode == 0:
                    raise RuntimeError('Production file missing: '+path)
                continue
            if current == data[path]:
                continue
            if previous.returncode or current != previous.stdout.replace(b'\r\n', b'\n'):
                raise RuntimeError('Production baseline differs: '+path)
    health = r.require_loopback_idle(client, 'H3 preflight', samples=1)
    if health.get('draining') or health.get('dreamapi_uncertainty_fence'):
        raise RuntimeError('Production is draining or has an uncertainty fence')
    r.require_persistent_release_drain_contract(client)
    r.require_release_start_draining_unset(client)
    r.command(client, 'test ! -e '+shlex.quote(r.RELEASE_LOCK_DIR))
    return health


def verify(client, data):
    with client.open_sftp() as sftp:
        for path, expected in data.items():
            with sftp.open(r.REMOTE_ROOT+'/'+path, 'rb') as f:
                if f.read() != expected:
                    raise RuntimeError('Live byte mismatch: '+path)
    workflows = r.fetch_json(r.PUBLIC_BASE, '/api/workflows')
    workflow = next(w for w in workflows if w['id'] == 'h3_edit_n')
    if len([key for key in workflow['rh_params'] if key.startswith('lora_')]) != 6:
        raise RuntimeError('Public LoRA schema missing')
    if 'rh_lora_catalog' in workflow or '.safetensors' in json.dumps(workflow):
        raise RuntimeError('Public schema exposes private model names')
    remote_manifest = r.fetch_json(r.PUBLIC_BASE, '/static/app-manifest.json')
    expected_manifest = json.loads(data['static/app-manifest.json'])
    if remote_manifest != expected_manifest:
        raise RuntimeError('Public manifest mismatch')
    for key in ('css', 'module'):
        url = remote_manifest['pages']['/video'][key]
        import urllib.request
        with urllib.request.urlopen(r.PUBLIC_BASE+url, timeout=30) as response:
            actual = response.read()
        if actual != data[url.lstrip('/')]:
            raise RuntimeError('Public asset mismatch: '+key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    data = payloads()
    client = transport._connect(BASE/'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    try:
        baseline(client, data)
        print('PREFLIGHT_OK', len(data), 'files; production idle; baseline matches', flush=True)
        if not args.execute:
            return
        tx = r.new_release_transaction()
        r.acquire_release_lock(client, tx)
        state = {'transaction': tx, 'phase': 'locked', 'watchdog': r.capture_watchdog_state(client),
                 'files': {p: hashlib.sha256(v).hexdigest() for p, v in data.items()}}
        transport._atomic_json(STATE, state)
        transport._upload(client.open_sftp(), tx['root']+'/watchdog-state.json',
                          json.dumps(state['watchdog']).encode())
        swapped = False
        committed = False
        admission_touched = False
        watchdog_touched = False
        sftp = client.open_sftp()
        remotes = [r.REMOTE_ROOT+'/'+path for path in data]
        try:
            for path, raw in data.items():
                for attempt in range(3):
                    try:
                        r.stage_file_resilient(client, sftp, BASE/path, r.REMOTE_ROOT+'/'+path, tx, raw)
                        break
                    except (OSError, EOFError):
                        if attempt == 2:
                            raise
                        sftp.close(); client.close()
                        client = transport._connect(BASE/'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
                        sftp = client.open_sftp()
                print('STAGED', path, flush=True)
            staged_modules = [r.transaction_file(tx, r.REMOTE_ROOT+'/'+path, 'stage')
                              for path in r.SERVER_RUNTIME_MODULE_PATHS]
            r.command(client, 'python3 -m py_compile '+' '.join(map(shlex.quote, staged_modules)))
            manifest = r.backup_release(client, sftp, remotes, tx)
            r.write_transaction_phase(client, tx, 'prepared')
            admission_touched = True
            r.set_release_start_draining(client, True)
            r.enable_remote_release_drain(client, undo_if_busy=False)
            watchdog_touched = True
            r.isolate_watchdog(client)
            r.require_loopback_idle(client, 'H3 drained', samples=2, interval=1)
            # Do not interrupt an upload or a pending queue while restarting.
            script = """import json,pathlib,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8189/api/video-queue',timeout=10) as f: queue=json.load(f)
assert not queue.get('waiting') and not queue.get('running'), 'video queue is not idle'
root=pathlib.Path('/home/admin/comfy-panel/panel_data/upload_tmp')
assert not root.exists() or not any(p.is_file() for p in root.rglob('*')), 'staged upload exists'
"""
            r.command(client, 'python3 -c '+shlex.quote(script))
            state['phase'] = 'swapping'; transport._atomic_json(STATE, state)
            r.write_transaction_phase(client, tx, 'swapping')
            swapped = True
            r.stop_panel_resilient(client)
            for path in data:
                remote = r.REMOTE_ROOT+'/'+path
                sftp.posix_rename(r.transaction_file(tx, remote, 'stage'), remote)
                sftp.chmod(remote, manifest[remote]['mode'] if manifest[remote]['exists'] else 0o644)
                r.fsync_remote_file(client, remote)
            r.command(client, 'sudo systemctl start comfy-panel', timeout=60)
            r.wait_for_loopback_live(client)
            r.wait_for_remote_release_drain(client)
            verify(client, data)
            r.write_transaction_phase(client, tx, 'committed')
            committed = True
            state['phase'] = 'committed'; transport._atomic_json(STATE, state)
            print('DEPLOYED_BYTES_VERIFIED', flush=True)
        except BaseException:
            if swapped and not committed:
                r.write_transaction_phase(client, tx, 'rolling-back')
                r.rollback_release(client, sftp, remotes, tx)
                r.write_transaction_phase(client, tx, 'rolled-back')
                state['phase'] = 'rolled-back'; transport._atomic_json(STATE, state)
            raise
        finally:
            # Reconnect before cleanup if a slow transfer exhausted the SSH session.
            if not client.get_transport() or not client.get_transport().is_active():
                client = transport._connect(BASE/'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
            if not swapped or committed or state['phase'] == 'rolled-back':
                if watchdog_touched:
                    r.restore_watchdog_state(client, state['watchdog'])
                if admission_touched:
                    r.set_release_start_draining(client, False)
                    r.set_remote_release_drain(client, False)
                r.release_release_lock(client, tx)
                state['cleanup_complete'] = True; transport._atomic_json(STATE, state)
            sftp.close()
        print('RELEASE_COMPLETE', tx['id'], flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
