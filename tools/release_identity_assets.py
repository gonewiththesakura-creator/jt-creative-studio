"""Narrow identity-nginx transaction; default is a read-only release plan.

Only /etc/nginx/conf.d/jt-identity.conf may be replaced. The candidate is
constructed from its current bytes, retaining live fixes absent from templates.
Reuse the production release lock and pinned SSH connection. No container or
workbench restart, database access, login attempt, or provider request occurs.
"""
import argparse
import base64
import hashlib
import json
import pathlib
import re
import shlex

import prepare_dreamapi_native_canary as t

r = t.release
TARGET = '/etc/nginx/conf.d/jt-identity.conf'
TEMPLATE = t.BASE / 'deploy/membership/jt-identity.nginx.conf'
STATE = t.BASE / 'audit/identity-assets-release-20261015/release.json'
ZONE = b'limit_conn_zone $binary_remote_addr zone=jt_identity_assets_conn:10m;\n'
BLOCK = b'''    # Keep static module downloads out of the dynamic/login connection budget.
    # A plain prefix preserves the existing regex denial of hidden paths.
    location /assets/ {
        limit_conn jt_identity_assets_conn 60;
        limit_req zone=jt_identity_general burst=60 nodelay;
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host auth.dreamapi.club;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_buffer_size 16k;
        proxy_buffers 8 16k;
    }
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def candidate_from_live(raw):
    """Insert two exact additions, or refuse an unfamiliar/previously fixed file."""
    if b'\r' in raw or b'jt_identity_assets_conn' in raw or b'location /assets/' in raw:
        raise ValueError('Identity configuration is already patched or unfamiliar')
    anchors = (
        b'limit_conn_zone $binary_remote_addr zone=jt_identity_conn:10m;\n',
        b'    location / {\n        limit_req zone=jt_identity_general burst=60 nodelay;\n',
    )
    required = (
        b'    limit_conn jt_identity_conn 20;\n',
        b'limit_req_zone $binary_remote_addr zone=jt_identity_login:10m rate=10r/m;\n',
        b'limit_req_zone $binary_remote_addr zone=jt_identity_general:10m rate=30r/s;\n',
        b'        limit_req zone=jt_identity_login burst=10 nodelay;\n',
    )
    if any(raw.count(line) != 1 for line in anchors + required):
        raise ValueError('Identity configuration anchors/limits differ; review first')
    if re.search(rb'location[^\n]*assets', raw):
        raise ValueError('Unexpected existing assets location; review first')
    result = raw.replace(anchors[0], anchors[0] + ZONE, 1)
    result = result.replace(anchors[1], BLOCK + anchors[1], 1)
    if result.replace(ZONE, b'', 1).replace(BLOCK, b'', 1) != raw:
        raise ValueError('Candidate changes are not strictly additive')
    return result


# This single remote process owns backup, swap, nginx validation, reload, and
# rollback. Its private flock also serializes recovery after a lost SSH reply.
REMOTE_PROGRAM = r'''
import base64, concurrent.futures, fcntl, hashlib, json, os, pathlib, re
import signal, stat, subprocess, threading, time

def require(value, message):
    if not value: raise RuntimeError(message)

target = pathlib.Path('/etc/nginx/conf.d/jt-identity.conf')
tx = payload['transaction']
require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}', tx['id']), 'Bad transaction id')
root = pathlib.Path('/home/admin/comfy-panel/.release-transactions') / tx['id']
require(str(root) == tx['root'] and root.is_dir() and not root.is_symlink(), 'Bad transaction root')
require(pathlib.Path('/home/admin/comfy-panel/.release.lock/owner').read_text().strip() == tx['id'], 'Release lock ownership changed')
backup = root / 'backup/jt-identity.conf'
staged = root / 'stage/jt-identity.conf'
journal = root / 'identity-nginx.json'
owner = root.stat()
lock = open(root / 'identity-nginx-operation.lock', 'a')
os.chmod(lock.name, 0o600)
fcntl.flock(lock, fcntl.LOCK_EX)
sha = lambda data: hashlib.sha256(data).hexdigest()

