"""Switch an already released loopback-capable panel using release drain/lock helpers."""
import json
import pathlib
import shlex
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_dreamapi_native_canary import _connect, release

ENV_PATH = '/etc/comfy-panel/internal-api.env'
DROPIN_PATH = '/etc/systemd/system/comfy-panel.service.d/98-internal-api.conf'
ENV = 'DREAMAPI_CONNECTION_MODE=direct\nDREAMAPI_BASE_URL=http://127.0.0.1:8080/v1\n'
DROPIN = '[Service]\nEnvironmentFile=' + ENV_PATH + '\n'

def config_script(action):
    return f'''import pathlib,os,subprocess
items=[({ENV_PATH!r},{ENV!r},0o600),({DROPIN_PATH!r},{DROPIN!r},0o644)]
action={action!r}
for name,content,mode in items:
    p=pathlib.Path(name)
    if action=='check':
        if p.exists() or p.is_symlink(): raise RuntimeError('internal config already exists; inspect first')
    elif action=='install':
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
        with os.fdopen(fd,'w') as f: f.write(content);f.flush();os.fsync(f.fileno())
    elif action=='rollback':
        if p.exists():
            if p.is_symlink() or p.read_text()!=content: raise RuntimeError('config changed; refusing removal')
            p.unlink()
if action!='check': subprocess.run(['systemctl','daemon-reload'],check=True)
'''

VERIFY = '''import pathlib,subprocess,json,urllib.request
pid=subprocess.check_output(['systemctl','show','comfy-panel','-p','MainPID','--value'],text=True).strip()
env=dict(x.split('=',1) for x in pathlib.Path('/proc/'+pid+'/environ').read_bytes().decode().split('\\0') if '=' in x)
assert env.get('DREAMAPI_BASE_URL')=='http://127.0.0.1:8080/v1'
assert env.get('DREAMAPI_CONNECTION_MODE')=='direct'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
req=urllib.request.Request(env['DREAMAPI_BASE_URL']+'/models',headers={'Authorization':'Bearer '+env['DREAMAPI_KEY']})
with opener.open(req,timeout=20) as response:
    assert response.status==200
    count=len(json.load(response).get('data',[]))
print(json.dumps({'base_url':env['DREAMAPI_BASE_URL'],'models':count,'pid':pid}))
'''

def main():
    if sys.argv[1:] != ['--execute']:
        raise SystemExit('Use --execute only after the loopback-capable release has passed all gates.')
    release.require_public_idle(release.PUBLIC_BASE, phase='internal-switch')
    client = _connect(release.BASE / 'tools/creds.json', release.DEPLOY_SSH_KEY_PATH)
    transaction = release.new_release_transaction()
    locked = armed = drained = touched = isolated = False
    safe_unlock = True
    watchdog = None
    try:
        release.acquire_release_lock(client, transaction)
        locked = True
        release.require_persistent_release_drain_contract(client)
        release.require_release_start_draining_unset(client)
        release.command(client, 'sudo python3 -c ' + shlex.quote(config_script('check')))
        watchdog = release.capture_watchdog_state(client)
        safe_unlock = False
        armed = True
        release.set_release_start_draining(client, True)
        drained = True
        release.enable_remote_release_drain(client)
        isolated = True
        release.isolate_watchdog(client)
        release.require_loopback_idle(client, phase='internal-switch-drained')
        touched = True
        release.command(client, 'sudo python3 -c ' + shlex.quote(config_script('install')))
        release.command(client, 'sudo systemctl restart comfy-panel')
        release.wait_for_loopback_live(client)
        release.wait_for_remote_release_drain(client)
        verified = release.command(client, 'sudo python3 -c ' + shlex.quote(VERIFY))
        release.require_dreamapi_release_health(release.fetch_json(release.PUBLIC_BASE, '/api/health'))
        release.set_release_start_draining(client, False)
        armed = False
        release.set_remote_release_drain(client, False)
        drained = False
        release.restore_watchdog_state(client, watchdog)
        isolated = False
        touched = False
        safe_unlock = True
        print('INTERNAL_SWITCH_OK', verified)
    except BaseException:
        if touched:
            # Keep admission fenced through rollback and restart.
            release.set_release_start_draining(client, True)
            armed = True
            release.command(client, 'sudo python3 -c ' + shlex.quote(config_script('rollback')))
            release.command(client, 'sudo systemctl restart comfy-panel')
            release.wait_for_loopback_live(client)
            release.wait_for_remote_release_drain(client)
            release.require_dreamapi_release_health(release.fetch_json(release.PUBLIC_BASE, '/api/health'))
        if armed:
            release.set_release_start_draining(client, False)
        if drained:
            release.set_remote_release_drain(client, False)
        if isolated and watchdog is not None:
            release.restore_watchdog_state(client, watchdog)
        safe_unlock = True
        raise
    finally:
        if locked and safe_unlock:
            release.release_release_lock(client, transaction)
        client.close()

if __name__ == '__main__':
    main()
