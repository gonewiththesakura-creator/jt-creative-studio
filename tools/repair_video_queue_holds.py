"""Deploy the queue repair while preserving the live ledger and waiting jobs."""
import json
import shlex
import subprocess
import prepare_dreamapi_native_canary as t

r=t.release
STATE=t.BASE/'audit/queue-repair-20260929/release.json'


def assert_only_stale_holds(client):
    code="""import json,pathlib,time,urllib.request
root=pathlib.Path('/home/admin/comfy-panel');jobs=json.loads((root/'panel_data/jobs.json').read_text())
assert not any(j.get('status') in ('running','recovering') for j in jobs.values()),'real active job exists'
holds=[j for j in jobs.values() if j.get('queue_hold')]
assert holds and all(j.get('status')=='error' and not j.get('rh_task_id') and time.time()-j.get('submit_started',time.time())>300 for j in holds),'unexpected hold'
env=dict(line.split('=',1) for line in (root/'panel.env').read_text().splitlines() if '=' in line and not line.startswith('#'));key=env['RUNNINGHUB_API_KEY'].strip().strip(chr(34)).strip(chr(39))
req=urllib.request.Request('https://www.runninghub.ai/uc/openapi/accountStatus',data=json.dumps({'apikey':key}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
with urllib.request.urlopen(req,timeout=25) as f:d=json.load(f)
assert d.get('code')==0 and str((d.get('data') or {}).get('currentTaskCounts'))=='0','provider busy or unconfirmed'
print(json.dumps({'held':[j['id'] for j in holds],'waiting':[j['id'] for j in jobs.values() if j.get('status')=='queued']}))
"""
    return json.loads(r.command(client,'python3 -c '+shlex.quote(code),timeout=40))


def main():
    client=t._connect(t.BASE/'tools/creds.json',r.DEPLOY_SSH_KEY_PATH)
    sftp=client.open_sftp();remote=r.REMOTE_ROOT+'/server.py'
    payload=(t.BASE/'server.py').read_bytes().replace(b'\r\n',b'\n')
    original=subprocess.check_output(['git','show','HEAD:server.py'],cwd=t.BASE).replace(b'\r\n',b'\n')
    with sftp.open(remote,'rb') as f:assert f.read().replace(b'\r\n',b'\n')==original,'production baseline changed'
    initial=assert_only_stale_holds(client)
    r.require_persistent_release_drain_contract(client);r.require_release_start_draining_unset(client)
    tx=r.new_release_transaction();r.acquire_release_lock(client,tx)
    state={'transaction':tx,'initial':initial,'watchdog':r.capture_watchdog_state(client),'phase':'preparing'}
    t._atomic_json(STATE,state)
    swapped=False;admission=False;isolated=False
    try:
        r.stage_file_resilient(client,sftp,t.BASE/'server.py',remote,tx,payload)
        r.command(client,'python3 -m py_compile '+shlex.quote(r.transaction_file(tx,remote,'stage')))
        manifest=r.backup_release(client,sftp,[remote],tx)
        r.write_transaction_phase(client,tx,'prepared')
        admission=True;r.set_release_start_draining(client,True);r.set_remote_release_drain(client,True)
        isolated=True;r.isolate_watchdog(client)
        snapshot=assert_only_stale_holds(client)
        assert set(initial['waiting']).issubset(snapshot['waiting'])
        r.stop_panel_resilient(client)
        # Snapshot actual production data, never replace it with a local ledger.
        r.command(client,'cp -- '+shlex.quote(r.REMOTE_ROOT+'/panel_data/jobs.json')+' '+shlex.quote(tx['root']+'/jobs-before-restart.json'))
        r.fsync_remote_file(client,tx['root']+'/jobs-before-restart.json')
        r.write_transaction_phase(client,tx,'swapping');swapped=True
        sftp.posix_rename(r.transaction_file(tx,remote,'stage'),remote);sftp.chmod(remote,manifest[remote]['mode']);r.fsync_remote_file(client,remote)
        with sftp.open(remote,'rb') as f:assert f.read()==payload
        r.command(client,'sudo systemctl start comfy-panel',timeout=60)
        r.wait_for_loopback_live(client)
        state_after=r.set_remote_release_drain(client,True,require_start_draining=True)
        code="""import json,pathlib
root=pathlib.Path('/home/admin/comfy-panel');before=json.loads(pathlib.Path(BACKUP).read_text());after=json.loads((root/'panel_data/jobs.json').read_text())
ids=[k for k,j in before.items() if j.get('status')=='queued']
assert all(after.get(k)==before[k] for k in ids),'queued job changed during restart'
print(json.dumps({'waiting_preserved':len(ids),'ids':ids}))
""".replace('BACKUP',repr(tx['root']+'/jobs-before-restart.json'))
        print(r.command(client,'python3 -c '+shlex.quote(code)),flush=True)
        r.write_transaction_phase(client,tx,'committed');state['phase']='committed';t._atomic_json(STATE,state)
    except BaseException:
        if swapped and state['phase']!='committed':
            r.write_transaction_phase(client,tx,'rolling-back')
            r.rollback_release(client,sftp,[remote],tx)
            r.write_transaction_phase(client,tx,'rolled-back');state['phase']='rolled-back';t._atomic_json(STATE,state)
        raise
    finally:
        if not swapped or state['phase'] in ('committed','rolled-back'):
            if isolated:r.restore_watchdog_state(client,state['watchdog'])
            if admission:r.set_release_start_draining(client,False);r.set_remote_release_drain(client,False)
            r.release_release_lock(client,tx);state['cleanup_complete']=True;t._atomic_json(STATE,state)
        sftp.close();client.close()
    print('REPAIR_DEPLOYED; QUEUE_ADMISSION_OPEN',flush=True)


if __name__=='__main__':main()
