import json
from test_app_shell import browser, serve_page
from playwright.sync_api import expect


def test_queue_lightweight_editor_and_actions(browser, tmp_path):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    requests = serve_page(page, block_scene=True)
    jobs = [dict(id=str(i), workflow='fixture-video', wf_name='视频工作流',
                 status='running' if i < 2 else 'queued', editable=i >= 2,
                 position=i-1, media={'source_video': '舞蹈素材-'+str(i)+'.mp4'},
                 params={'prompt':'保持动作'}, queue_revision=0) for i in range(30)]
    actions = []
    jobs[2]['thumbnails']={'source_video':'/api/video-thumbnail/abcdef123456/'+'a'*32+'.jpg'}
    import base64
    from test_video_thumbnails import jpeg
    page.route('**/api/video-thumbnail/**',lambda r:r.fulfill(body=base64.b64decode(jpeg()),content_type='image/jpeg'))
    def queue(route):
        if route.request.method == 'POST':
            body = route.request.post_data_json
            actions.append(body)
            j = next(j for j in jobs if j['id'] == body['job_id'])
            if body['action'] == 'edit': j['params'] = body['params']
            if body['action'] == 'cancel': j.update(status='cancelled', editable=False)
            return route.fulfill(json={'ok': True})
        return route.fulfill(json={'jobs':jobs,'running':2,'waiting':28,'limit':2})
    page.route('**/api/video-queue', queue)
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('.task-card')).to_have_count(30)
        expect(page.locator('#taskList video')).to_have_count(0)
        expect(page.locator('#taskList img')).to_have_count(1)
        expect(page.locator('#taskList img')).to_have_attribute('loading','lazy')
        card = page.locator('[data-job-id="2"]')
        expect(card).to_contain_text('舞蹈素材-2.mp4')
        card.get_by_role('button',name='编辑参数').click()
        dialog = page.locator('#queueEditor')
        expect(dialog).to_be_visible()
        dialog.locator('[name="prompt"]').fill('新的提示词')
        dialog.get_by_role('button',name='保存修改').click()
        expect(dialog).to_have_count(0)
        assert actions[-1]['params']['prompt'] == '新的提示词'
        card.get_by_role('button',name='下移').click()
        expect(card.get_by_role('button',name='取消排队')).to_be_enabled()
        card.get_by_role('button',name='取消排队').click()
        expect(card).to_contain_text('已取消排队')
        page.screenshot(path=str(tmp_path/'video-queue.png'), full_page=True)
        assert not [r for r in requests if r[1].startswith('/api/job/')]
        assert [a['action'] for a in actions] == ['edit','down','cancel']
    finally: page.close()


def test_reference_drop_paste_and_real_first_frame(browser):
    page=browser.new_page()
    serve_page(page,block_scene=True)
    uploads=[]
    page.route('**/api/workflows',lambda r:r.fulfill(json=[dict(id='ref-video',kind='video',name='参考图测试',
        rh_media={'reference_image':dict(type='image',label='参考图',required=True)},rh_params={})]))
    def upload(route):
        uploads.append(route.request.url)
        route.fulfill(json={'uploadToken':'upl_fake'})
    page.route('**/api/upload?*',upload)
    try:
        page.goto('http://fixture.test/video')
        drop=page.locator('.drop')
        expect(drop).to_be_visible()
        for event in ['drop','paste']:
            drop.evaluate('''(el,type)=>{const c=document.createElement('canvas');c.width=2;c.height=2;c.toBlob(blob=>{const dt=new DataTransfer();dt.items.add(new File([blob],'ref.png',{type:'image/png'}));(type==='drop'?el:document.body).dispatchEvent(type==='drop'?new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}):new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}))})}''',event)
            expect(drop.locator('.fn')).to_contain_text('已上传')
        assert len(uploads)==2
        # Real browser-encoded video: extraction must produce a bounded JPEG,
        # without playing a video in the queue or calling any provider.
        result=page.evaluate('''async()=>{const host=document.querySelector('.page-host[data-page="/video"]'),root=host.shadowRoot,canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;const ctx=canvas.getContext('2d');ctx.fillStyle='red';ctx.fillRect(0,0,320,180);const stream=canvas.captureStream(10),rec=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];rec.ondataavailable=e=>parts.push(e.data);const done=new Promise(r=>rec.onstop=r);rec.start();await new Promise(r=>setTimeout(r,250));rec.stop();await done;stream.getTracks().forEach(t=>t.stop());const file=new File(parts,'first.webm',{type:'video/webm'});const source=await(await fetch('/static/video.html')).text();const start=source.indexOf('const videoThumbnails='),end=source.indexOf('function persistTaskThumbnails');const extract=new Function(source.slice(start,end)+';return prepareVideoThumbnail')();const data=await extract(file);const image=new Image();image.src='data:image/jpeg;base64,'+data;await image.decode();return {width:image.width,height:image.height,bytes:atob(data).length}}''')
        assert result['width']<=160 and result['height']<=90 and result['bytes']<=32768
    finally: page.close()
