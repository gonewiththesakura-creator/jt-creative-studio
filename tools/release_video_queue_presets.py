"""Scoped queue/UI release; drain active work naturally and preserve waiting jobs."""
import argparse
import json
import shlex
import subprocess
import time
import prepare_dreamapi_native_canary as t
import release_h3_lora_slots as ui

r=t.release
STATE=t.BASE/'audit/queue-presets-20260929/release.json'


def normalize_release_bytes(path, payload):
    """Normalize source text only; binary assets must retain exact bytes."""
    if path.lower().endswith(('.py', '.js', '.css', '.html', '.json', '.txt')):
        return payload.replace(b'\r\n', b'\n')
    return payload


def snapshot(client):
    code="""import json,pathlib
jobs=json.loads(pathlib.Path('/home/admin/comfy-panel/panel_data/jobs.json').read_text())
print(json.dumps({'active':[j['id'] for j in jobs.values() if j.get('status') in ('running','recovering')], 'waiting':[j['id'] for j in jobs.values() if j.get('status')=='queued']}))
"""
    return json.loads(r.command(client,'python3 -c '+shlex.quote(code),timeout=25))


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',
                        help='run the full release gate and publish; without it only read-only production checks run')
    return parser.parse_args(argv)


def verify_production_baseline(sftp,data):
    """Read-only: production must hold the candidate or HEAD bytes, so nothing unreviewed is overwritten."""
    changed=[]
    for p,raw in data.items():
        old=subprocess.run(['git','show','HEAD:'+p],cwd=t.BASE,capture_output=True)
        try:
            with sftp.open(r.REMOTE_ROOT+'/'+p,'rb') as f:live=normalize_release_bytes(p,f.read())
        except FileNotFoundError:
            assert old.returncode!=0,'missing production '+p
            changed.append(p);continue
        assert live==raw or (old.returncode==0 and live==normalize_release_bytes(p,old.stdout)),'production changed '+p
        if live!=raw:changed.append(p)
    return changed


def main(extra_paths=(),execute=None):
    if execute is None:execute=parse_args().execute
    manifest=json.loads((t.BASE/'static/app-manifest.json').read_text(encoding='utf8'))
    paths=[*r.SERVER_RUNTIME_MODULE_PATHS]+[p.lstrip('/') for p in manifest['pages']['/video'].values() if p.startswith('/static/')]+['static/video.html','static/app-manifest.json','static/app.html']
    paths+=[p for p in extra_paths if p not in paths]
    r.require_server_runtime_modules(paths)
    data={p:normalize_release_bytes(p,(t.BASE/p).read_bytes()) for p in paths}
    if not execute:
        # Default is a read-only preflight: no lock, upload, drain or restart, and no 10 minute gate.
        c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH);s=c.open_sftp()
        try:changed=verify_production_baseline(s,data)
        finally:s.close();c.close()
        print(json.dumps({'preflight':'read-only','would_change':changed},ensure_ascii=False),flush=True)
        print('Pass --execute to run the full release gate and publish.',flush=True)
        return
    r.run_feature_release_gate(data,normalize_release_bytes)
    c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH);s=c.open_sftp()
    verify_production_baseline(s,data)
    r.require_persistent_release_drain_contract(c);r.require_release_start_draining_unset(c)
    tx=r.new_release_transaction();r.acquire_release_lock(c,tx)
    state={'transaction':tx,'phase':'preparing','watchdog':r.capture_watchdog_state(c)}
    t._atomic_json(STATE,state)
    admission=isolated=swapped=False
    remotes=[r.REMOTE_ROOT+'/'+p for p in paths]
    try:
        for p,raw in data.items():r.stage_file_resilient(c,s,t.BASE/p,r.REMOTE_ROOT+'/'+p,tx,raw)
        r.command(c,'python3 -m py_compile '+' '.join(shlex.quote(r.transaction_file(tx,r.REMOTE_ROOT+'/'+p,'stage')) for p in r.SERVER_RUNTIME_MODULE_PATHS))
        backup=r.backup_release(c,s,remotes,tx);r.write_transaction_phase(c,tx,'prepared')
        admission=True;r.set_release_start_draining(c,True);r.set_remote_release_drain(c,True)
        deadline=time.time()+900
        while True:
            current=snapshot(c)
            print('DRAIN',json.dumps(current),flush=True)
            if not current['active']:break
            if time.time()>deadline:raise RuntimeError('Active work did not finish; leaving existing service intact')
            time.sleep(15)
        s.close();c.close()
        c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH);s=c.open_sftp()
        isolated=True;r.isolate_watchdog(c)
        assert not snapshot(c)['active']
        r.stop_panel_resilient(c)
        ledger=tx['root']+'/jobs-before-restart.json'
        r.command(c,'cp -- '+shlex.quote(r.REMOTE_ROOT+'/panel_data/jobs.json')+' '+shlex.quote(ledger));r.fsync_remote_file(c,ledger)
        r.write_transaction_phase(c,tx,'swapping');swapped=True
        for p,raw in data.items():
            remote=r.REMOTE_ROOT+'/'+p
            s.posix_rename(r.transaction_file(tx,remote,'stage'),remote)
            s.chmod(remote,backup[remote]['mode'] if backup[remote]['exists'] else 0o644);r.fsync_remote_file(c,remote)
            with s.open(remote,'rb') as f:assert f.read()==raw
        r.command(c,'sudo systemctl start comfy-panel',timeout=60);r.wait_for_loopback_live(c)
        r.set_remote_release_drain(c,True,require_start_draining=True)
        code="""import json,pathlib
root=pathlib.Path('/home/admin/comfy-panel');before=json.loads(pathlib.Path(BACKUP).read_text());after=json.loads((root/'panel_data/jobs.json').read_text())
ids=[k for k,j in before.items() if j.get('status')=='queued']
assert all(after.get(k)==before[k] for k in ids),'queued job changed during restart'
print(json.dumps({'waiting_preserved':len(ids),'ids':ids}))
""".replace('BACKUP',repr(ledger))
        print(r.command(c,'python3 -c '+shlex.quote(code)),flush=True)
        s.close();c.close()
        c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH);s=c.open_sftp()
        ui.verify(c,data)
        r.write_transaction_phase(c,tx,'committed');state['phase']='committed';t._atomic_json(STATE,state)
    except BaseException:
        if swapped and state['phase']!='committed':
            if not c.get_transport() or not c.get_transport().is_active():
                c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH);s=c.open_sftp()
            r.write_transaction_phase(c,tx,'rolling-back');r.rollback_release(c,s,remotes,tx)
            r.write_transaction_phase(c,tx,'rolled-back');state['phase']='rolled-back';t._atomic_json(STATE,state)
        raise
    finally:
        if not swapped or state['phase'] in ('committed','rolled-back'):
            c.close();c=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
            if isolated:r.restore_watchdog_state(c,state['watchdog'])
            if admission:r.set_release_start_draining(c,False);r.set_remote_release_drain(c,False)
            r.release_release_lock(c,tx);state['cleanup_complete']=True;t._atomic_json(STATE,state)
        s.close();c.close()
    print('RELEASE_COMPLETE',flush=True)


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
