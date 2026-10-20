"""Publish security fixes with drained queues, private rollback, and data checks."""
import argparse
import concurrent.futures
import hashlib
import json
import shlex
import subprocess
import time
import urllib.error
import urllib.request

import prepare_dreamapi_native_canary as t
from release_membership_cutover import queue, remote_json

r=t.release
ORIGIN='https://studio.dreamapi.club'
STATE=t.BASE/'audit/security-fix-20261011/release.json'
DATA=r.REMOTE_ROOT+'/panel_data'
HARDEN=r.REMOTE_ROOT+'/deploy/security/harden_host.py'
MODULES=[*r.SERVER_RUNTIME_MODULE_PATHS,'deploy/security/harden_host.py','deploy/security/disable_identity_signup.py']


def fetch(path):
    try:
        with urllib.request.urlopen(urllib.request.Request(ORIGIN+path,headers={'Cache-Control':'no-cache'}),timeout=45) as response:
            return response.status,response.read(),dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code,error.read(),dict(error.headers)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    manifest=json.loads((t.BASE/'static/app-manifest.json').read_text(encoding='utf-8'))
    assets=[p.lstrip('/') for p in manifest['assets']]
    paths=r.require_server_runtime_modules([*assets,*MODULES,'static/app-manifest.json','static/app.html'])
    data={p:(t.BASE/p).read_bytes() for p in paths}
    data={p:raw.replace(b'\r\n',b'\n') if not p.endswith('.webp') else raw for p,raw in data.items()}
    client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
    sftp=client.open_sftp()
    def read(p):
        try:
            with sftp.open(r.REMOTE_ROOT+'/'+p,'rb') as handle:return handle.read()
        except FileNotFoundError:return None
    tx=None
    locked=admission=isolated=stopped=swapped=host_applied=False
    state={}
    try:
        before={p:read(p) for p in paths}
        for p in paths:
            if before[p] is None:
                assert p in assets or p.startswith('deploy/security/'), 'Missing module: '+p
            elif before[p]!=data[p]:
                baseline=subprocess.run(['git','show','HEAD:'+p],cwd=t.BASE,capture_output=True)
                assert baseline.returncode==0 and before[p]==baseline.stdout.replace(b'\r\n',b'\n'),'Production drift: '+p
        changed=[p for p in paths if before[p]!=data[p]]
        assert fetch('/api/jobs')[0]==401
        r.require_release_start_draining_unset(client)
        print(json.dumps({'phase':'preflight','changed_count':len(changed),'queue':queue(client)}),flush=True)
        if not args.execute:return
        assert not STATE.exists(),'Inspect existing release state before retry'
        tx=r.new_release_transaction()
        r.acquire_release_lock(client,tx);locked=True
        state={'phase':'preparing','transaction':tx,'watchdog':r.capture_watchdog_state(client),
               'files':{p:hashlib.sha256(raw).hexdigest() for p,raw in data.items()}}
        t._atomic_json(STATE,state)
        for p in changed:r.stage_file_resilient(client,sftp,t.BASE/p,r.REMOTE_ROOT+'/'+p,tx,data[p])
        backup=r.backup_release(client,sftp,[r.REMOTE_ROOT+'/'+p for p in changed],tx)
        staged_harden=r.transaction_file(tx,HARDEN,'stage')
        state['host_preparation']=json.loads(r.command(client,'sudo python3 '+shlex.quote(staged_harden)+' prepare'))
        r.write_transaction_phase(client,tx,'prepared')
        admission=True;r.set_release_start_draining(client,True)
        busy=r.set_remote_release_drain(client,True)
        deadline=time.monotonic()+900
        while queue(client)['active'] or any(busy[k] for k in ('cloud_busy','local_busy','api_busy')):
            if time.monotonic()>=deadline:raise RuntimeError('Existing work still active; no tasks cancelled')
            print('Waiting for active tasks to finish naturally',flush=True)
            time.sleep(15);busy=r.set_remote_release_drain(client,True)
        isolated=True;r.isolate_watchdog(client)
        stopped=True;r.stop_panel_resilient(client)
        remote_json(client,f'''import sqlite3,pathlib,json,shutil,os
root=pathlib.Path({DATA!r});target=pathlib.Path({tx['root']!r})
src=sqlite3.connect(str(root/'membership.sqlite3'));dst=sqlite3.connect(str(target/'membership-before.sqlite3'))
src.backup(dst);dst.close();src.close();os.chmod(target/'membership-before.sqlite3',0o600)
for name in ('jobs.json','favorites.json','upload_capabilities.json'):
 if (root/name).exists():shutil.copy2(root/name,target/('before-'+name));os.chmod(target/('before-'+name),0o600)
print(json.dumps({{'server_local_backup':True}}))
''',root=True)
        for p in changed:assert read(p)==before[p],'Concurrent modification: '+p
        r.write_transaction_phase(client,tx,'swapping');swapped=True
        r.command(client,'mkdir -p -- '+shlex.quote(r.REMOTE_ROOT+'/deploy/security'))
        for p in changed:
            remote=r.REMOTE_ROOT+'/'+p;staged=r.transaction_file(tx,remote,'stage')
            sftp.chmod(staged,0o644);sftp.posix_rename(staged,remote);r.fsync_remote_file(client,remote)
        host_applied=True
        state['host_application']=json.loads(r.command(client,'sudo python3 '+shlex.quote(HARDEN)+' apply'))
        # Verify a completely new key-authenticated connection before proceeding.
        fresh=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
        assert r.command(fresh,'true')==''
        fresh.close();state['fresh_ssh_key_login']=True
        r.command(client,'sudo systemctl start comfy-panel',timeout=60)
        r.wait_for_loopback_live(client)
        r.set_remote_release_drain(client,True,require_start_draining=True)
        state['host_verification']=json.loads(r.command(client,'sudo python3 '+shlex.quote(HARDEN)+' verify'))
        me=json.loads(fetch('/api/auth/me')[1]);assert me.get('login_method')=='access_code' and not me.get('authenticated')
        assert fetch('/api/jobs')[0]==401 and fetch('/api/admin/release-drain')[0]==404
        assert fetch('/static/video.html')[0]==404 and fetch('/static/index.html')[0]==404
        def verify(p):
            code,raw,_=fetch('/' if p=='static/app.html' else '/'+p)
            assert code==200 and raw==data[p],'Public asset mismatch: '+p
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(verify,assets+['static/app.html','static/app-manifest.json']))
        state['data_verification']=remote_json(client,f'''import pathlib,json,sqlite3
root=pathlib.Path({DATA!r});backup=pathlib.Path({tx['root']!r})
before=json.loads((backup/'before-jobs.json').read_text());after=json.loads((root/'jobs.json').read_text())
assert before==after,'Job ledger changed during release'
for name in ('favorites.json','upload_capabilities.json'):
 if (backup/('before-'+name)).exists():assert (backup/('before-'+name)).read_bytes()==(root/name).read_bytes(),name
db=sqlite3.connect('file:'+str(root/'membership.sqlite3')+'?mode=ro',uri=True)
old=sqlite3.connect('file:'+str(backup/'membership-before.sqlite3')+'?mode=ro',uri=True)
for table in ('users','plans','entitlements','activation_codes','reservations','login_credentials'):
 assert db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()==old.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall(),table
print(json.dumps({{'jobs_preserved':len(after),'favorites_preserved':len(json.loads((root/'favorites.json').read_text())),'accounts_and_plans_preserved':True}}))
''',root=True)
        state['identity_signup']=json.loads(r.command(client,'sudo python3 '+shlex.quote(r.REMOTE_ROOT+'/deploy/security/disable_identity_signup.py')))
        state['phase']='committed';r.write_transaction_phase(client,tx,'committed');t._atomic_json(STATE,state)
        print('SECURITY_RELEASE_COMPLETE',flush=True)
    except BaseException:
        if swapped:
            r.stop_panel_resilient(client)
            if host_applied:r.command(client,'sudo python3 '+shlex.quote(HARDEN)+' rollback')
            for p in changed:
                remote=r.REMOTE_ROOT+'/'+p
                if not backup[remote]['exists']:
                    # Remove only this transaction's byte-identical new files.
                    # Otherwise rolling back the older static handler could
                    # leave unreferenced new assets publicly readable.
                    remote_json(client,f'''import pathlib,hashlib,json
p=pathlib.Path({remote!r});root=pathlib.Path({r.REMOTE_ROOT!r})
assert p.is_relative_to(root) and p!=root and not p.is_symlink()
if p.exists():
 assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()=={hashlib.sha256(data[p]).hexdigest()!r}
 p.unlink()
print(json.dumps({{'new_release_file_removed':True}}))
''')
                    continue
                r.command(client,'cp -- '+shlex.quote(r.transaction_file(tx,remote,'backup'))+' '+shlex.quote(remote+'.security-rollback'))
                sftp.chmod(remote+'.security-rollback',backup[remote]['mode']);sftp.posix_rename(remote+'.security-rollback',remote);r.fsync_remote_file(client,remote)
            r.command(client,'sudo systemctl start comfy-panel',timeout=60);r.wait_for_loopback_live(client)
            state['phase']='rolled-back';r.write_transaction_phase(client,tx,'rolled-back');t._atomic_json(STATE,state)
        elif stopped:
            r.command(client,'sudo systemctl start comfy-panel',timeout=60);r.wait_for_loopback_live(client)
        raise
    finally:
        if locked and (not swapped or state.get('phase') in ('committed','rolled-back')):
            if isolated:r.restore_watchdog_state(client,state['watchdog'])
            if admission:r.set_release_start_draining(client,False);r.set_remote_release_drain(client,False)
            r.release_release_lock(client,tx);state['cleanup_complete']=True;t._atomic_json(STATE,state)
        sftp.close();client.close()


if __name__=='__main__':main()
