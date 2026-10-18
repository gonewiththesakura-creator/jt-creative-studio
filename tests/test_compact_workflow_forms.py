"""Packaged browser checks: one slot, capacity counters, progressive uploads, real buttons."""
import base64
import io
import json
from pathlib import Path
import pytest
from PIL import Image
from playwright.sync_api import expect
from test_app_shell import browser,serve_page,current

ROOT=Path(__file__).resolve().parents[1]
WORKFLOWS=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['workflows']


def setup(page):
    errors=[];uploads=[];submissions=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    serve_page(page,block_scene=True)
    page.route('**/api/workflows',lambda route:route.fulfill(json=WORKFLOWS))
    page.route('**/api/*-queue',lambda route:route.fulfill(json={'jobs':[],'running':0,'waiting':0,'limit':2}))
    def upload(route):
        uploads.append(route.request.post_data_json);route.fulfill(json={'upload_id':str(len(uploads))})
    page.route('**/api/upload-start',upload)
    page.route('**/api/upload-chunk?*',lambda route:route.fulfill(json={'offset':len(route.request.post_data_buffer)}))
    page.route('**/api/upload-finish',lambda route:route.fulfill(json={'uploadToken':'token-'+route.request.post_data_json['upload_id']}))
    def submit(route):submissions.append(route.request.post_data_json);route.fulfill(json={'job_id':'a'*12})
    page.route('**/api/*-generate',submit)
    return errors,uploads,submissions


def picture():
    output=io.BytesIO();Image.new('RGB',(20,30),'navy').save(output,format='PNG');return output.getvalue()


def paste(drop):
    drop.locator('.paste-target').click()
    drop.evaluate("""(el,data)=>{const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'pasted.png',{type:'image/png'}));el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))}""",base64.b64encode(picture()).decode())


@pytest.mark.parametrize('width',[390,1440])
def test_video_progressive_slots_buttons_and_restore(browser,tmp_path,width):
    page=browser.new_page(viewport={'width':width,'height':1000},reduced_motion='reduce');errors,uploads,submitted=setup(page)
    try:
        page.goto('http://fixture.test/video');host=current(page);host.locator('button[data-wf=h3_remix_full]').click()
        expect(host.locator('.drop:visible')).to_have_count(1)
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('0 / 9')
        expect(host.locator('#param_prompt_optimizer_enabled')).to_have_count(0)
        expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
        toggle=host.locator('[data-toggle-for=param_second_pass]');expect(toggle).to_have_attribute('aria-pressed','true')
        toggle.click();expect(toggle).to_have_attribute('aria-pressed','false')
        expect(host.locator('.remix-group[data-group="二次采样设置"]')).to_be_hidden()
        toggle.click();expect(toggle).to_have_attribute('aria-pressed','true')
        paste(host.locator('.drop[data-media-key=reference_image]'))
        expect(host.locator('.drop[data-media-key=reference_image_2]')).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('1 / 9')
        paste(host.locator('.drop[data-media-key=reference_image_2]'))
        expect(host.locator('.drop[data-media-key=reference_image_3]')).to_be_visible()
        # Previously uploaded slots remain selectable and deletable without losing later uploads.
        host.locator('.compact-media-slot[data-slot=reference_image]').click()
        expect(host.locator('.drop[data-media-key=reference_image] img')).to_be_visible()
        host.locator('.drop[data-media-key=reference_image] .media-remove').click()
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('1 / 9')
        expect(host.locator('.compact-media-slot[data-slot=reference_image_2]')).to_be_visible()
        paste(host.locator('.drop[data-media-key=reference_image]'))
        expect(host.locator('.drop[data-media-key=reference_image_3]')).to_be_visible()
        host.locator('.compact-media-tab[data-media-type=video]').click()
        expect(host.locator('.drop[data-media-key=source_video]')).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        host.locator('.compact-media-tab[data-media-type=audio]').click()
        expect(host.locator('.drop[data-media-key=reference_audio]')).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        host.locator('#param_mode').select_option('image')
        expect(host.locator('.compact-media-tab[data-media-type=audio]')).to_be_hidden()
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('2 / 2')
        host.locator('[data-toggle-for=param_face_refine]').click()
        host.locator('#genBtn').click()
        expect(host.locator('#genStatus')).to_contain_text('已提交')
        assert submitted[0]['media']=={'reference_image':'token-3','reference_image_2':'token-2'}
        assert submitted[0]['params']['face_refine'] is False
        host.locator('button[data-wf=h3_edit_n]').click();expect(host.locator('.drop:visible')).to_have_count(1)
        host.locator('button[data-wf=h3_remix_full]').click()
        expect(host.locator('.compact-media-tab[data-media-type=image] .compact-count')).to_have_text('2 / 2')
        expect(host.locator('[data-toggle-for=param_face_refine]')).to_have_attribute('aria-pressed','false')
        host.locator('.compact-uploads').scroll_into_view_if_needed();page.screenshot(path=str(tmp_path/f'compact-video-{width}.png'))
        assert not errors
    finally:page.close()


