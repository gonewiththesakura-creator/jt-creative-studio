import json
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_app_shell import browser, serve_page, current

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['workflows']
if isinstance(WORKFLOWS, dict): WORKFLOWS=list(WORKFLOWS.values())


@pytest.mark.parametrize('width', [390,1440])
@pytest.mark.parametrize('use_clothing', [True,False])
def test_image_editor_upload_paste_queue_redo_and_remove(browser, tmp_path, width, use_clothing):
    page=browser.new_page(viewport={'width':width,'height':1000}, reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    serve_page(page,block_scene=True)
    page.route('**/api/workflows',lambda route:route.fulfill(json=WORKFLOWS))
    jobs=[];submitted=[];uploads=[]
    page.route('**/api/image-edit-queue',lambda route:route.fulfill(json={'jobs':jobs,'running':0,'waiting':len(jobs),'limit':2}))
    def upload(route):
        uploads.append(route.request.post_data_json)
        route.fulfill(json={'upload_id':str(len(uploads))})
    page.route('**/api/upload-start',upload)
    page.route('**/api/upload-chunk?*',lambda route:route.fulfill(json={'offset':len(route.request.post_data_buffer)}))
    page.route('**/api/upload-finish',lambda route:route.fulfill(json={'uploadToken':'token-'+route.request.post_data_json['upload_id']}))
    def generate(route):
        payload=route.request.post_data_json;submitted.append(payload)
        if payload.get('redo_job_id'):return route.fulfill(json={'job_id':'b'*12})
        jobs.append({'id':'a'*12,'workflow':'qwen21_wardrobe','wf_name':'Qwen 2.1 · 固定人物换装','status':'queued','position':1,'editable':True,'revision':0,'media':{'person':'person.png','clothing':'dress.png'},'params':payload['params'],'created':1,'style_id':'realism','images':[]})
        route.fulfill(json={'job_id':'a'*12})
    page.route('**/api/image-edit-generate',generate)
    try:
        page.goto('http://fixture.test/realism')
        host=current(page)
        expect(host.locator('#workflowSelect')).to_have_value('qwen21_wardrobe')
        expect(host.locator('.drop')).to_have_count(2)
        page.evaluate("""() => {const b=document.createElement('canvas');b.width=20;b.height=20; b.getContext('2d').fillRect(0,0,20,20);window.testPng=b.toDataURL('image/png').split(',')[1]}""")
        import base64
        image=base64.b64decode(page.evaluate('window.testPng'))
        host.locator('.drop[data-media-key="person"] input[type=file]').set_input_files({'name':'person.png','mimeType':'image/png','buffer':image})
        expect(host.locator('.upload-status.ok')).to_have_count(1)
        toggle=host.get_by_role('button',name='使用图二参考图',exact=True)
        expect(toggle).to_have_attribute('aria-pressed','true')
        toggle.click()
        expect(host.locator('.drop[data-media-key="clothing"]')).to_be_hidden()
        expect(host.locator('#generateBtn')).to_be_enabled()
        toggle.click()
        host.locator('.compact-media-slot[data-slot=clothing]').click()
        expect(host.locator('.drop[data-media-key="clothing"]')).to_be_visible()
        expect(host.locator('#generateBtn')).to_be_disabled()
        host.locator('.drop[data-media-key="clothing"] .paste-target').click()
        host.locator('.drop[data-media-key="clothing"]').evaluate("""(el,base64) => {const file=new File([Uint8Array.from(atob(base64),c=>c.charCodeAt(0))],'dress.png',{type:'image/png'});const dt=new DataTransfer();dt.items.add(file);el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))}""",page.evaluate('window.testPng'))
        expect(host.locator('.upload-status.ok')).to_have_count(2)
        assert len(uploads)==2
        remove=host.locator('.drop[data-media-key="person"] .media-remove')
        assert remove.text_content()==''
        host.locator('.compact-media-slot[data-slot=person]').click()
        remove.click()
        expect(host.locator('#generateBtn')).to_be_disabled()
        host.locator('.drop[data-media-key="person"] input[type=file]').set_input_files({'name':'person.png','mimeType':'image/png','buffer':image})
        expect(host.locator('#generateBtn')).to_be_enabled()
        toggle.click()
        expect(host.locator('.drop[data-media-key="clothing"]')).to_be_hidden()
        toggle.click()
        host.locator('.compact-media-slot[data-slot=clothing]').click()
        expect(host.locator('.drop[data-media-key="clothing"] .local-image-preview')).to_be_visible()
        expect(host.locator('#generateBtn')).to_be_enabled()
        if not use_clothing:toggle.click()
        host.locator('#generateBtn').click()
        expect(host.locator('.task-card')).to_have_count(1)
        assert submitted[0]['media']==({'person':'token-3','clothing':'token-2'} if use_clothing else {'person':'token-3'})
        assert submitted[0]['params']['use_clothing'] is use_clothing
        expect(host.locator('.task-badge')).to_contain_text('排队')
        jobs[0].update(status='error',editable=False,redoable=True,provider_status='FAILED',error='offline failure')
        page.reload()
        expect(current(page).locator('.task-redo')).to_have_count(1)
        current(page).locator('.task-card').hover()
        with page.expect_request('**/api/image-edit-generate'):
            current(page).locator('.task-redo-quick').click()
        assert submitted[-1]['redo_job_id']=='a'*12
        assert errors==[]
        page.screenshot(path=str(tmp_path/f'image-edit-{width}.png'))
    finally:page.close()


def test_every_video_workflow_has_shared_upload_and_retains_parameters(browser):
    page=browser.new_page(reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    serve_page(page,block_scene=True)
    page.route('**/api/workflows',lambda route:route.fulfill(json=WORKFLOWS))
    try:
        page.goto('http://fixture.test/video')
        host=current(page)
        for workflow in [w for w in WORKFLOWS if w.get('kind')=='video']:
            host.locator('#wfSwitch button[data-wf="'+workflow['id']+'"]').click()
            expect(host.locator('.drop')).to_have_count(len(workflow.get('rh_media',{})))
            expect(host.locator('.paste-target')).to_have_count(sum(m.get('type')=='image' for m in workflow.get('rh_media',{}).values()))
            for remove in host.locator('.media-remove').all():assert remove.text_content()==''
        ids=[w['id'] for w in WORKFLOWS if w.get('kind')=='video' and 'prompt' in w.get('rh_params',{})]
        host.locator('#wfSwitch button[data-wf="'+ids[0]+'"]').click()
        host.locator('#param_prompt').fill('keep this prompt')
        host.locator('#wfSwitch button[data-wf="'+ids[1]+'"]').click()
        host.locator('#wfSwitch button[data-wf="'+ids[0]+'"]').click()
        expect(host.locator('#param_prompt')).to_have_value('keep this prompt')
        assert errors==[]
    finally:page.close()