def write_private(path, data):
    require(path.parent in (root, root / 'backup', root / 'stage'), 'Unexpected transaction write')
    require(not path.exists() and not path.is_symlink(), 'Existing transaction file')
    with open(path, 'xb') as out:
        os.chmod(path, 0o600)
        os.chown(path, owner.st_uid, owner.st_gid)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    sync_dir(path.parent)

def sync_dir(path):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)

def checkpoint(phase, **fields):
    report.update(fields, phase=phase)
    temp = root / 'identity-nginx.json.tmp'
    if temp.exists():
        require(temp.is_file() and not temp.is_symlink(), 'Unsafe checkpoint')
        temp.unlink()
    write_private(temp, (json.dumps(report, sort_keys=True) + '\n').encode())
    os.replace(temp, journal)
    sync_dir(root)

def run(argv, timeout=45):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(result.returncode == 0, 'Command failed: ' + argv[0] + ' ' + ' '.join(argv[1:3]))
    return result.stdout

def snapshots():
    panel = run(['systemctl', 'show', 'comfy-panel', '-p', 'MainPID', '--value']).decode().strip()
    identity = run(['docker', 'inspect', '--format', '{{.Id}} {{.State.Pid}} {{.State.StartedAt}}', 'jt-casdoor']).decode().strip()
    require(panel.isdigit() and int(panel) > 0, 'Workbench is not running')
    require(len(identity.split()) == 3 and int(identity.split()[1]) > 0, 'Identity is not running')
    return {'panel_pid': panel, 'identity_process': identity}

def http(path, status=200):
    require(path.startswith('/') and '?' not in path, 'Invalid probe path')
    result = run(['curl', '--silent', '--show-error', '--max-time', '25',
        '--noproxy', '*', '--resolve', 'auth.dreamapi.club:443:127.0.0.1',
        '--header', 'Cache-Control: no-cache', '--write-out', '\n%{http_code}',
        'https://auth.dreamapi.club' + path], timeout=30)
    body, code = result.rsplit(b'\n', 1)
    require(code == str(status).encode(), 'Unexpected HTTP status at ' + path + ': ' + code.decode())
    return body

def healthy():
    live = json.loads(run(['curl', '--silent', '--show-error', '--fail', '--max-time', '10',
        '--noproxy', '*', 'http://127.0.0.1:8189/api/live']))
    require(live.get('service') == 'comfy-panel', 'Workbench health mismatch')
    identity_health = json.loads(run(['curl', '--silent', '--show-error', '--fail', '--max-time', '10',
        '--noproxy', '*', 'http://127.0.0.1:8010/api/health']))
    require(identity_health.get('status') == 'ok', 'Identity health mismatch')
    require(b'<html' in http('/login/built-in').lower(), 'Identity login HTML missing')
    for path in ('/docs', '/.env', '/assets/.env'):
        http(path, 404)

def install(data, expected_current, metadata):
    require(target.is_file() and not target.is_symlink(), 'Identity target is not a regular file')
    require(sha(target.read_bytes()) == expected_current, 'Concurrent identity config change')
    temp = target.with_name('jt-identity.conf.tx-' + tx['id'])
    require(not temp.exists() and not temp.is_symlink(), 'Existing swap file')
    with open(temp, 'xb') as out:
        os.fchmod(out.fileno(), metadata['mode'])
        os.fchown(out.fileno(), metadata['uid'], metadata['gid'])
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, target)
    sync_dir(target.parent)

def rollback():
    require(backup.is_file() and not backup.is_symlink(), 'Backup missing')
    original = backup.read_bytes()
    require(sha(original) == report['before_sha256'], 'Backup hash mismatch')
    current = sha(target.read_bytes())
    require(current in (report['before_sha256'], report['after_sha256']), 'Concurrent change blocks rollback')
    checkpoint('rolling-back')
    if current != report['before_sha256']:
        install(original, report['after_sha256'], report['metadata'])
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])
    run(['systemctl', 'is-active', '--quiet', 'nginx'])
    require(sha(target.read_bytes()) == report['before_sha256'], 'Rollback hash mismatch')
    require(snapshots() == report['processes'], 'A service restarted during rollback')
    checkpoint('rolled-back', restored_original_bytes=True)