@pytest.mark.parametrize('width',[390,1440])
def test_image_progression_optional_reference_and_submit(browser,tmp_path,width):
    page=browser.new_page(viewport={'width':width,'height':1000},reduced_motion='reduce');errors,uploads,submitted=setup(page)
    try:
        page.goto('http://fixture.test/realism');host=current(page)
        expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe')
        expect(host.locator('.drop:visible')).to_have_count(1)
        expect(host.locator('.compact-count')).to_have_text('0 / 2')
        expect(host.locator('.creation-scroll input[type=checkbox]:visible')).to_have_count(0)
        toggle=host.get_by_role('button',name='使用图二参考图',exact=True)
        toggle.click();expect(host.locator('.compact-count')).to_have_text('0 / 1')
        toggle.click();expect(host.locator('.compact-count')).to_have_text('0 / 2')
        paste(host.locator('.drop[data-media-key=person]'))
        expect(host.locator('.drop[data-media-key=clothing]')).to_be_visible()
        expect(host.locator('#generateBtn')).to_be_disabled()
        paste(host.locator('.drop[data-media-key=clothing]'))
        expect(host.locator('.compact-count')).to_have_text('2 / 2')
        expect(host.locator('#generateBtn')).to_be_enabled()
        host.locator('.compact-media-slot[data-slot=person]').click()
        host.locator('.drop[data-media-key=person] .media-remove').click()
        expect(host.locator('#generateBtn')).to_be_disabled()
        paste(host.locator('.drop[data-media-key=person]'))
        expect(host.locator('#generateBtn')).to_be_enabled()
        toggle.click();expect(host.locator('.compact-count')).to_have_text('1 / 1')
        expect(host.locator('.drop[data-media-key=person]')).to_be_visible()
        host.locator('#generateBtn').click()
        expect(host.locator('#generateStatus')).to_contain_text('已加入')
        assert submitted[0]['params']['use_clothing'] is False
        assert submitted[0]['media']=={'person':'token-3'}
        assert not errors
        host.locator('.compact-uploads').scroll_into_view_if_needed();page.screenshot(path=str(tmp_path/f'compact-image-{width}.png'))
    finally:page.close()


def test_all_catalog_workflows_start_with_at_most_one_upload(browser):
    page=browser.new_page(reduced_motion='reduce');errors,_,_=setup(page)
    try:
        page.goto('http://fixture.test/video');host=current(page)
        for workflow in [w for w in WORKFLOWS if w.get('kind')=='video']:
            host.locator('button[data-wf="'+workflow['id']+'"]').click()
            expect(host.locator('.drop:visible')).to_have_count(1 if workflow.get('rh_media') else 0)
            expect(host.locator('#wfForm input[type=checkbox]:visible')).to_have_count(0)
        page.goto('http://fixture.test/realism');host=current(page)
        for workflow in [w for w in WORKFLOWS if w.get('kind') in ('ai_app','rh_workflow')]:
            host.locator('#workflowSelect').select_option(workflow['id'])
            expect(host.locator('.drop:visible')).to_have_count(1 if workflow.get('rh_media') else 0)
            expect(host.locator('.creation-scroll input[type=checkbox]:visible')).to_have_count(0)
        assert not errors
    finally:page.close()


@pytest.mark.parametrize('route,first,second,retry',[
    ('video','reference_image','reference_image_2','继续上传'),
    ('realism','person','clothing','重试上传'),
])
def test_failed_upload_stays_visible_until_successful_retry(browser,route,first,second,retry):
    page=browser.new_page(reduced_motion='reduce');errors,uploads,_=setup(page)
    attempts=[]
    def finish(request):
        attempts.append(1)
        if len(attempts)==1:return request.fulfill(status=400,json={'error':'test upload failed'})
        request.fulfill(json={'uploadToken':'retry-token'})
    page.route('**/api/upload-finish',finish)
    try:
        page.goto('http://fixture.test/'+route);host=current(page)
        if route=='video':host.locator('button[data-wf=h3_remix_full]').click()
        drop=host.locator('.drop[data-media-key='+first+']');paste(drop)
        button=host.get_by_role('button',name=retry,exact=True)
        expect(button).to_be_visible()
        expect(drop).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        expect(host.locator('.drop[data-media-key='+second+']')).to_be_hidden()
        button.click()
        expect(host.locator('.drop[data-media-key='+second+']')).to_be_visible()
        expect(host.locator('.drop:visible')).to_have_count(1)
        assert len(attempts)==2 and not errors
    finally:page.close()


def test_independent_face_reference_does_not_require_filling_nine_optional_slots(browser):
    page=browser.new_page(reduced_motion='reduce');errors,uploads,_=setup(page)
    try:
        page.goto('http://fixture.test/video');host=current(page)
        host.locator('button[data-wf=h3_remix_full]').click()
        host.locator('.remix-group[data-group="人脸精修设置"] > summary').click()
        host.locator('[data-toggle-for=param_use_face_reference]').click()
        host.locator('.compact-media-slot[data-slot=face_reference]').click()
        expect(host.locator('.drop:visible')).to_have_count(1)
        paste(host.locator('.drop[data-media-key=face_reference]'))
        expect(host.locator('.drop[data-media-key=reference_image]')).to_be_visible()
        assert uploads[0]['input_key']=='face_reference' and not errors
    finally:page.close()
