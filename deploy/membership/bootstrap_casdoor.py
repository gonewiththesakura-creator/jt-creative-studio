#!/usr/bin/env python3
"""Prepare a fresh, loopback-only Casdoor installation; never alter the JT service.

Run as root on Linux. Secrets remain in root-readable files, never stdout.
After first healthy startup, `seal` validates the database and disables bootstrap.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import uuid

ROOT = Path('/opt/jt-identity')
VERSION = 'v4.18.0'
IMAGE = 'casbin/casdoor:4.18.0@sha256:30c176f544bc2a24391a44d85c174e6647f79c85652df59d786f0a10d9225c9b'


def write(path, text, mode=0o600, uid=0):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temporary, uid, uid)
    os.replace(temporary, path)


def domain(value):
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', value):
        raise ValueError('Expected a plain DNS hostname')
    return value


def app_config(issuer, sealed=False):
    return f'''appname = casdoor
httpport = 8000
runmode = prod
copyrequestbody = true
driverName = sqlite
dataSourceName = file:/data/casdoor.db?cache=shared
dbName = casdoor
showSql = false
origin = https://{issuer}
originFrontend = https://{issuer}
isDemoMode = false
showGithubCorner = false
defaultApplication = jt-workbench
defaultLanguage = zh
forceLanguage = zh
enableErrorMask = true
enableGzip = true
initDataNewOnly = false
initDataMerge = false
initDataFile = {'""' if sealed else '"/conf/init_data.json"'}
initDataWatchInterval = 0
inactiveTimeoutMinutes = 30
logPostOnly = true
logConfig = {{"adapter":"file","filename":"/logs/casdoor.log","maxdays":14,"perm":"0600"}}
'''


def generate_data(site, issuer, credentials, certificate, private_key):
    def organization(name, application):
        return {'owner':'admin', 'name':name, 'displayName':'JT 账户管理' if name=='built-in' else 'JT 创作台',
                'websiteUrl':'https://'+site, 'favicon':'https://'+site+'/static/favicon.png',
                'passwordType':'bcrypt', 'passwordOptions':['AtLeast8','Aa123','SpecialChar'],
                'countryCodes':['CN'], 'languages':['zh'], 'isProfilePublic':False,
                'defaultApplication':application, 'defaultTokenFormat':'JWT-Standard', 'defaultTokenFields':[],
                'hasPrivilegeConsent':False, 'dcrPolicy':'disabled', 'initScore':0,
                'masterPassword':'', 'defaultPassword':'', 'masterVerificationCode':'',
                'tokenRetentionDays':7, 'recordRetentionDays':30, 'maxSessions':5}
    def application(name, org, client_id, client_secret, signup):
        return {'owner':'admin', 'name':name, 'displayName':'JT 创作台' if signup else 'JT 账户管理',
                'organization':org, 'homepageUrl':'https://'+site, 'logo':'https://'+site+'/static/favicon.png',
                'cert':'cert-jt', 'clientId':client_id, 'clientSecret':client_secret,
                'enablePassword':True, 'enableSignUp':signup, 'disableSignin':False,
                'grantTypes':['authorization_code'], 'redirectUris':['https://'+site+'/api/auth/callback','https://'+site+'/'] if signup else [],
                'tokenFormat':'JWT-Standard', 'tokenSigningMethod':'RS256', 'tokenFields':[],
                'expireInHours':1, 'cookieExpireInHours':8, 'failedSigninLimit':5, 'failedSigninFrozenTime':15,
                'signinMethods':[{'name':'Password','displayName':'密码','rule':'All'}],
                'providers':[{'name':'provider_captcha_default','canSignUp':False,'canSignIn':False,'canUnlink':False,'prompted':False,'rule':'None'}],
                'signupItems':[{'name':n,'visible':n!='ID','required':True,'prompted':False,'rule':'Random' if n=='ID' else 'None'}
                               for n in ['ID','Username','Display name','Password','Confirm password']],
                'tags':[], 'isShared':False}
    return {'organizations':[organization('built-in','app-built-in'),organization('jt-users','jt-workbench')],
            'applications':[application('app-built-in','built-in',credentials['admin_client_id'],credentials['admin_client_secret'],False),
                            application('jt-workbench','jt-users',credentials['client_id'],credentials['client_secret'],True)],
            'users':[{'owner':'built-in','name':'admin','displayName':'JT 管理员','type':'normal-user','isAdmin':True,
                      'password':credentials['identity_admin_password'],'passwordType':'plain','signupApplication':'app-built-in'},
                     {'owner':'jt-users','name':'owner','displayName':'工作台管理员','type':'normal-user','isAdmin':False,
                      'password':credentials['workbench_owner_password'],'passwordType':'plain','signupApplication':'jt-workbench'}],
            'certs':[{'owner':'admin','name':'cert-jt','displayName':'JT Identity Signing Certificate','scope':'JWT','type':'x509',
                      'cryptoAlgorithm':'RS256','bitSize':4096,'expireInYears':2,'certificate':certificate,'privateKey':private_key}]}


def prepare(site, issuer):
    if ROOT.exists():
        raise RuntimeError('Refusing to overwrite an existing identity installation')
    ROOT.mkdir(mode=0o700)
    for name in ['conf','data','logs','files','nginx']:
        directory=ROOT/name
        directory.mkdir(mode=0o700)
        if name!='nginx':os.chown(directory,1000,1000)
    credentials={'client_id':'jt-'+secrets.token_hex(12),'client_secret':secrets.token_urlsafe(48),
                 'admin_client_id':secrets.token_hex(24),'admin_client_secret':secrets.token_urlsafe(48),
                 'identity_admin_username':'admin','identity_admin_password':'Jt!9'+secrets.token_urlsafe(32),
                 'workbench_owner_username':'owner','workbench_owner_password':'Jt!9'+secrets.token_urlsafe(32),
                 'public_origin':'https://'+site,'issuer':'https://'+issuer}
    key_path=ROOT/'signing-key.pem'
    cert_path=ROOT/'signing-cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:4096','-nodes','-sha256','-days','730',
                    '-subj','/CN=JT Identity Signing','-keyout',str(key_path),'-out',str(cert_path)],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    os.chmod(key_path,0o600)
    os.chmod(cert_path,0o600)
    data=generate_data(site,issuer,credentials,cert_path.read_text(),key_path.read_text())
    write(ROOT/'conf/init_data.json',json.dumps(data,ensure_ascii=False,indent=2)+'\n',0o400,1000)
    write(ROOT/'conf/app.conf',app_config(issuer),0o400,1000)
    write(ROOT/'bootstrap-credentials.json',json.dumps(credentials,ensure_ascii=False,indent=2)+'\n')
    write(ROOT/'panel-membership.env','\n'.join([
        'JT_MEMBERSHIP_ENABLED=1','JT_PUBLIC_ORIGIN=https://'+site,'JT_OIDC_ISSUER=https://'+issuer,
        'JT_OIDC_CLIENT_ID='+credentials['client_id'],'JT_OIDC_CLIENT_SECRET='+credentials['client_secret'],
        'JT_OIDC_REDIRECT_URI=https://'+site+'/api/auth/callback','JT_OIDC_ORGANIZATION=jt-users',
        'PANEL_BIND=127.0.0.1','']) )
    write(ROOT/'compose.yaml',f'''name: jt-identity
services:
  casdoor:
    image: {IMAGE}
    container_name: jt-casdoor
    restart: unless-stopped
    user: "1000:1000"
    ports:
      - "127.0.0.1:8010:8000"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    pids_limit: 160
    mem_limit: 512m
    cpus: 1.0
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m,uid=1000,gid=1000
    volumes:
      - ./conf:/conf:ro
      - ./data:/data
      - ./logs:/logs
      - ./files:/files
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
''')
    write(ROOT/'state.json',json.dumps({'phase':'prepared','version':VERSION,'site':site,'issuer':issuer},indent=2)+'\n')
    print(json.dumps({'phase':'prepared','root':str(ROOT),'site':site,'issuer':issuer,'secrets_printed':False}))


def seal():
    import bcrypt
    state=json.loads((ROOT/'state.json').read_text())
    if state['phase']=='sealed':
        print(json.dumps({'phase':'sealed','already_sealed':True}));return
    with sqlite3.connect('file:'+str(ROOT/'data/casdoor.db')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        owner=dict(db.execute('SELECT id, owner, name, is_admin, password_type FROM user WHERE owner=? AND name=?',('jt-users','owner')).fetchone() or {})
        admin=dict(db.execute('SELECT id, password, password_type FROM user WHERE owner=? AND name=?',('built-in','admin')).fetchone() or {})
        app=dict(db.execute('SELECT enable_sign_up, redirect_uris, grant_types FROM application WHERE owner=? AND name=?',('admin','jt-workbench')).fetchone() or {})
        builtin=dict(db.execute('SELECT enable_sign_up FROM application WHERE owner=? AND name=?',('admin','app-built-in')).fetchone() or {})
        if not owner.get('id') or owner.get('is_admin') or owner.get('password_type')!='bcrypt':
            raise RuntimeError('Workbench owner bootstrap validation failed')
        if not admin.get('password','').startswith('$2') or admin.get('password_type')!='bcrypt':
            raise RuntimeError('Identity administrator bootstrap validation failed')
        credentials=json.loads((ROOT/'bootstrap-credentials.json').read_text())
        if (not bcrypt.checkpw(credentials['identity_admin_password'].encode(),admin['password'].encode())
                or bcrypt.checkpw(b'123',admin['password'].encode())):
            raise RuntimeError('Identity administrator password did not replace the default')
        if builtin.get('enable_sign_up') or not app.get('enable_sign_up'):
            raise RuntimeError('Application signup policies differ from the approved bootstrap')
        expected_redirects=['https://'+state['site']+'/api/auth/callback','https://'+state['site']+'/']
        if json.loads(app['grant_types'])!=['authorization_code'] or json.loads(app['redirect_uris'])!=expected_redirects:
            raise RuntimeError('OAuth grant/redirect whitelist mismatch')
    state.update(phase='sealed',owner_subject=owner['id'],owner_issuer='https://'+state['issuer'])
    write(ROOT/'conf/app.conf',app_config(state['issuer'],sealed=True),0o400,1000)
    write(ROOT/'state.json',json.dumps(state,indent=2)+'\n')
    print(json.dumps({'phase':'sealed','owner_subject':owner['id'],'owner_issuer':state['owner_issuer'],'restart_identity_required':True}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','seal'])
    parser.add_argument('--site',type=domain,default='studio.dreamapi.club')
    parser.add_argument('--issuer',type=domain,default='auth.dreamapi.club')
    args=parser.parse_args()
    if os.name!='posix' or os.geteuid()!=0:raise RuntimeError('Run on Linux as root; this utility never prints secrets')
    if args.site==args.issuer:raise ValueError('Casdoor requires a separate hostname')
    os.umask(0o077)
    prepare(args.site,args.issuer) if args.action=='prepare' else seal()


if __name__=='__main__':main()
