from test_app_shell import browser, serve_page
from playwright.sync_api import expect


def test_prompt_presets_survive_reload_without_submitting(browser, tmp_path):
    page=browser.new_page(viewport={'width':1440,'height':1000})
    requests=serve_page(page,block_scene=True)
    page.route('**/api/video-queue',lambda r:r.fulfill(json={'jobs':[],'running':0,'waiting':0,'limit':2}))
    try:
        page.goto('http://fixture.test/video')
        box=page.locator('.prompt-presets')
        expect(box.locator('.prompt-preset-slots button')).to_have_count(6)
        page.locator('#param_prompt').fill('保留镜头运动，使用自然光')
        box.get_by_role('textbox',name='预设名称').fill('自然光')
        box.get_by_role('button',name='保存当前').click()
        expect(box).to_contain_text('已保存')
        page.reload()
        box=page.locator('.prompt-presets')
        expect(box.locator('.prompt-preset-slots button').first).to_have_text('自然光')
        page.locator('#param_prompt').fill('其他内容')
        box.get_by_role('button',name='套用',exact=True).click()
        expect(page.locator('#param_prompt')).to_have_value('保留镜头运动，使用自然光')
        box.locator('.prompt-preset-slots button').nth(1).click()
        expect(box.get_by_role('button',name='套用',exact=True)).to_be_disabled()
        box.locator('.prompt-preset-slots button').first.click()
        page.once('dialog',lambda d:d.dismiss())
        box.get_by_role('button',name='清空',exact=True).click()
        expect(box.get_by_role('button',name='套用',exact=True)).to_be_enabled()
        page.screenshot(path=str(tmp_path/'presets.png'),full_page=True)
        page.once('dialog',lambda d:d.accept())
        box.get_by_role('button',name='清空',exact=True).click()
        expect(page.locator('#param_prompt')).to_have_value('保留镜头运动，使用自然光')
        page.reload()
        expect(page.locator('.prompt-presets').get_by_role('button',name='套用',exact=True)).to_be_disabled()
        assert not [r for r in requests if r[0]=='POST']
    finally:page.close()
