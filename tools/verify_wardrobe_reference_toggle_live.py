"""Inspect the live switch without uploading images or submitting generation."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from verify_image_edit_playback_live import login_session,BASE


def main():
    session=login_session();report={'success':False};writes=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        context.add_cookies(session['cookies']);page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        page.on('request',lambda request:writes.append(urlsplit(request.url).path) if request.method not in ('GET','HEAD','OPTIONS') else None)
        try:
            page.goto(session['origin']+'/realism',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe',timeout=30000)
            catalog=context.request.get(session['origin']+'/api/workflows').json()
            workflow=next(w for w in catalog if w['id']=='qwen21_wardrobe')
            assert workflow['rh_params']['use_clothing']['default'] is True
            assert workflow['rh_media']['clothing']['depends_on']=={'key':'use_clothing','value':True}
            assert 'rh_optional_reference' not in workflow
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                toggle=host.get_by_role('checkbox',name='使用图二参考图',exact=True)
                expect(toggle).to_be_checked()
                expect(host.locator('.drop[data-media-key="clothing"]')).to_be_visible()
                toggle.uncheck()
                expect(host.locator('.drop[data-media-key="clothing"]')).to_be_hidden()
                expect(host.locator('.drop[data-media-key="person"]')).to_be_visible()
                expect(host.locator('#generateBtn')).to_be_disabled()
                assert '图二' not in host.locator('#generateBtn').inner_text()
                toggle.check()
                expect(host.locator('.drop[data-media-key="clothing"]')).to_be_visible()
            assert not errors and not writes
            report.update(success=True,desktop_and_mobile_toggle=True,private_graph_hidden=True,business_writes=0,page_errors=0)
        except BaseException as error:
            report['failure_type']=type(error).__name__
        finally:
            response=context.request.post(session['origin']+'/api/auth/logout',data={},headers={
                'Content-Type':'application/json','Origin':session['origin'],'X-CSRF-Token':session['csrf']})
            report['test_session_logged_out']=response.status==200
            context.request.get(session['issuer']+'/api/logout')
            context.close();browser.close()
    output=BASE/'audit/wardrobe-reference-toggle-20261018/live-verification.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
