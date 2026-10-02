from test_app_shell import browser, serve_page
from playwright.sync_api import expect


def test_running_cancel_icon_and_pending_ui(browser):
    page=browser.new_page(viewport={'width':1440,'height':1000})
    serve_page(page,block_scene=True)
    job=dict(id='running',workflow='fixture-video',status='running',cancellable=True,editable=False,queue_revision=0,media={},params={})
    posts=[]
    def queue(route):
        if route.request.method=='POST':
            posts.append(route.request.post_data_json)
            job.update(cancel_requested=True,cancel_note='等待云端确认取消')
            return route.fulfill(json={'ok':True})
        return route.fulfill(json={'jobs':[job],'running':1,'waiting':0,'limit':2})
    page.route('**/api/video-queue',queue)
    try:
        page.goto('http://fixture.test/video')
        card=page.locator('[data-job-id="running"]')
        card.locator('.task-tile').hover()
        cancel=card.get_by_role('button',name='取消生成',exact=True)
        expect(cancel).to_be_visible()
        expect(card.get_by_role('button',name='编辑参数')).to_be_hidden()
        cancel.click()
        expect(card.locator('.task-badge')).to_have_text('取消中 · 核对停止')
        card.locator('.task-tile').hover()
        expect(card.get_by_role('button',name='正在取消',exact=True)).to_be_disabled()
        assert len(posts)==1 and posts[0]['action']=='cancel_running'
        expect(page.locator('#taskCount')).to_contain_text('执行 1/2')
    finally:page.close()
