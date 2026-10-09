#!/usr/bin/env python3
"""Add only auth.dreamapi.club to nginx and obtain its TLS certificate.

Run on the server as root, after the loopback Casdoor bootstrap is sealed.
This script never restarts or configures the JT workbench service.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

ROOT = Path('/opt/jt-identity')
LIVE = Path('/etc/nginx/conf.d/jt-identity.conf')
MARKER = '# JT managed identity host\n'


def run(*args):
    result=subprocess.run(args,check=True,text=True,capture_output=True)
    return result.stdout


def write(path,text):
    temporary=path.with_suffix(path.suffix+'.tmp')
    with open(temporary,'w',encoding='utf-8') as handle:
        handle.write(text);handle.flush();os.fsync(handle.fileno())
    os.chmod(temporary,0o644)
    os.replace(temporary,path)


def replace_nginx(text):
    previous=LIVE.read_text() if LIVE.exists() else None
    if previous is not None and not previous.startswith(MARKER):
        raise RuntimeError('Existing nginx host is not owned by this installer')
    write(LIVE,MARKER+text)
    try:
        run('nginx','-t')
        run('systemctl','reload','nginx')
    except Exception:
        if previous is None: LIVE.unlink()
        else:write(LIVE,previous)
        run('nginx','-t')
        run('systemctl','reload','nginx')
        raise


def snapshots():
    files={}
    for directory in ['/etc/nginx/conf.d','/etc/nginx/sites-enabled']:
        for path in Path(directory).iterdir():
            if path==LIVE or not path.is_file():continue
            files[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'nginx_other_hosts':files,'workbench_unit':run('systemctl','show','comfy-panel','-p','MainPID','-p','ActiveEnterTimestampMonotonic')}


def main():
    if os.geteuid()!=0:raise RuntimeError('Run as root')
    state=json.loads((ROOT/'state.json').read_text())
    if state.get('phase')!='sealed':raise RuntimeError('Identity bootstrap must be sealed before publication')
    if state.get('issuer')!='auth.dreamapi.club':raise RuntimeError('Unexpected issuer host')
    if socket.gethostbyname('auth.dreamapi.club')!='8.210.125.65':raise RuntimeError('Identity DNS not ready')
    before=snapshots()
    run('docker','compose','-f',str(ROOT/'compose.yaml'),'restart','casdoor')
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8010/api/health',timeout=5) as response:
                if json.load(response).get('status')=='ok':break
        except Exception:
            if attempt==19:raise
        time.sleep(2)
    Path('/var/www/jt-identity-acme').mkdir(mode=0o755,exist_ok=True)
    certificate=Path('/etc/letsencrypt/live/auth.dreamapi.club/fullchain.pem')
    if not certificate.exists():
        replace_nginx('''server {
    listen 80;
    server_name auth.dreamapi.club;
    location ^~ /.well-known/acme-challenge/ { root /var/www/jt-identity-acme; }
    location / { return 404; }
}
''')
        run('certbot','certonly','--webroot','-w','/var/www/jt-identity-acme','-d','auth.dreamapi.club',
            '--non-interactive','--agree-tos')
    template=ROOT/'nginx/jt-identity.nginx.conf'
    replace_nginx(template.read_text())
    after=snapshots()
    if before!=after:raise RuntimeError('Unrelated nginx hosts or workbench service changed during identity publication')
    # Graceful nginx reload returns before every worker has adopted the new SNI host.
    for attempt in range(10):
        try:
            with urllib.request.urlopen('https://auth.dreamapi.club/.well-known/openid-configuration',timeout=20) as response:
                discovery=json.load(response)
            break
        except Exception:
            if attempt==9:raise
            time.sleep(1)
    if discovery.get('issuer')!='https://auth.dreamapi.club':raise RuntimeError('OIDC issuer does not match the public TLS hostname')
    audit={'identity_origin':discovery['issuer'],'phase':'identity_https_ready','other_hosts_unchanged':True,
           'workbench_unchanged':True,'workbench_unit':after['workbench_unit'],
           'certificate':run('openssl','x509','-in',str(certificate),'-noout','-dates','-fingerprint','-sha256'),
           'oidc_endpoints':{k:discovery.get(k) for k in ['authorization_endpoint','token_endpoint','jwks_uri']}}
    write(ROOT/'https-audit.json',json.dumps(audit,indent=2)+'\n')
    os.chmod(ROOT/'https-audit.json',0o600)
    print(json.dumps(audit))


if __name__=='__main__':main()