def interrupted(signum, frame):
    raise RuntimeError('Release interrupted by signal')

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGHUP, interrupted)
if payload['action'] == 'recover':
    if not journal.exists():
        # Preflight or backup failed before the first possible live mutation.
        # The flock proves the original process has exited; compare the reviewed
        # hash before allowing the outer release lock to be removed.
        require(not journal.is_symlink(), 'Unsafe journal')
        require(sha(target.read_bytes()) == payload['expected_sha256'], 'No journal and original bytes changed')
        report = {'target': str(target), 'transaction_id': tx['id'],
            'before_sha256': payload['expected_sha256'], 'after_sha256': payload['candidate_sha256'],
            'processes': snapshots(), 'restart_required': False, 'live_config_untouched': True}
        checkpoint('rolled-back')
    else:
        require(journal.is_file() and not journal.is_symlink(), 'Unsafe journal')
        report = json.loads(journal.read_text())
        require(report['target'] == str(target) and report['transaction_id'] == tx['id'], 'Unexpected journal')
        if report['phase'] not in ('committed', 'rolled-back'):
            rollback()
    final_hash = report['after_sha256'] if report['phase'] == 'committed' else report['before_sha256']
    require(sha(target.read_bytes()) == final_hash, 'Terminal journal differs from current configuration')
    print(json.dumps(report, sort_keys=True))
else:
    require(not journal.exists(), 'Transaction already has a journal')
    info = target.lstat()
    require(stat.S_ISREG(info.st_mode), 'Identity target is not a regular file')
    before = target.read_bytes()
    after = base64.b64decode(payload['candidate_b64'], validate=True)
    require(sha(before) == payload['expected_sha256'], 'Reviewed original hash changed')
    require(sha(after) == payload['candidate_sha256'], 'Candidate hash mismatch')
    report = {'target': str(target), 'transaction_id': tx['id'],
        'before_sha256': sha(before), 'after_sha256': sha(after),
        'metadata': {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid},
        'processes': snapshots(), 'restart_required': False, 'backup': str(backup)}
    run(['nginx', '-t'])
    healthy()
    paths = ('/assets/PasswordInput-x4iAHheu.js', '/assets/Obfuscator-CO6TTDW3.js')
    baseline = {path: http(path) for path in paths}
    require(all(body and b'<html' not in body[:200].lower() for body in baseline.values()), 'Invalid module response')
    write_private(backup, before)
    write_private(staged, after)
    checkpoint('prepared')
    swapped = False
    try:
        checkpoint('swapping')
        swapped = True
        install(after, report['before_sha256'], report['metadata'])
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        run(['systemctl', 'is-active', '--quiet', 'nginx'])
        time.sleep(0.5)
        barrier = threading.Barrier(33)
        def probe(index):
            path = paths[index % len(paths)] if index < 32 else '/api/get-account'
            barrier.wait(timeout=20)
            body = http(path)
            if index < 32:
                require(body == baseline[path], 'Static module bytes changed')
            else:
                require(isinstance(json.loads(body), dict), 'Account API did not return JSON')
        with concurrent.futures.ThreadPoolExecutor(max_workers=33) as pool:
            list(pool.map(probe, range(33)))
        healthy()
        require(snapshots() == report['processes'], 'Workbench or identity process changed')
        require(sha(target.read_bytes()) == report['after_sha256'], 'Published bytes changed')
        checkpoint('committed', concurrent_static_requests=32, concurrent_account_request=True,
            static_bytes_unchanged=True, hidden_paths_denied=True, health_ok=True, processes_unchanged=True)
    except BaseException:
        if swapped:
            try:
                rollback()
            except BaseException:
                checkpoint('rollback-failed')
                raise RuntimeError('Identity nginx rollback failed; release lock retained') from None
        raise RuntimeError('Identity nginx release failed and original configuration restored') from None
    print(json.dumps(report, sort_keys=True))
