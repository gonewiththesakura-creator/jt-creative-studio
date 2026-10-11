#!/usr/bin/env python3
"""Enable the already-published membership code without copying any local ledger.

Default preflight is read-only. --execute drains naturally, takes the existing
release lock, stops the service, runs server-local backed-up owner migration,
installs only this service's drop-in and its new nginx host, then verifies before
admitting work. On failure, restore the migration snapshot and remove only this
transaction's newly-created configuration. Never submit or cancel provider jobs.
"""
import argparse
import hashlib
import json
import shlex
import time
import prepare_dreamapi_native_canary as t

r=t.release
REMOTE='/home/admin/comfy-panel'
DATA=REMOTE+'/panel_data'
VENV=REMOTE+'/.venv-membership/bin/python'
DROPIN='/etc/systemd/system/comfy-panel.service.d/zz-membership.conf'
NGINX='/etc/nginx/conf.d/jt-workbench.conf'
PUBLIC='https://studio.dreamapi.club'
DEFAULT_STATE=t.BASE/'audit/membership-cutover-20261009/release.json'
RUNTIME_FILES=('server.py','membership_store.py','membership_auth.py','membership_http.py','membership_media.py','tools/migrate_membership_owner.py')
DROPIN_TEXT='''# JT managed membership cutover
[Service]
EnvironmentFile=/opt/jt-identity/panel-membership.env
ExecStart=
ExecStart=/home/admin/comfy-panel/.venv-membership/bin/python /home/admin/comfy-panel/server.py
UMask=0077
'''


def remote_json(client,source,root=False):
    return json.loads(r.command(client,('sudo ' if root else '')+'python3 -c '+shlex.quote(source)))


def queue(client):
    return remote_json(client,f'''import json,pathlib
j=json.loads(pathlib.Path({DATA+'/jobs.json'!r}).read_text())
print(json.dumps({{'active':[v['id'] for v in j.values() if v.get('status') in ('running','recovering') or v.get('queue_hold')],
                  'waiting':[v['id'] for v in j.values() if v.get('status')=='queued']}}))
''', root=True)


