"""Deployed controls and synthetic uploads; generation is explicitly blocked."""
import base64
import io
import json
import subprocess
import wave
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright,expect
from verify_image_edit_playback_live import login_session,BASE

OUTPUT=BASE/'audit/h3-optimized-20261020'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    output=io.BytesIO();Image.new('RGB',(48,64),(23,80,140)).save(output,format='PNG');png=output.getvalue()
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*4000)
    wav=output.getvalue()
    video=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=navy:s=64x64:r=24',
        '-t','0.5','-c:v','libx264','-pix_fmt','yuv420p','-movflags','frag_keyframe+empty_moov','-f','mp4','pipe:1'],
        capture_output=True,check=True).stdout
    session=login_session();report={'success':False};responses=[];generation=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--disable-webgl'])
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',permissions=['clipboard-read','clipboard-write'])
        context.add_cookies(session['cookies']);page=context.new_page()
        def forbid(route):generation.append(urlsplit(route.request.url).path);route.abort()
        page.route('**/*generate*',forbid)
        page.on('pageerror',lambda e:errors.append(type(e).__name__))
        page.on('response',lambda response:responses.append({'path':urlsplit(response.url).path,'status':response.status})
            if urlsplit(response.url).path in ('/api/upload-start','/api/upload-chunk','/api/upload-finish') else None)
        try:
            page.goto(session['origin']+'/video',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            button=host.locator('button[data-wf=h3_reference_optimized]');expect(button).to_be_visible(timeout=30000);button.click()
            workflow=next(w for w in context.request.get(session['origin']+'/api/workflows').json() if w['id']=='h3_reference_optimized')
            assert len(workflow['rh_params'])==32 and len(workflow['rh_media'])==15
            assert all(v not in json.dumps(workflow) for v in ('rh_graph','rh_workflow_id','safetensors','2111727257252290561'))
            report['public_schema_and_secret_boundary']=True
            expect(host.locator('.drop:visible')).to_have_count(1)
            expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
            expect(host.locator('#param_second_pass')).not_to_be_checked()
            expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_hidden()
            host.locator('[data-toggle-for=param_second_pass]').click()
            expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_visible()
            host.locator('[data-toggle-for=param_second_pass]').click()
            expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_hidden()
            host.locator('.remix-group[data-group="LoRA 设置"] > summary').click()
            host.locator('[data-toggle-for=param_lora_3_enabled]').click()
            expect(host.locator('#param_lora_3_enabled')).to_be_checked()
            host.locator('[data-toggle-for=param_lora_3_enabled]').click()
            report['branch_and_lora_switches_live']=True
            page.evaluate("""async data=>{const raw=Uint8Array.from(atob(data),c=>c.charCodeAt(0));await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([raw],{type:'image/png'})})])}""",base64.b64encode(png).decode())
            drop=host.locator('.drop[data-media-key=reference_image]');drop.locator('.paste-target').click();page.keyboard.press('Control+V')
            expect(drop.locator('.fn')).to_contain_text('已上传',timeout=180000)
            expect(host.locator('.drop[data-media-key=reference_image_2]')).to_be_visible()
            expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('1 / 9')
            report['clipboard_image_uploaded']=True
            for kind,key,name,mime,raw in [('video','source_video','jt-optimized-check.mp4','video/mp4',video),
                                           ('audio','reference_audio','jt-optimized-check.wav','audio/wav',wav)]:
                host.locator('.compact-media-tab[data-media-type='+kind+']').click()
                drop=host.locator('.drop[data-media-key='+key+']')
                drop.locator('input[type=file]').set_input_files({'name':name,'mimeType':mime,'buffer':raw})
                expect(drop.locator('.fn')).to_contain_text('已上传',timeout=180000)
                expect(host.locator('.drop[data-media-key='+key+'_2]')).to_be_visible()
                expect(host.locator('.drop:visible')).to_have_count(1)
                expect(host.locator('.compact-media-tab[data-media-type='+kind+'] .compact-count')).to_have_text('1 / 3')
                report[kind+'_uploaded']=True
            host.locator('.compact-media-tab[data-media-type=image]').click()
            host.locator('.compact-uploads').screenshot(path=str(OUTPUT/'live-upload-panel.png'))
            host.locator('.remix-group[data-group="基本设置"]').scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT/'live-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            host.locator('.compact-uploads').screenshot(path=str(OUTPUT/'live-mobile-uploads.png'))
            host.locator('.remix-group[data-group="基本设置"]').scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT/'live-mobile.png'));report['mobile_layout']=True
            assert not generation and not errors
            assert responses and all(row['status']==200 for row in responses)
            report.update(success=True,controls=len(workflow['rh_params']),generation_requests=0,upload_responses=responses)
        except BaseException as error:
            report.update(failure_type=type(error).__name__,upload_responses=responses,page_errors=errors)
        finally:
            result=context.request.post(session['origin']+'/api/auth/logout',data={},headers={
                'Content-Type':'application/json','Origin':session['origin'],'X-CSRF-Token':session['csrf']})
            report['test_session_logged_out']=result.status==200
            context.request.get(session['issuer']+'/api/logout');context.close();browser.close()
    (OUTPUT/'live-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
