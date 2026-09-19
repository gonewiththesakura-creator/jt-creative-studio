"""One-time repair of the provider-confirmed missing task; no provider submits."""
import json
import shlex

from prepare_dreamapi_native_canary import _connect, release


def main():
    client = _connect(release.BASE / "tools/creds.json", release.DEPLOY_SSH_KEY_PATH)
    code = r'''
import json,pathlib,subprocess,time,os
root=pathlib.Path('/home/admin/comfy-panel')
path=root/'panel_data/jobs.json'
jobs=json.loads(path.read_text())
target='091ca0762c79'
active=[j['id'] for j in jobs.values() if j.get('status') in ('running','recovering')]
if any(j != target for j in active): raise RuntimeError('other tasks are active')
if jobs[target].get('rh_task_id') != '2100877290394173442': raise RuntimeError('task identity mismatch')
import urllib.request
pid=subprocess.check_output(['systemctl','show','comfy-panel','-p','MainPID','--value'],text=True).strip()
env=dict(x.split('=',1) for x in pathlib.Path('/proc/'+pid+'/environ').read_bytes().decode().split('\0') if '=' in x)
request=urllib.request.Request('https://www.runninghub.ai/openapi/v2/query',data=json.dumps({'taskId':jobs[target]['rh_task_id']}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+env['RUNNINGHUB_API_KEY']})
with urllib.request.urlopen(request,timeout=30) as response: result=json.load(response)
if str(result.get('errorCode')) != '1004': raise RuntimeError('provider no longer confirms missing task')
subprocess.run(['systemctl','stop','comfy-panel'],check=True)
try:
    jobs=json.loads(path.read_text())
    if any(j.get('status') in ('running','recovering') and j['id'] != target for j in jobs.values()):
        raise RuntimeError('another task started; abort repair')
    backup=path.with_name('jobs.before-rh-missing-'+str(int(time.time()))+'.json')
    backup.write_bytes(path.read_bytes());os.chmod(backup,0o600)
    job=jobs[target]
    job.update(status='error',provider_status='UNAVAILABLE',error='RH_TASK_UNAVAILABLE',provider_finished=time.time())
    temp=path.with_suffix('.reconcile.tmp')
    temp.write_text(json.dumps(jobs,ensure_ascii=False),encoding='utf8')
    os.chown(temp,path.stat().st_uid,path.stat().st_gid)
    os.chmod(temp,path.stat().st_mode & 0o777)
    os.replace(temp,path)
    print(json.dumps({'task':target,'status':'error','provider_status':'UNAVAILABLE','backup':backup.name}))
finally:
    subprocess.run(['systemctl','start','comfy-panel'],check=True)
'''
    try:
        release.set_remote_release_drain(client, True)
        print(release.command(client, "sudo python3 -c " + shlex.quote(code), timeout=90))
    finally:
        release.set_remote_release_drain(client, False)
        client.close()


if __name__ == "__main__":
    main()