'''


def remote_run(client, payload):
    source = 'payload = ' + repr(payload) + '\n' + REMOTE_PROGRAM
    return json.loads(r.command(client, 'sudo -n python3 -c ' + shlex.quote(source), timeout=240))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-before-sha256')
    parser.add_argument('--recover', action='store_true', help='Resolve this tool\'s existing transaction')
    args = parser.parse_args()
    if args.execute and args.recover:
        parser.error('--execute and --recover are mutually exclusive')
    if args.execute and not re.fullmatch(r'[0-9a-f]{64}', args.expected_before_sha256 or ''):
        parser.error('--execute requires --expected-before-sha256 from the reviewed plan')
    client = t._connect(t.BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
    locked = False
    report = None
    tx = None
    try:
        if args.recover:
            state = json.loads(STATE.read_text(encoding='utf-8'))
            tx = state['transaction']
            locked = True
            report = remote_run(client, {'action': 'recover', 'transaction': tx,
                'expected_sha256': state['before_sha256'], 'candidate_sha256': state['after_sha256']})
        else:
            with client.open_sftp() as sftp:
                with sftp.open(TARGET, 'rb') as handle:
                    before = handle.read()
            after = candidate_from_live(before)
            template = TEMPLATE.read_bytes().replace(b'\r\n', b'\n')
            if template.count(BLOCK) != 1 or template.count(ZONE) != 1:
                raise RuntimeError('Local template does not match the reviewed insertion')
            print(json.dumps({'target': TARGET, 'before_sha256': digest(before),
                'after_sha256': digest(after), 'static_connection_limit': 60,
                'dynamic_connection_limit': 20, 'request_rates_unchanged': True,
                'restart_required': False, 'read_only_plan': not args.execute}), flush=True)
            if not args.execute:
                return
            if digest(before) != args.expected_before_sha256:
                raise RuntimeError('Reviewed production configuration changed')
            if STATE.exists():
                raise RuntimeError('Existing release state; inspect it or use --recover')
            tx = r.new_release_transaction()
            r.acquire_release_lock(client, tx)
            locked = True
            try:
                t._atomic_json(STATE, {'transaction': tx, 'phase': 'preparing',
                    'before_sha256': digest(before), 'after_sha256': digest(after)})
            except BaseException:
                r.release_release_lock(client, tx)
                locked = False
                raise
            payload = {'action': 'execute', 'transaction': tx,
                'expected_sha256': digest(before), 'candidate_sha256': digest(after),
                'candidate_b64': base64.b64encode(after).decode('ascii')}
            try:
                report = remote_run(client, payload)
            except BaseException:
                # Wait on the same remote flock if the original process survived
                # a transport loss; its durable journal decides commit/rollback.
                client.close()
                client = t._connect(t.BASE / 'tools/creds.json', r.DEPLOY_SSH_KEY_PATH)
                report = remote_run(client, {'action': 'recover', 'transaction': tx,
                    'expected_sha256': digest(before), 'candidate_sha256': digest(after)})
        t._atomic_json(STATE, {'transaction': tx, **report, 'lock_released': False})
        if report['phase'] not in ('committed', 'rolled-back'):
            raise RuntimeError('Nonterminal identity release; lock retained')
        r.write_transaction_phase(client, tx, report['phase'])
        r.release_release_lock(client, tx)
        locked = False
        t._atomic_json(STATE, {'transaction': tx, **report, 'lock_released': True})
        print(json.dumps({'phase': report['phase'], 'lock_released': True,
            'before_sha256': report['before_sha256'], 'after_sha256': report['after_sha256'],
            'processes_unchanged': report.get('processes_unchanged', False)}), flush=True)
        if report['phase'] != 'committed':
            raise RuntimeError('Identity release rolled back; original configuration restored')
    finally:
        if locked:
            print('IDENTITY_RELEASE_LOCK_RETAINED: inspect state and run --recover', flush=True)
        client.close()


if __name__ == '__main__':
    main()
