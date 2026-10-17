"""Read-only live UI/playback checks using a fresh owner session; never generates work."""
import importlib.util
import inspect
import json
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
import prepare_dreamapi_native_canary as t

BASE=t.BASE
OUTPUT=BASE/'audit/image-edit-release-20261018'


def login_session():
    spec=importlib.util.spec_from_file_location('live_owner_helpers', BASE/'deploy/membership/verify_workbench_live.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    helpers='\n'.join(inspect.getsource(getattr(module,name)) for name in ('NoRedirect','Browser','require','login'))
    code='''import http.cookiejar,json,urllib.error,urllib.parse,urllib.request
from pathlib import Path
'''+helpers+'''
credentials=json.loads(Path('/opt/jt-identity/bootstrap-credentials.json').read_text())
browser=Browser();me=login(browser,credentials,'owner',credentials['workbench_owner_password'])
require(me['user']['is_admin'] and not me['admin_verification_required'],'Verified owner session missing')
print(json.dumps({'origin':credentials['public_origin'],'issuer':credentials['issuer'],'csrf':browser.csrf,
 'cookies':[{'name':c.name,'value':c.value,'domain':c.domain,'path':c.path,'secure':c.secure} for c in browser.cookies]}))
'''
    ssh=t._connect(BASE/'tools/creds.json',t.release.DEPLOY_SSH_KEY_PATH)
    try:return json.loads(t.release.command(ssh,'sudo python3 -c '+shlex.quote(code)))
    finally:ssh.close()


def main():
    session=login_session();report={'success':False};writes=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        context.add_cookies(session['cookies'])
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        page.on('request',lambda request:writes.append(urlsplit(request.url).path) if request.method not in ('GET','HEAD','OPTIONS') else None)
        try:
            page.goto(session['origin']+'/realism',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe',timeout=30000)
            expect(host.locator('.drop')).to_have_count(2)
            assert page.locator('body > .app-shell > .topbar a[href="/realism"]').inner_text()=='图片编辑'
            report['new_workflow_and_nav_live']=True
            catalog=context.request.get(session['origin']+'/api/workflows').json()
            new=next(w for w in catalog if w['id']=='qwen21_wardrobe')
            assert set(new['rh_media'])=={'person','clothing'}
            assert 'rh_workflow_id' not in new and all('node' not in m for m in new['rh_media'].values())
            report['provider_identifiers_hidden']=True
            page.screenshot(path=str(OUTPUT/'live-image-edit-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUTPUT/'live-image-edit-mobile.png'))
            report['mobile_layout']=True
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('body > .app-shell > .topbar a[href="/video"]').click()
            expect(host.locator('#wfForm')).to_be_visible()
            for workflow in [w for w in catalog if w.get('kind')=='video']:
                host.locator('#wfSwitch button[data-wf="'+workflow['id']+'"]').click()
                expect(host.locator('.drop')).to_have_count(len(workflow.get('rh_media',{})))
            report['video_forms_checked']=sum(w.get('kind')=='video' for w in catalog)
            # Unmount the form's preview player before measuring a separate player.
            page.goto(session['origin']+'/api/auth/me',wait_until='domcontentloaded')
            rows=context.request.get(session['origin']+'/api/jobs?scope=video&limit=30').json()
            job=next((j for j in rows if j.get('status')=='done' and j.get('images')),None)
            if job:
                url=job['images'][0]['url']
                assert url.startswith('/api/result-media/')
                response=context.request.get(session['origin']+url,headers={'Range':'bytes=0-31'})
                assert response.status==206 and response.headers.get('cache-control')=='private, max-age=3600'
                assert response.headers.get('vary')=='Cookie' and response.headers.get('etag')
                report['live_range_and_private_cache_headers']=True
                cdp=context.new_cdp_session(page);cdp.send('Network.enable');cache_hits=[]
                cdp.on('Network.requestServedFromCache',lambda data:cache_hits.append(data['requestId']))
                # A new native player requests the exact completed result a second time.
                result=page.evaluate('''async path=>{
                  const load=async()=>{const v=document.createElement('video');v.muted=true;v.preload='auto';document.body.append(v);v.src=path;
                   const start=Date.now();while(Date.now()-start<120000){if(v.error)throw Error('video load failed');if(Number.isFinite(v.duration)&&v.buffered.length&&v.buffered.end(v.buffered.length-1)>=v.duration-.1)return v;await new Promise(r=>setTimeout(r,250))}throw Error('video buffer timed out')};
                  const a=await load();const duration=a.duration;await a.play();await new Promise(r=>setTimeout(r,3000));
                  const firstQuality=a.getVideoPlaybackQuality();a.pause();a.removeAttribute('src');a.load();a.remove();
                  const count=performance.getEntriesByName(new URL(path,location.href).href).length;
                  const b=await load();await b.play();await new Promise(r=>setTimeout(r,3000));const replayQuality=b.getVideoPlaybackQuality();b.pause();b.removeAttribute('src');b.load();b.remove();
                  const entries=performance.getEntriesByName(new URL(path,location.href).href).slice(count);
                  return {duration, first_decoded_frames:firstQuality.totalVideoFrames,first_dropped_frames:firstQuality.droppedVideoFrames,
                   replay_decoded_frames:replayQuality.totalVideoFrames,replay_dropped_frames:replayQuality.droppedVideoFrames,
                   replay_requests:entries.length,replay_transfer_bytes:entries.reduce((n,e)=>n+e.transferSize,0)};
                }''',url)
                report['live_playback']=result
                report['browser_cache_hits']=len(cache_hits)
                assert result['replay_transfer_bytes']==0
            else:report['live_playback']='no completed video available; offline native replay verified'
            assert not errors and not writes
            report.update(success=True,business_writes=0,page_errors=0)
        except BaseException as error:
            report['failure_type']=type(error).__name__
        finally:
            response=context.request.post(session['origin']+'/api/auth/logout',data={},headers={
                'Content-Type':'application/json','Origin':session['origin'],'X-CSRF-Token':session['csrf']})
            report['test_session_logged_out']=response.status==200
            report['logout_clears_private_cache']=response.headers.get('clear-site-data')=='"cache"'
            context.request.get(session['issuer']+'/api/logout')
            context.close();browser.close()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'live-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
