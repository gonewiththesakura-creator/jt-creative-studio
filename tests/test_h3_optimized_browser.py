"""New workflow in the packaged UI, with generation intercepted."""
import base64
import io
import json
from pathlib import Path

from PIL import Image
import pytest
from playwright.sync_api import expect
from test_app_shell import browser, serve_page, current

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('width',[390,1440])
def test_optimized_upload_controls_queue_and_redo(browser,tmp_path,width):
    page=browser.new_page(viewport={'width':width,'height':1000},reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    serve_page(page,block_scene=True)
    page.route('**/api/workflows',lambda r:r.fulfill(json=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['workflows']))
    jobs=[];submitted=[];uploads=[]
    page.route('**/api/video-queue',lambda r:r.fulfill(json={'jobs':jobs,'running':0,'waiting':len(jobs),'limit':2}))
    def upload(route):
        uploads.append(route.request.post_data_json);route.fulfill(json={'upload_id':str(len(uploads))})
    page.route('**/api/upload-start',upload)
    page.route('**/api/upload-chunk?*',lambda r:r.fulfill(json={'offset':len(r.request.post_data_buffer)}))
    page.route('**/api/upload-finish',lambda r:r.fulfill(json={'uploadToken':'token-'+r.request.post_data_json['upload_id']}))
    def generate(route):
        payload=route.request.post_data_json;submitted.append(payload)
        if not payload.get('redo_job_id'):
            jobs.append(dict(id='a'*12,workflow='h3_reference_optimized',wf_name='多参考生视频（优化版）',status='queued',position=1,editable=True,revision=0,
                media={'reference_image':'person.png'},params=payload['params'],prompt=payload['prompt'],created=1,style_id='video',images=[]))
        route.fulfill(json={'job_id':('b' if payload.get('redo_job_id') else 'a')*12})
    page.route('**/api/video-generate',generate)
    try:
        page.goto('http://fixture.test/video');host=current(page)
        host.locator('button[data-wf=h3_reference_optimized]').click()
        expect(host.locator('.drop:visible')).to_have_count(1)
        expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('0 / 9')
        expect(host.locator('.compact-media-tab[data-media-type=video] .compact-count')).to_have_text('0 / 3')
        expect(host.locator('.compact-media-tab[data-media-type=audio] .compact-count')).to_have_text('0 / 3')
        expect(host.locator('#param_second_pass')).not_to_be_checked()
        expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_hidden()
        host.locator('[data-toggle-for=param_second_pass]').click()
        group=host.locator('.remix-group[data-group="二次采样设置"]');expect(group).to_be_visible()
        group.locator('summary').click();host.locator('#param_second_scale').fill('2')
        host.locator('#param_second_scale').dispatch_event('change')
        output=io.BytesIO();Image.new('RGB',(30,40),'navy').save(output,format='PNG')
        drop=host.locator('[data-media-key=reference_image]');drop.locator('.paste-target').click()
        drop.evaluate("""(el,data)=>{const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'clip.png',{type:'image/png'}));el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))}""",base64.b64encode(output.getvalue()).decode())
        expect(drop.locator('.fn')).to_contain_text('已上传')
        expect(host.locator('[data-media-key=reference_image_2]')).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        assert uploads[0]['input_key']=='reference_image'
        host.locator('.remix-group[data-group="LoRA 设置"] > summary').click()
        host.locator('[data-toggle-for=param_lora_1_enabled]').click()
        host.locator('#param_lora_2_strength').fill('0.3');host.locator('#param_lora_2_strength').dispatch_event('change')
        host.locator('button[data-wf=h3_edit_n]').click()
        host.locator('button[data-wf=h3_reference_optimized]').click()
        expect(host.locator('#param_second_pass')).to_be_checked()
        expect(host.locator('#param_second_scale')).to_have_value('2')
        expect(host.locator('[data-media-key=reference_image] .fn')).to_contain_text('已上传')
        host.locator('#genBtn').click();expect(host.locator('.task-badge')).to_contain_text('排队')
        assert len(submitted)==1
        payload=submitted[0]
        assert payload['media']=={'reference_image':'token-1'}
        assert payload['params']['second_pass'] is True and payload['params']['second_scale']==2
        assert payload['params']['lora_1_enabled'] is False and payload['params']['lora_2_strength']==.3
        jobs[0].update(status='error',editable=False,redoable=True,provider_status='FAILED',error='offline failure')
        page.reload();host=current(page);expect(host.locator('.task-redo')).to_have_count(1)
        host.locator('.task-card').hover()
        with page.expect_request('**/api/video-generate'):host.locator('.task-redo-quick').click()
        assert submitted[-1]['redo_job_id']=='a'*12
        host.locator('button[data-wf=h3_reference_optimized]').click()
        host.locator('.compact-uploads').screenshot(path=str(tmp_path/f'uploads-{width}.png'))
        host.locator('.remix-group[data-group="基本设置"]').scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path/f'optimized-{width}.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
    finally:page.close()
