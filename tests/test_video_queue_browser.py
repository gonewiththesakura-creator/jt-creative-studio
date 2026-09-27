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
        card.locator('.task-tile').hover()
        card.get_by_role('button',name='编辑参数').click()
        dialog = page.locator('#queueEditor')
        expect(dialog).to_be_visible()
        dialog.locator('[name="prompt"]').fill('新的提示词')
        dialog.get_by_role('button',name='保存修改').click()
        expect(dialog).to_have_count(0)
        assert actions[-1]['params']['prompt'] == '新的提示词'
        card.locator('.task-tile').hover()
        card.get_by_role('button',name='下移').click()
        card.locator('.task-tile').hover()
        expect(card.get_by_role('button',name='取消排队')).to_be_enabled()
        card.get_by_role('button',name='取消排队').click()
        expect(card).to_contain_text('已取消排队')
        page.screenshot(path=str(tmp_path/'video-queue.png'), full_page=True)
        assert not [r for r in requests if r[1].startswith('/api/job/')]
        assert [a['action'] for a in actions] == ['edit','down','cancel']
    finally: page.close()


def test_completed_results_auto_appear_without_reloading_player(browser, tmp_path):
    page=browser.new_page(viewport={'width':1440,'height':1000})
    serve_page(page,block_scene=True)
    jobs=[dict(id='playing',workflow='fixture-video',wf_name='已完成的视频',status='done',media={'source_video':'原视频.mp4'},rh_coins=99),
          dict(id='pending',workflow='fixture-video',wf_name='等待中的视频',status='queued',position=1,editable=True,params={'prompt':'保持动作'},media={}),
          dict(id='failed',workflow='fixture-video',wf_name='失败的视频',status='error',error='上游返回失败',media={})]
    detail_requests=[]
    # Locally encoded media exercises a real first frame/player without provider calls.
    import base64
    sample=page.evaluate('''async()=>{const c=document.createElement('canvas');c.width=320;c.height=180;const x=c.getContext('2d'),g=x.createLinearGradient(0,0,320,180);g.addColorStop(0,'#638ca2');g.addColorStop(1,'#202d46');x.fillStyle=g;x.fillRect(0,0,320,180);x.fillStyle='#e7d3aa';x.beginPath();x.arc(240,50,24,0,7);x.fill();x.fillStyle='#162a35';x.beginPath();x.moveTo(0,180);x.lineTo(125,55);x.lineTo(250,180);x.fill();const png=c.toDataURL('image/png').split(',')[1],stream=c.captureStream(10),rec=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];rec.ondataavailable=e=>parts.push(e.data);const done=new Promise(r=>rec.onstop=r);rec.start();await new Promise(r=>setTimeout(r,350));rec.stop();await done;stream.getTracks().forEach(t=>t.stop());const bytes=new Uint8Array(await new Blob(parts).arrayBuffer());return {png,video:btoa(String.fromCharCode(...bytes))}}''')
    page.route('**/sample.mp4',lambda r:r.fulfill(body=base64.b64decode(sample['video']),content_type='video/webm'))
    page.route('**/sample.png',lambda r:r.fulfill(body=base64.b64decode(sample['png']),content_type='image/png'))
    def detail(route):
        key=route.request.url.rsplit('/',1)[-1];detail_requests.append(key)
        route.fulfill(json=dict(id=key,images=[dict(url='/sample.'+('mp4' if key=='playing' else 'png'),file=key,file_type='video' if key=='playing' else 'image')]))
    page.route('**/api/video-queue',lambda r:r.fulfill(json=dict(jobs=jobs,running=0,waiting=1,limit=2)))
    page.route('**/api/job/*',detail)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto('http://fixture.test/video')
        expect(page.locator('#galleryMain video')).to_have_count(1)
        page.wait_for_function("document.querySelector('.page-host[data-page=\"/video\"]').shadowRoot.querySelector('#galleryMain video')?.readyState>=2")
        expect(page.locator('[data-group=done] .task-card')).to_have_count(1)
        expect(page.locator('[data-group=active] .task-card')).to_have_count(1)
        expect(page.locator('[data-group=other] .task-card')).to_have_count(1)
        page.locator('#galleryMain video').evaluate("el=>el.dataset.retained='yes'")
        jobs[1].update(status='done',editable=False)
        expect(page.locator('.gallery-thumb')).to_have_count(2,timeout=10000)
        expect(page.locator('#galleryMain video')).to_have_attribute('data-retained','yes')
        expect(page.locator('#taskList video')).to_have_count(0)
        assert detail_requests==['playing','pending']
        page.locator('#galleryNext').click()
        expect(page.locator('#galleryMain img')).to_have_count(1)
        expect(page.locator('#galleryMain img')).to_have_js_property('naturalWidth',320)
        page.locator('#galleryPrev').click()
        expect(page.locator('#galleryMain video')).to_have_count(1)
        box=page.locator('#galleryMain').bounding_box();nav=page.locator('#galleryNext').bounding_box()
        assert box['y']<nav['y']<box['y']+box['height']
        page.locator('[data-job-id=failed] .task-tile').hover()
        expect(page.locator('[data-job-id=failed] .task-details')).to_be_visible()
        page.screenshot(path=str(tmp_path/'task-gallery-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-job-id=failed] .task-tile').click()
        expect(page.locator('[data-job-id=failed] .task-details')).to_be_visible()
        assert page.locator('.page-host[data-page="/video"]').evaluate('el=>el.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'task-gallery-mobile.png'),full_page=True)
        assert not errors
    finally:page.close()


def test_reference_drop_paste_and_real_first_frame(browser):
    page=browser.new_page()
    serve_page(page,block_scene=True)
    uploads=[]
    page.route('**/api/workflows',lambda r:r.fulfill(json=[dict(id='ref-video',kind='video',name='参考图测试',
        rh_media={'reference_image':dict(type='image',label='参考图',required=True)},rh_params={})]))
    def upload(route):
        uploads.append(route.request.url)
        route.fulfill(json={'uploadToken':'upl_fake'})
    page.route('**/api/upload-start',lambda r:(uploads.append(r.request.post_data_json),r.fulfill(json={'upload_id':str(len(uploads))})))
    page.route('**/api/upload-chunk?*',lambda r:r.fulfill(json={'offset':len(r.request.post_data_buffer)}))
    page.route('**/api/upload-finish',lambda r:r.fulfill(json={'status':'done','uploadToken':'upl_fake'}))
    try:
        page.goto('http://fixture.test/video')
        drop=page.locator('.drop')
        expect(drop).to_be_visible()
        for event in ['drop','paste']:
            drop.locator('.fn').evaluate('(el)=>el.textContent=""')
            drop.evaluate('''(el,type)=>{const c=document.createElement('canvas');c.width=2;c.height=2;c.toBlob(blob=>{const dt=new DataTransfer();dt.items.add(new File([blob],'ref.png',{type:'image/png'}));(type==='drop'?el:document.body).dispatchEvent(type==='drop'?new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}):new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}))})}''',event)
            expect(drop.locator('.fn')).to_contain_text('已上传')
        assert len(uploads)==2
        # Real browser-encoded video: extraction must produce a bounded JPEG,
        # without playing a video in the queue or calling any provider.
        result=page.evaluate('''async()=>{const host=document.querySelector('.page-host[data-page="/video"]'),root=host.shadowRoot,canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;const ctx=canvas.getContext('2d');ctx.fillStyle='red';ctx.fillRect(0,0,320,180);const stream=canvas.captureStream(10),rec=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];rec.ondataavailable=e=>parts.push(e.data);const done=new Promise(r=>rec.onstop=r);rec.start();await new Promise(r=>setTimeout(r,250));rec.stop();await done;stream.getTracks().forEach(t=>t.stop());const file=new File(parts,'first.webm',{type:'video/webm'});const source=await(await fetch('/static/video.html')).text();const start=source.indexOf('const videoThumbnails='),end=source.indexOf('function persistTaskThumbnails');const extract=new Function(source.slice(start,end)+';return prepareVideoThumbnail')();const data=await extract(file);const image=new Image();image.src='data:image/jpeg;base64,'+data;await image.decode();return {width:image.width,height:image.height,bytes:atob(data).length}}''')
        assert result['width']<=160 and result['height']<=90 and result['bytes']<=32768
    finally: page.close()
