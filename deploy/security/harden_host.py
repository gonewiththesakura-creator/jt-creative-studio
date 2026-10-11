"""Scoped, reversible hardening for the existing JT service (run as root).

Never replaces ledgers or changes other applications' firewall/listener rules.
Prepare before drain; apply only while comfy-panel is stopped. Backups stay 0600.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import shlex
import shutil
import subprocess

ROOT = Path('/home/admin/comfy-panel')
DATA = ROOT / 'panel_data'
STATE = Path('/var/lib/jt-security-hardening-20261011')
UNIT = Path('/etc/systemd/system/comfy-panel.service')
DROPIN = Path('/etc/systemd/system/comfy-panel.service.d/zzzz-security.conf')
ENV = Path('/etc/comfy-panel/security.env')
SSH = Path('/etc/ssh/sshd_config.d/00-jt-key-auth.conf')
ACCOUNT = 'jt-panel'
HARDENING = f'''[Service]
User={ACCOUNT}
Group={ACCOUNT}
EnvironmentFile={ENV}
Environment=PYTHONDONTWRITEBYTECODE=1
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={DATA}
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UMask=0077
'''
SSH_CONFIG = '''# Host has only admin/root interactive accounts; preserve key/tunnel access.
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
'''


def run(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if p.returncode:
        # Commands/config output may contain credentials. Never include it.
        raise RuntimeError('Host operation failed: ' + Path(args[0]).name)
    return p.stdout.strip()


def write(path, raw, mode=0o600):
    raw = raw.encode() if isinstance(raw, str) else raw
    temp = path.with_name(path.name + '.security-tmp')
    with temp.open('wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, mode)
    os.replace(temp, path)


def prepare():
    if STATE.exists():
        raise RuntimeError('Hardening state already exists; inspect before retry')
    interactive = {p.pw_name for p in pwd.getpwall() if Path(p.pw_shell).name not in ('nologin','false','sync')}
    assert interactive == {'admin','root'}, 'Unexpected interactive SSH accounts; review before applying key-only auth'
    if not shutil.which('setfacl'):
        run('apt-get', 'install', '-y', '--no-install-recommends', 'acl')
    try:
        pwd.getpwnam(ACCOUNT)
        raise RuntimeError('Service account already exists; inspect before reuse')
    except KeyError:
        pass
    run('useradd', '--system', '--user-group', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', ACCOUNT)
    STATE.mkdir(mode=0o700)
    saved = {}
    for p in (UNIT, DROPIN, ENV, SSH):
        if p.is_symlink():
            raise RuntimeError('Refused symlink configuration')
        saved[str(p)] = {'exists': p.exists(), 'mode': p.stat().st_mode & 0o777 if p.exists() else None}
        if p.exists():
            write(STATE / (p.name + '.before'), p.read_bytes())
    write(STATE/'before.json', json.dumps(saved))
    write(STATE/'home-acl.before', run('getfacl', '-p', str(ROOT.parent))+'\n')
    # No credentials are logged or sent back to the workstation.
    write(STATE/'new-security.env', 'PANEL_TOKEN='+secrets.token_urlsafe(48)+'\nPANEL_SESSION_SECRET='+secrets.token_urlsafe(48)+'\n')
    write(STATE/'prepared', '1\n')
    return {'prepared': True, 'service_account': ACCOUNT, 'backup': str(STATE)}


def apply():
    assert (STATE/'prepared').exists()
    assert run('systemctl', 'show', 'comfy-panel', '-p', 'ActiveState', '--value') == 'inactive', 'Stop the drained service first'
    assert DATA.resolve() == DATA and not any(p.is_symlink() for p in DATA.rglob('*'))
    write(STATE/'data-acl.before', run('getfacl', '-p', '-R', str(DATA))+'\n')
    current = UNIT.read_bytes()
    assert current == (STATE/(UNIT.name+'.before')).read_bytes(), 'Concurrent unit edit'
    lines = []
    for line in current.decode().splitlines():
        if line.startswith('Environment='):
            values = shlex.split(line.split('=', 1)[1])
            values = [v for v in values if v.split('=', 1)[0] not in ('PANEL_TOKEN', 'PANEL_SESSION_SECRET')]
            if values:
                lines.append('Environment='+' '.join('"'+v.replace('\\','\\\\').replace('"','\\"')+'"' for v in values))
        else:
            lines.append(line)
    # Named ACL grants traversal of the home only, not directory listing.
    run('setfacl', '-m', 'u:'+ACCOUNT+':--x', str(ROOT.parent))
    run('setfacl', '-R', '-m', 'u:'+ACCOUNT+':rwX', str(DATA))
    # SQLite creates WAL/SHM sidecars with the database owner's identity. A
    # root read can otherwise recreate admin-owned sidecars without our ACL.
    service = pwd.getpwnam(ACCOUNT)
    for name in ('membership.sqlite3','membership.sqlite3-wal','membership.sqlite3-shm'):
        path = DATA/name
        if path.exists():
            os.chown(path,service.pw_uid,service.pw_gid)
    # Data remains in place, with the original ownership and absolute paths.
    write(ENV, (STATE/'new-security.env').read_bytes())
    write(UNIT, '\n'.join(lines)+'\n', 0o644)
    write(DROPIN, HARDENING, 0o644)
    write(SSH, SSH_CONFIG, 0o644)
    run('/usr/sbin/sshd', '-t')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'reload', 'ssh')
    write(STATE/'applied', '1\n')
    return {'applied': True, 'requires_start_and_live_verification': True}


def verify():
    account = pwd.getpwnam(ACCOUNT)
    pid = run('systemctl', 'show', 'comfy-panel', '-p', 'MainPID', '--value')
    status = dict(line.split(':', 1) for line in Path('/proc/'+pid+'/status').read_text().splitlines())
    assert status['Uid'].split()[0] == str(account.pw_uid)
    assert status['NoNewPrivs'].strip() == '1' and int(status['CapEff'].strip(), 16) == 0
    environment = shlex.split(run('systemctl','show','comfy-panel','-p','Environment','--value'))
    assert not any(v.startswith(('PANEL_TOKEN=', 'PANEL_SESSION_SECRET=')) for v in environment)
    assert ENV.stat().st_mode & 0o077 == 0
    assert run('id', '-Gn', ACCOUNT).split() == [ACCOUNT]
    denied = subprocess.run(['runuser','-u',ACCOUNT,'--','sudo','-n','true'],capture_output=True).returncode != 0
    assert denied
    assert (DATA/'membership.sqlite3').stat().st_uid == account.pw_uid
    for user in ('admin','root'):
        effective = dict(row.split(' ',1) for row in run('/usr/sbin/sshd','-T','-C','user='+user+',host=localhost,addr=127.0.0.1').splitlines())
        assert effective['passwordauthentication'] == 'no' and effective['authenticationmethods'] == 'publickey'
    # Same mount namespace and identity as the app: real access checks, no writes.
    test = "import os,json;print(json.dumps({p:os.access(p,os.W_OK) for p in %r}))" % [str(ROOT/'server.py'), '/etc/passwd', str(DATA)]
    writable = json.loads(run('nsenter','-t',pid,'-m','--','runuser','-u',ACCOUNT,'--','/usr/bin/python3','-c',test))
    assert writable == {str(ROOT/'server.py'):False, '/etc/passwd':False, str(DATA):True}
    return {'service_unprivileged':True,'no_sudo':True,'no_new_privileges':True,'no_capabilities':True,
            'runtime_code_readonly':True,'data_writable':True,'inline_secrets_removed':True,
            'separate_session_secret':True,'maintenance_password_login_disabled':True,'pid':int(pid)}


def rollback():
    saved = json.loads((STATE/'before.json').read_text())
    for raw, info in saved.items():
        path = Path(raw)
        if info['exists']:
            write(path,(STATE/(path.name+'.before')).read_bytes(),info['mode'])
        elif path.exists():
            path.unlink()
    run('setfacl','--restore='+str(STATE/'home-acl.before'))
    # Maintenance may have removed staged chunks between snapshot and rollback.
    # Revoke this isolated account's named ACL on surviving paths, then restore
    # only backed-up entries whose paths still exist. New files retain their ACL.
    if (STATE/'data-acl.before').exists():
        import re
        raw = (STATE/'data-acl.before').read_text()
        blocks = []
        for block in raw.split('\n\n'):
            header = next((line[8:] for line in block.splitlines() if line.startswith('# file: ')), None)
            if header is None:
                continue
            decoded = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match.group(1),8)), header)
            path = Path(decoded)
            assert path == DATA or DATA in path.parents
            if path.exists() and not path.is_symlink():
                blocks.append(block)
        write(STATE/'data-acl.rollback', '\n\n'.join(blocks)+'\n')
        run('setfacl','--restore='+str(STATE/'data-acl.rollback'))
    panel_uid = pwd.getpwnam(ACCOUNT).pw_uid
    admin = pwd.getpwnam('admin')
    for path in DATA.rglob('*'):
        if not path.is_symlink() and path.stat().st_uid == panel_uid:
            os.chown(path, admin.pw_uid, admin.pw_gid)
    run('/usr/sbin/sshd','-t')
    run('systemctl','daemon-reload')
    run('systemctl','reload','ssh')
    return {'host_settings_rolled_back':True,'production_data_not_replaced':True}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','apply','verify','rollback'))
    args=parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    print(json.dumps(globals()[args.action]()))
