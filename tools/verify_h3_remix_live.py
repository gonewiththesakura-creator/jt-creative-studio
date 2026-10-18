"""Verify deployed controls and real synthetic uploads without submitting generation."""
import base64
import io
import json
import subprocess
import wave
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright,expect
from verify_image_edit_playback_live import login_session,BASE

OUTPUT=BASE/'audit/compact-workflow-20261018'


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
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        page.on('response',lambda response:responses.append({'path':urlsplit(response.url).path,'status':response.status})
            if urlsplit(response.url).path in ('/api/upload-start','/api/upload-chunk','/api/upload-finish') else None)
        try:
            page.goto(session['origin']+'/video',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            button=host.locator('button[data-wf=h3_remix_full]');expect(button).to_be_visible(timeout=30000);button.click()
            catalog=context.request.get(session['origin']+'/api/workflows').json()
            workflow=next(w for w in catalog if w['id']=='h3_remix_full')
            assert len(workflow['rh_params'])==76 and len(workflow['rh_media'])==16
            assert 'prompt_optimizer_enabled' not in workflow['rh_params']
            expect(host.locator('.drop:visible')).to_have_count(1)
            expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
            expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('0 / 9')
            public=json.dumps(workflow)
            assert all(value not in public for value in ('rh_graph','rh_workflow_id','safetensors','prompt_optimizer_api_key'))
            report['public_schema_and_secret_boundary']=True
            expect(host.locator('#param_second_pass')).to_be_checked();host.locator('[data-toggle-for=param_second_pass]').click()
            expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_hidden()
            host.locator('[data-toggle-for=param_second_pass]').click()
            host.locator('[data-toggle-for=param_face_refine]').click()
            expect(host.locator('.remix-group[data-group="人脸精修设置"]')).to_be_hidden()
            host.locator('[data-toggle-for=param_face_refine]').click();report['branch_switches_live']=True
            page.evaluate("""async data=>{const raw=Uint8Array.from(atob(data),c=>c.charCodeAt(0));await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([raw],{type:'image/png'})})])}""",base64.b64encode(png).decode())
            drop=host.locator('.drop[data-media-key=reference_image]');drop.locator('.paste-target').click();page.keyboard.press('Control+V')
            expect(drop.locator('.fn')).to_contain_text('已上传',timeout=180000);report['clipboard_image_uploaded']=True
            expect(host.locator('.drop[data-media-key=reference_image_2]')).to_be_visible()
            expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('1 / 9')
            host.locator('.compact-media-tab[data-media-type=video]').click()
            drop=host.locator('.drop[data-media-key=source_video]')
            drop.locator('input[type=file]').set_input_files({'name':'jt-remix-check.mp4','mimeType':'video/mp4','buffer':video})
            expect(drop.locator('.fn')).to_contain_text('已上传',timeout=180000);report['video_uploaded']=True
            expect(host.locator('.drop[data-media-key=source_video_2]')).to_be_visible()
            expect(host.locator('.compact-media-tab[data-media-type=video] .compact-count')).to_have_text('1 / 3')
            host.locator('.compact-media-tab[data-media-type=audio]').click()
            drop=host.locator('.drop[data-media-key=reference_audio]')
            drop.locator('input[type=file]').set_input_files({'name':'jt-remix-check.wav','mimeType':'audio/wav','buffer':wav})
            expect(drop.locator('.fn')).to_contain_text('已上传',timeout=180000)
            expect(drop.locator('audio')).to_be_attached();report['audio_uploaded']=True
            expect(host.locator('.drop[data-media-key=reference_audio_2]')).to_be_visible()
            expect(host.locator('.drop:visible')).to_have_count(1)
            expect(host.locator('.compact-media-tab[data-media-type=audio] .compact-count')).to_have_text('1 / 3')
            host.locator('#param_mode').select_option('image')
            expect(host.locator('.drop[data-media-key=source_video]')).to_be_hidden()
            expect(drop).to_be_hidden();host.locator('#param_mode').select_option('reference')
            host.locator('.compact-media-tab[data-media-type=image]').click()
            host.locator('.compact-uploads').scroll_into_view_if_needed()
            host.locator('.compact-uploads').screenshot(path=str(OUTPUT/'live-upload-panel.png'))
            host.locator('.remix-group[data-group="基本设置"]').scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT/'live-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            host.locator('.remix-group[data-group="基本设置"]').scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT/'live-mobile.png'));report['mobile_layout']=True
            page.goto(session['origin']+'/realism',wait_until='domcontentloaded',timeout=60000)
            host=page.locator('.page-host:not([hidden])')
            expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe',timeout=30000)
            expect(host.locator('.drop:visible')).to_have_count(1)
            expect(host.locator('.creation-scroll input[type=checkbox]:visible')).to_have_count(0)
            for key in ('person','clothing'):
                drop=host.locator('.drop[data-media-key='+key+']');expect(drop).to_be_visible()
                drop.locator('input[type=file]').set_input_files({'name':'jt-layout-check.png','mimeType':'image/png','buffer':png})
                expect(drop.locator('..').locator('.upload-status')).to_contain_text('已上传',timeout=180000)
            expect(host.locator('.compact-count')).to_have_text('2 / 2')
            host.get_by_role('button',name='使用图二参考图',exact=True).click()
            expect(host.locator('.compact-count')).to_have_text('1 / 1')
            expect(host.locator('.drop[data-media-key=person]')).to_be_visible()
            host.locator('.compact-uploads').screenshot(path=str(OUTPUT/'live-image-upload-panel.png'))
            report['image_editor_progression_and_buttons']=True
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
