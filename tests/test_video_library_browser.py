from test_app_shell import browser, serve_page
from playwright.sync_api import expect


def test_details_hover_scroll_history_and_pending_favorite(browser):
    page=browser.new_page(viewport={'width':1440,'height':1000})
    serve_page(page,block_scene=True)
    job=dict(id='v',workflow='retired-workflow',wf_name='旧视频工作流',status='done',created=100,params={'prompt':'保持自然光。\n'*100,'lora_1_model':'minimax-n4','lora_1_strength':.7},images=[{'url':'/result.mp4','file_type':'mp4'}])
    page.route('**/api/video-queue',lambda r:r.fulfill(json={'jobs':[job],'running':0,'waiting':0,'limit':2}))
    page.route('**/api/job/*',lambda r:r.fulfill(json=job))
    page.route('**/api/jobs?*',lambda r:r.fulfill(json=[dict(job,id=str(i)) for i in range(20)] if 'before=' not in r.request.url else [dict(job,id='older')]))
    fav=dict(id='f',job_id='v',image_index=0,style_id='video',archive_status='saving')
    page.route('**/api/favorites',lambda r:r.fulfill(status=202 if r.request.method=='POST' else 200,json=fav if r.request.method=='POST' else [fav]))
    try:
        page.goto('http://fixture.test/video')
        page.wait_for_load_state('networkidle')
        thumb=page.locator('.gallery-thumb').first;thumb.hover()
        page.wait_for_timeout(1000)
        expect(page.locator('#galleryJobHint')).to_be_hidden()
        hint=page.locator('#galleryJobHint');expect(hint).to_be_visible()
        hint.hover();page.wait_for_timeout(400);expect(hint).to_be_visible()
        # mouse.wheel returns before the compositor applies the scroll; wait for it.
        page.mouse.wheel(0,600)
        page.wait_for_function("document.querySelector('.page-host:not([hidden])').shadowRoot.getElementById('galleryJobHint').scrollTop>0",timeout=3000)
        page.locator('#galleryMain .gallery-actions button').click()
        expect(page.locator('#galleryMain .gallery-actions button')).to_have_text('已加入收藏 · 后台保存中')
        page.locator('#favOpen').first.click();expect(page.locator('#favList')).to_contain_text('后台保存中')
        page.locator('#favOverlay .close').click()
        page.locator('#histOpen').first.click();expect(page.locator('#histList .job')).to_have_count(20)
        page.get_by_role('button',name='加载更早记录').click();expect(page.locator('#histList .job')).to_have_count(21)
        page.locator('#histList .job').last.get_by_role('button',name='播放结果').click()
        # 2026-11-12: the result plays in the shell lightbox above the library, which stays open
        # (it used to close the library and jump back to the workspace).
        expect(page.locator('#jtLightbox .lb-stage video')).to_have_count(1)
        expect(page.locator('#histOverlay')).to_have_class('library-overlay open')
        page.keyboard.press('Escape')
        expect(page.locator('#jtLightbox')).to_be_hidden()
        expect(page.locator('#histOverlay')).to_have_class('library-overlay open')
    finally:page.close()
