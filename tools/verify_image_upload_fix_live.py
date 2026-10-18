"""Upload synthetic images through the actual clipboard/file UI; never generate."""
import base64
import io
import json
from urllib.parse import urlsplit
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from verify_image_edit_playback_live import login_session,BASE


def main():
    output=io.BytesIO();Image.new('RGB',(48,48),(23,80,140)).save(output,format='PNG')
    png=output.getvalue();session=login_session();report={'success':False};responses=[];generation=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',
                                   permissions=['clipboard-read','clipboard-write'])
        context.add_cookies(session['cookies']);page=context.new_page()
        def forbid_generation(route):
            generation.append(urlsplit(route.request.url).path);route.abort()
        page.route('**/*generate*',forbid_generation)
        page.on('response',lambda response:responses.append({'path':urlsplit(response.url).path,'status':response.status})
                if urlsplit(response.url).path in ('/api/upload-start','/api/upload-chunk','/api/upload-finish') else None)
        try:
            page.goto(session['origin']+'/realism',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe',timeout=30000)
            await_clipboard="""async data=>{const raw=Uint8Array.from(atob(data),c=>c.charCodeAt(0));
                await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([raw],{type:'image/png'})})])}"""
            page.evaluate(await_clipboard,base64.b64encode(png).decode())
            host.locator('.drop[data-media-key="person"] .paste-target').click()
            page.keyboard.press('Control+V')
            expect(host.locator('.upload-status.ok')).to_have_count(1,timeout=180000)
            report['real_ctrl_v_uploaded']=True
            host.locator('.drop[data-media-key="clothing"] input[type=file]').set_input_files({
                'name':'jt-upload-check.png','mimeType':'image/png','buffer':png})
            expect(host.locator('.upload-status.ok')).to_have_count(2,timeout=180000)
            expect(host.locator('#generateBtn')).to_be_enabled()
            report['second_reference_file_uploaded']=True
            assert not generation and responses and all(row['status']==200 for row in responses)
            report.update(success=True,upload_responses=responses,generation_requests=0)
        except BaseException as error:
            report.update(failure_type=type(error).__name__,upload_responses=responses)
        finally:
            response=context.request.post(session['origin']+'/api/auth/logout',data={},headers={
                'Content-Type':'application/json','Origin':session['origin'],'X-CSRF-Token':session['csrf']})
            report['test_session_logged_out']=response.status==200
            context.request.get(session['issuer']+'/api/logout')
            context.close();browser.close()
    target=BASE/'audit/image-upload-fix-20261018/live-verification.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