def preflight(client):
    source=f'''import hashlib,json,pathlib,subprocess,urllib.request
root=pathlib.Path({REMOTE!r})
state=json.loads(pathlib.Path('/opt/jt-identity/state.json').read_text())
assert state['phase']=='sealed' and state['owner_issuer']=='https://auth.dreamapi.club'
assert state.get('owner_subject')
for target in [{DROPIN!r},{NGINX!r}]:
 assert not pathlib.Path(target).exists(), 'Cutover target already exists; use its saved transaction for recovery'
assert pathlib.Path('/opt/jt-identity/panel-membership.env').stat().st_mode & 0o077 == 0
with urllib.request.urlopen('https://auth.dreamapi.club/.well-known/openid-configuration',timeout=20) as response:
 assert json.load(response)['issuer']==state['owner_issuer']
deps=subprocess.check_output([{VENV!r},'-c','import jwt,cryptography;print(jwt.__version__+"/"+cryptography.__version__)'],text=True).strip()
assert deps=='2.15.1/50.0.1', 'Membership dependency versions differ'
files={{p:hashlib.sha256((root/p).read_bytes().replace(b'\\r\\n',b'\\n')).hexdigest() for p in {RUNTIME_FILES!r}}}
print(json.dumps({{'identity_ready':True,'owner_subject':state['owner_subject'],'owner_issuer':state['owner_issuer'],'dependencies':deps,'runtime_sha256':files}}))
'''
    result=remote_json(client,source,root=True)
    for path in RUNTIME_FILES:
        expected=hashlib.sha256((t.BASE/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if result['runtime_sha256'][path]!=expected:raise RuntimeError('Publish reviewed runtime before cutover: '+path)
    r.require_persistent_release_drain_contract(client)
    r.require_release_start_draining_unset(client)
    return result


def migrate(client,apply=False):
    code=f'''import json,sys
sys.path.insert(0,{REMOTE!r});sys.path.insert(0,{REMOTE+'/tools'!r})
from migrate_membership_owner import migrate
from pathlib import Path
state=json.loads(Path('/opt/jt-identity/state.json').read_text())
print(json.dumps(migrate({DATA!r},state['owner_issuer'],state['owner_subject'],apply={apply!r})))
'''
    return remote_json(client,code,root=True)


def verify(client,transaction):
    code=f'''import json,pathlib,subprocess,urllib.request,urllib.error
origin={PUBLIC!r}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None
opener=urllib.request.build_opener(NoRedirect())
def get(path):
 try:
  with opener.open(origin+path,timeout=15) as response:return response.status,response.read()
 except urllib.error.HTTPError as error:return error.code,error.read()
status,body=get('/api/auth/me');me=json.loads(body)
assert status==200 and me.get('enabled') is True and me.get('authenticated') is False
assert get('/api/jobs')[0]==401, 'Anonymous jobs were not denied'
assert get('/api/admin/release-drain')[0]==404, 'Public release management is exposed'
assert get('/api/auth/login')[0]==302, 'Login redirect unavailable'
pid=subprocess.check_output(['systemctl','show','comfy-panel','-p','MainPID','--value'],text=True).strip()
env=dict(item.split('=',1) for item in pathlib.Path('/proc/'+pid+'/environ').read_bytes().decode().split('\\0') if '=' in item)
assert env.get('PANEL_BIND')=='127.0.0.1' and env.get('JT_MEMBERSHIP_ENABLED')=='1'
before=json.loads(pathlib.Path({transaction['root']+'/jobs-before-membership.json'!r}).read_text())
after=json.loads(pathlib.Path({DATA+'/jobs.json'!r}).read_text())
allowed={{'request_session_hash','quota_session_hash','owner_user_id'}}
strip=lambda value:{{k:v for k,v in value.items() if k not in allowed}}
assert set(before)==set(after), 'Job set changed while draining'
assert all(strip(before[k])==strip(after[k]) for k in before), 'Job contents changed beyond ownership'
assert all(v.get('owner_user_id') for v in after.values()), 'A job was not assigned to the original owner'
print(json.dumps({{'anonymous_denied':True,'release_management_hidden':True,'login_ready':True,'backend_loopback':True,
                  'jobs_preserved':len(after),'queued_preserved':sum(v.get('status')=='queued' for v in after.values())}}))
'''
    # Give nginx's graceful reload time to replace workers without weakening TLS.
    last=None
    for attempt in range(5):
        try:return remote_json(client,code,root=True)
        except Exception as error:
            last=error
            if attempt<4:time.sleep(2)
    raise last


def rollback(client,transaction,migration_started):
    r.stop_panel_resilient(client)
    code=f'''import json,pathlib,sys
sys.path.insert(0,{REMOTE!r});sys.path.insert(0,{REMOTE+'/tools'!r})
from migrate_membership_owner import restore_backup,atomic_json
directory=pathlib.Path({DATA!r});marker=directory/'membership-owner-migration.json'
if {migration_started!r} and marker.exists():
 data=json.loads(marker.read_text())
 if data.get('phase') in ('committed','committing'):
  restore_backup(directory,directory/'membership-owner-backups'/data['backup'])
  data['phase']='rolled_back';atomic_json(marker,data,directory.stat())
for target in [{DROPIN!r},{NGINX!r}]:
 path=pathlib.Path(target)
 if path.exists():
  assert path.read_text().startswith('# JT managed'), 'Refusing to remove unowned configuration'
  path.unlink()
print(json.dumps({{'rollback_files_restored':True}}))
'''
    remote_json(client,code,root=True)
    r.command(client,'sudo systemctl daemon-reload')
    r.command(client,'sudo nginx -t')
    r.command(client,'sudo systemctl reload nginx')
    r.command(client,'sudo systemctl start comfy-panel',timeout=60)
    r.wait_for_loopback_live(client)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--state',type=str,default=str(DEFAULT_STATE))
    args=parser.parse_args(argv)
    client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
    checked=preflight(client)
    if not args.execute:
        print(json.dumps({'preflight':checked,'migration':migrate(client),'queue':queue(client)}));client.close();return
    state_path=t.BASE/args.state
    if state_path.exists():raise RuntimeError('Audit state already exists; inspect before another cutover')
    transaction=r.new_release_transaction();r.acquire_release_lock(client,transaction)
    state={'phase':'preparing','transaction':transaction,'watchdog':r.capture_watchdog_state(client),'preflight':checked}
    t._atomic_json(state_path,state)
    admission=isolated=migration_started=configured=stopped=False
    try:
        sftp=client.open_sftp()
        t._upload(sftp,transaction['stage_root']+'/membership.conf',DROPIN_TEXT.encode())
        nginx=(t.BASE/'deploy/membership/jt-workbench.nginx.conf').read_bytes()
        if not nginx.startswith(b'# JT managed'):nginx=b'# JT managed workbench host\n'+nginx
        t._upload(sftp,transaction['stage_root']+'/jt-workbench.conf',nginx)
        sftp.close()
        r.write_transaction_phase(client,transaction,'prepared')
        admission=True;r.set_release_start_draining(client,True);r.set_remote_release_drain(client,True)
        deadline=time.time()+900
        while True:
            current=queue(client)
            print(json.dumps({'phase':'draining','active':len(current['active']),'waiting':len(current['waiting'])}),flush=True)
            if not current['active']:break
            if time.time()>deadline:raise RuntimeError('Existing active work did not finish; no tasks cancelled')
            time.sleep(15)
        client.close();client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
        isolated=True;r.isolate_watchdog(client)
        if queue(client)['active']:raise RuntimeError('Active work changed before offline migration')
        stopped=True;r.stop_panel_resilient(client)
        r.command(client,'cp -- '+shlex.quote(DATA+'/jobs.json')+' '+shlex.quote(transaction['root']+'/jobs-before-membership.json'))
        r.fsync_remote_file(client,transaction['root']+'/jobs-before-membership.json')
        r.write_transaction_phase(client,transaction,'swapping')
        migration_started=True;state['migration']=migrate(client,apply=True)
        state['phase']='migrated';t._atomic_json(state_path,state)
        configured=True
        r.command(client,'sudo install -m 644 '+shlex.quote(transaction['stage_root']+'/membership.conf')+' '+shlex.quote(DROPIN))
        r.command(client,'sudo install -m 644 '+shlex.quote(transaction['stage_root']+'/jt-workbench.conf')+' '+shlex.quote(NGINX))
        r.command(client,'sudo systemctl daemon-reload')
        r.command(client,'sudo nginx -t')
        r.command(client,'sudo systemctl reload nginx')
        r.command(client,'sudo systemctl start comfy-panel',timeout=60)
        r.wait_for_loopback_live(client)
        r.set_remote_release_drain(client,True,require_start_draining=True)
        state['verification']=verify(client,transaction)
        r.write_transaction_phase(client,transaction,'committed')
        state['phase']='committed';t._atomic_json(state_path,state)
    except BaseException:
        if stopped or migration_started or configured:
            client.close();client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
            r.write_transaction_phase(client,transaction,'rolling-back')
            try:
                rollback(client,transaction,migration_started)
                r.write_transaction_phase(client,transaction,'rolled-back');state['phase']='rolled-back'
            except BaseException:
                r.write_transaction_phase(client,transaction,'rollback-failed');state['phase']='rollback-failed'
                raise
            finally:t._atomic_json(state_path,state)
        raise
    finally:
        if not migration_started or state['phase'] in ('committed','rolled-back'):
            client.close();client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
            if isolated:r.restore_watchdog_state(client,state['watchdog'])
            if admission:r.set_release_start_draining(client,False);r.set_remote_release_drain(client,False)
            r.release_release_lock(client,transaction)
            state['cleanup_complete']=True;t._atomic_json(state_path,state)
        client.close()
    print(json.dumps({'phase':state['phase'],'verification':state.get('verification'),'cleanup_complete':state.get('cleanup_complete')}))


if __name__=='__main__':main()
