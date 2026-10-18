"""Read-only layout and face-reference checks; generation and upload are blocked."""
import json
from playwright.sync_api import sync_playwright,expect
from verify_image_edit_playback_live import login_session,BASE

OUTPUT=BASE/'audit/compact-workflow-20261018'


def main():
    session=login_session();report={'success':False};writes=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        context=browser.new_context(reduced_motion='reduce');context.add_cookies(session['cookies'])
        page=context.new_page();page.on('pageerror',lambda error:errors.append(type(error).__name__))
        def forbid(route):writes.append('blocked');route.abort()
        page.route('**/*generate*',forbid);page.route('**/api/upload*',forbid)
        try:
            for width in (390,1440):
                page.set_viewport_size({'width':width,'height':1000})
                page.goto(session['origin']+'/video',wait_until='domcontentloaded',timeout=60000)
                host=page.locator('.page-host:not([hidden])')
                select=host.locator('button[data-wf=h3_remix_full]');expect(select).to_be_visible(timeout=30000);select.click()
                expect(host.locator('.drop:visible')).to_have_count(1)
                expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
                group=host.locator('.remix-group[data-group="基本设置"] .remix-fields')
                prompt=host.locator('.remix-field[data-control=prompt]')
                assert prompt.bounding_box()['width']>=group.bounding_box()['width']-2
                toggle=host.locator('.remix-field[data-control=second_pass]')
                assert group.bounding_box()['width']/2-10<toggle.bounding_box()['width']<group.bounding_box()['width']/2
                toggle.scroll_into_view_if_needed();page.screenshot(path=str(OUTPUT/f'final-buttons-{width}.png'))
                host.locator('.remix-group[data-group="人脸精修设置"] > summary').click()
                host.locator('[data-toggle-for=param_use_face_reference]').click()
                host.locator('.compact-media-slot[data-slot=face_reference]').click()
                expect(host.locator('.drop[data-media-key=face_reference]')).to_be_visible()
                expect(host.locator('.drop:visible')).to_have_count(1)
                expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('0 / 10')
                host.locator('.compact-uploads').screenshot(path=str(OUTPUT/f'final-face-{width}.png'))
            assert not writes and not errors
            report.update(success=True,desktop_and_mobile_layout=True,independent_face_slot=True,generation_requests=0,upload_requests=0)
        except BaseException as error:report.update(failure=type(error).__name__,page_errors=errors)
        finally:
            response=context.request.post(session['origin']+'/api/auth/logout',data={},headers={
                'Content-Type':'application/json','Origin':session['origin'],'X-CSRF-Token':session['csrf']})
            report['test_session_logged_out']=response.status==200
            context.request.get(session['issuer']+'/api/logout');context.close();browser.close()
    (OUTPUT/'final-layout-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
