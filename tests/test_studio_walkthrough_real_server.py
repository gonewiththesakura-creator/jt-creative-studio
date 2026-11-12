"""Studio v2 walkthrough through the real server and the real built frontend (2026-11-11).

No route is mocked. Only the provider worker (`run_job`) is replaced, so a submission ends the
way a real one can: an error whose provider outcome is unconfirmed (timeout, restart). This is
the path that used to leave "当前套餐并发已满" on every later submission.
"""
import os
import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_app_shell import browser
from test_membership_http import membership_env
from test_server_review_regressions import panel

SHOTS = os.environ.get('JT_WALKTHROUGH_SHOTS')


@pytest.fixture
def site(membership_env, monkeypatch):
    env = membership_env
    env.gateway.login_mode = 'access_code'
    env.gateway.origin = 'http://127.0.0.1:%d' % env.httpd.server_address[1]
    admin = env.users['admin']['id']
    plan = env.store.save_plan(admin, {'name': 'Monthly', 'duration_days': 30, 'image_units': 10, 'video_units': 3,
                                       'max_concurrent': 1, 'backends': ['cloud', 'api', 'local']})
    env.member_code = env.store.issue_access_codes(admin, plan['id'])[0]['code']
    rotated = env.store.rotate_access_code(admin, admin, 'fixture administrator code')
    env.admin_code = rotated['code'] if isinstance(rotated.get('code'), str) else rotated['code']['code']
    env.started = []

    def unconfirmed_timeout(job):
        env.started.append(job['id'])
        with env.panel._lock_jobs:
            job.update(status='error', error='comfyui timeout after 1800s', submit_started=time.time(),
                       comfy_prompt_id='fixture-prompt', elapsed=1.0)
            env.panel.save_jobs()

    monkeypatch.setattr(env.panel, 'run_job', unconfirmed_timeout)
    return env


def shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f'{name}.png'), full_page=False)


def sign_in(browser, site, code):
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
    page = context.new_page()
    page.problems = []
    page.on('console', lambda m: m.type == 'error' and page.problems.append('console: ' + m.text))
    page.on('pageerror', lambda e: page.problems.append('pageerror: ' + str(e)))
    page.on('response', lambda r: r.status >= 500 and page.problems.append(f'{r.status} {r.url}'))
    page.goto(site.gateway.origin + '/')
    shot(page, '00-login')
    page.locator('#accountLoginCode').fill(code)
    page.locator('#accountLogin').click()
    expect(page.locator('#accountGate')).to_be_hidden(timeout=15000)
    return context, page


def test_unconfirmed_failure_no_longer_blocks_next_submission_and_quota_refreshes(browser, site):
    context, page = sign_in(browser, site, site.member_code)
    try:
        shot(page, '01-creator')
        expect(page.locator('.side-quota')).to_contain_text(re.compile(r'图片额度\s*10'))
        page.locator('#genCloudBtn').click()
        for _ in range(50):
            if site.started:
                break
            page.wait_for_timeout(100)
        assert len(site.started) == 1
        with site.panel._lock_jobs:
            jobs = [dict(j) for j in site.panel._jobs.values() if j.get('membership_reserved')]
        site.gateway.reconcile(jobs)  # one tick of video_queue_loop
        page.locator('#genCloudBtn').click()
        for _ in range(50):
            if len(site.started) == 2:
                break
            page.wait_for_timeout(100)
        shot(page, '03-second-submit')
        # Before 2026-11-11 the held reservation kept this second submit at "当前套餐并发已满".
        assert len(site.started) == 2
        expect(page.locator('body')).not_to_contain_text('并发已满')
        # The sidebar refetches quota after an accepted submission; no reload needed.
        expect(page.locator('.side-quota')).to_contain_text(re.compile(r'图片额度\s*8'), timeout=5000)

        page.locator('#histOpen').first.click()  # 2026-11-11: the entry is now named 作品库; the id is unchanged
        history = page.locator('#histList')
        expect(history).to_contain_text('失败')
        shot(page, '04-history')
        assert history.get_by_role('button', name='查看图片', exact=True).count() == 0
        page.locator('#favOpen').first.click()
        expect(page.locator('#favList')).to_contain_text('还没有收藏')
        shot(page, '05-favorites')
        assert [p for p in page.problems if 'WebGL' not in p] == []
    finally:
        context.close()


def test_admin_console_lists_held_reservation_in_every_tab_walk(browser, site):
    context, page = sign_in(browser, site, site.member_code)
    page.locator('#genCloudBtn').click()
    for _ in range(50):
        if site.started:
            break
        page.wait_for_timeout(100)
    context.close()
    context, page = sign_in(browser, site, site.admin_code)
    try:
        page.locator('#sideAdminOpen').click()
        for tab in ('plans', 'codes', 'renewals', 'users', 'reservations'):
            page.locator(f'[data-admin-tab="{tab}"]').click()
            page.wait_for_timeout(300)
            shot(page, f'10-admin-{tab}')
        expect(page.locator('#membershipAdminContent')).to_contain_text(site.started[0])
        expect(page.locator('#membershipAdminContent')).to_contain_text('提交或结果未确认')
        assert [p for p in page.problems if 'WebGL' not in p] == []
    finally:
        context.close()


# 2026-11-11: workspace entries always show the workspace; the library entries show that page's records.
@pytest.fixture
def finished_site(site, monkeypatch):
    def finished(job):
        site.started.append(job['id'])
        with site.panel._lock_jobs:
            job.update(status='done', elapsed=1.0, submit_started=time.time(), comfy_prompt_id='fixture-prompt',
                       images=[{'url': '/static/favicon.png', 'file': 'fixture.png'},
                               {'url': '/static/favicon.png', 'file': 'fixture-2.png'}])
            site.panel.save_jobs()

    monkeypatch.setattr(site.panel, 'run_job', finished)
    return site


def submit_one(page, site):
    page.locator('#genCloudBtn').click()
    for _ in range(50):
        if site.started:
            return
        page.wait_for_timeout(100)
    raise AssertionError('submission did not start')


def open_overlays(page):
    return page.evaluate("""() => [...window.jtApp.router.pages].flatMap(([path, item]) =>
        [...item.shadow.querySelectorAll('.library-overlay.open')].map(node => path + '#' + node.id))""")


def test_workspace_entry_always_shows_the_workspace(browser, finished_site):
    site = finished_site
    context, page = sign_in(browser, site, site.member_code)
    try:
        nav = lambda name: page.locator('body > .app-shell > .topbar .topnav-link', has_text=name).click()
        active = re.compile(r'\bactive\b')
        page.locator('#histOpen').first.click()
        assert open_overlays(page) == ['/#histOverlay']
        expect(page.locator('#histOpen').first).to_have_class(active)
        expect(page.locator('body')).to_have_attribute('data-library', 'hist')
        nav('创作台')  # same page: the library closes and the workspace is back
        assert open_overlays(page) == []
        expect(page.locator('#histOpen').first).not_to_have_class(active)
        expect(page.locator('#genCloudBtn')).to_be_visible()

        page.locator('#favOpen').first.click()
        assert open_overlays(page) == ['/#favOverlay']
        page.locator('#histOpen').first.click()  # one library at a time
        assert open_overlays(page) == ['/#histOverlay']
        nav('图片编辑')
        expect(page.locator('body')).to_have_attribute('data-page', '/realism')
        assert open_overlays(page) == []
        page.locator('#favOpen').first.click()
        assert open_overlays(page) == ['/realism#favOverlay']
        expect(page.locator('#favOpen').first).to_have_class(active)
        shot(page, '22-edit-favorites')
        nav('视频')
        expect(page.locator('body')).to_have_attribute('data-page', '/video')
        assert open_overlays(page) == []
        page.locator('#histOpen').first.click()
        assert open_overlays(page) == ['/video#histOverlay']
        shot(page, '23-video-library')
        nav('图片编辑')  # the favourites opened there earlier must not come back
        expect(page.locator('body')).to_have_attribute('data-page', '/realism')
        assert open_overlays(page) == []
        nav('创作台')
        expect(page.locator('body')).to_have_attribute('data-page', '/')
        assert open_overlays(page) == []
        expect(page.locator('body')).to_have_attribute('data-library', '')
        page.locator('#histOpen').first.click()
        page.go_back()  # browser history behaves like the sidebar
        expect(page.locator('body')).to_have_attribute('data-page', '/realism')
        assert open_overlays(page) == []
        assert [p for p in page.problems if 'WebGL' not in p] == []
    finally:
        context.close()


def test_creator_library_shows_picture_cards_pages_and_badges(browser, finished_site):
    site = finished_site
    context, page = sign_in(browser, site, site.member_code)
    try:
        expect(page.locator('#histCount')).to_be_hidden()
        submit_one(page, site)
        expect(page.locator('#histCount')).to_have_text('1', timeout=8000)
        with site.panel._lock_jobs:  # 24 older records of the same owner
            source = dict(site.panel._jobs[site.started[0]])
            for index in range(24):
                copy = dict(source, id='%012x' % (index + 1), created=source['created'] - 100 - index,
                            status='error' if index == 0 else 'done', membership_reserved=False)
                if index == 0:
                    copy['images'] = []
                site.panel._jobs[copy['id']] = copy
        page.locator('#histOpen').first.click()
        cards = page.locator('#histList .history-card')
        expect(cards).to_have_count(20)
        expect(page.locator('#histCount')).to_have_text('25', timeout=8000)
        expect(cards.first.locator('.history-thumbnail img')).to_have_attribute('src', re.compile('favicon'))
        expect(cards.first.locator('.history-count')).to_have_text('2 张')
        failed = page.locator('#histList .history-card[data-status=error]')
        expect(failed.locator('.history-thumbnail')).to_have_text('失败')
        assert failed.get_by_role('button', name='查看图片').count() == 0
        shot(page, '20-library')
        page.locator('#histList .history-more').click()
        expect(cards).to_have_count(25)
        expect(page.locator('#histList .history-more')).to_be_hidden()

        cards.first.get_by_role('button', name='查看图片').click()
        expect(page.locator('#histList .history-view .media-gallery')).to_be_visible()
        expect(cards.first).to_be_hidden()
        shot(page, '21-library-view')
        page.locator('#histList .history-back').click()
        expect(cards.first).to_be_visible()
        assert page.locator('#histList .history-view').count() == 0

        counts = page.evaluate("""async () => { const out = {}; for (const scope of ['creator', 'realism', 'video', 'nope']) {
            const r = await fetch('/api/library-counts?scope=' + scope); out[scope] = r.ok ? await r.json() : r.status; } return out; }""")
        assert counts == {'creator': {'history': 25, 'favorites': 0}, 'realism': {'history': 0, 'favorites': 0},
                          'video': {'history': 0, 'favorites': 0}, 'nope': 400}
        assert [p for p in page.problems if 'WebGL' not in p and '400' not in p] == []
    finally:
        context.close()


def test_video_page_upload_queue_and_cancel_through_real_server(browser, site, monkeypatch):
    """2026-11-11: the video page against the real server. Only the provider transfer is replaced."""
    uploads = []

    def provider_upload(path, filename, ctype='application/octet-stream', timeout=120):
        uploads.append((filename, ctype))
        return 'api/fixture-' + filename

    monkeypatch.setattr(site.panel, 'rh_upload_temp_file', provider_upload)
    context, page = sign_in(browser, site, site.member_code)
    try:
        page.locator('body > .app-shell > .topbar .topnav-link', has_text='视频').click()
        expect(page.locator('body')).to_have_attribute('data-page', '/video')
        panel_box, quota = page.locator('#taskPanel'), page.locator('.side-quota')
        page.locator('#param_prompt').fill('一只猫走过雨后的街道')
        page.locator('#genBtn').click()
        expect(panel_box).to_contain_text('排队 · 第 1 位')
        expect(quota).to_contain_text(re.compile(r'视频额度\s*2'), timeout=5000)
        expect(page.locator('#histCount')).to_have_text('1', timeout=8000)

        with page.expect_response(lambda r: 'upload-finish' in r.url and r.status == 200):
            page.locator('#wfForm input[type=file]').first.set_input_files(str(Path(__file__).parents[1] / 'static' / 'favicon.png'))
        page.wait_for_timeout(2500)  # the form shows the uploaded frame before it can be submitted
        page.locator('#genBtn').click()
        expect(panel_box).to_contain_text('排队 · 第 2 位')
        expect(quota).to_contain_text(re.compile(r'视频额度\s*1'), timeout=5000)
        assert uploads == [('favicon.png', 'image/png')]
        with site.panel._lock_jobs:
            media = [bool(job.get('media')) for job in sorted(site.panel._jobs.values(), key=lambda job: job['created'])]
        assert media == [False, True]
        shot(page, '30-video-queued')

        with page.expect_response(lambda r: r.url.endswith('/api/video-queue') and r.request.method == 'POST' and r.status == 200):
            page.get_by_role('button', name='取消排队').first.click()
        expect(panel_box).to_contain_text('已取消 · 1')
        page.wait_for_timeout(1500)  # the page's own refetch right after the cancel has come and gone
        expect(panel_box).to_contain_text('排队 · 第 1 位')
        with site.panel._lock_jobs:
            jobs = [dict(job) for job in site.panel._jobs.values() if job.get('membership_reserved')]
        site.gateway.reconcile(jobs)  # one tick of video_queue_loop: the cancelled task's unit is refunded
        states = sorted((job['status'], site.store.get_reservation(job['id'])['state']) for job in jobs)
        assert states == [('cancelled', 'refunded'), ('queued', 'reserved')], states
        # Nobody touches the page: the sidebar picks the refund up on its own.
        expect(quota).to_contain_text(re.compile(r'视频额度\s*2'), timeout=8000)
        shot(page, '31-video-cancelled')
        assert [p for p in page.problems if 'WebGL' not in p] == []
    finally:
        context.close()


# 2026-11-12: the owner's second batch after logging in on the live site.
def lightbox_state(page):
    return page.evaluate("""() => { const box = document.getElementById('jtLightbox'); return !box || box.hidden ? null :
        {media: box.querySelector('.lb-stage > *')?.tagName, fav: !box.querySelector('[data-lb=fav]').hidden,
         href: box.querySelector('[data-lb=download]').getAttribute('href')}; }""")


def test_library_plays_results_in_a_lightbox_above_the_library(browser, site):
    """视频「播放结果」和图片编辑「查看结果」在作品库上层弹窗，点空白或 Esc 关闭，不再跳回创作页。"""
    context, page = sign_in(browser, site, site.member_code)
    try:
        nav = lambda name: page.locator('body > .app-shell > .topbar .topnav-link', has_text=name).click()
        nav('视频')
        expect(page.locator('body')).to_have_attribute('data-page', '/video')
        page.locator('#param_prompt').fill('一只猫走过雨后的街道')
        page.locator('#genBtn').click()
        expect(page.locator('#taskPanel')).to_contain_text('排队 · 第 1 位')
        with site.panel._lock_jobs:
            job = next(iter(site.panel._jobs.values()))
            job.update(status='done', elapsed=1.0, video_queued=False,
                       images=[{'url': '/static/favicon.png', 'file': 'result.mp4', 'file_type': 'mp4'}])
            site.panel._jobs['e' * 12] = dict(job, id='e' * 12, style_id='realism', workflow='member-workflow', wf_name='换装',
                                              membership_reserved=False, created=job['created'] - 5,
                                              images=[{'url': '/static/favicon.png', 'file': 'result.png', 'file_type': 'png'}])
        page.locator('#histOpen').first.click()
        play = page.locator('#histList').get_by_role('button', name='播放结果')
        expect(play).to_be_enabled()
        play.click()
        box = page.locator('#jtLightbox')
        expect(box).to_be_visible()
        assert lightbox_state(page) == {'media': 'VIDEO', 'fav': True, 'href': site.gateway.origin + '/static/favicon.png'}
        assert open_overlays(page) == ['/video#histOverlay'], 'the library stays open underneath'
        expect(page.locator('#mediaGallery')).to_be_hidden()
        shot(page, '40-video-lightbox')
        page.mouse.click(20, 450)  # the backdrop
        expect(box).to_be_hidden()
        assert open_overlays(page) == ['/video#histOverlay']
        play.click()
        expect(box).to_be_visible()
        page.keyboard.press('Escape')
        expect(box).to_be_hidden()
        assert open_overlays(page) == ['/video#histOverlay'], 'Escape closes the player, not the library'

        nav('图片编辑')
        expect(page.locator('body')).to_have_attribute('data-page', '/realism')
        page.locator('#histOpen').first.click()
        page.locator('#histList').get_by_role('button', name='查看结果').click()
        expect(box).to_be_visible()
        assert lightbox_state(page)['media'] == 'IMG'
        assert open_overlays(page) == ['/realism#histOverlay']
        shot(page, '41-edit-lightbox')
        box.get_by_role('button', name='关闭').click()
        expect(box).to_be_hidden()

        # The page's own result area: the save / download pair shares one height and one top edge
        # (owner's screenshot 7), and the task rail is a rounded card (screenshot 8).
        page.locator('body > .app-shell > .topbar .topnav-link', has_text='图片编辑').click()
        assert open_overlays(page) == []
        expect(page.locator('#galleryMain .gallery-actions').last).to_be_visible(timeout=8000)
        buttons = page.evaluate("""() => [...window.jtApp.router.pages.get('/realism').shadow.querySelectorAll('#galleryMain .gallery-actions > *')]
            .map(node => { const r = node.getBoundingClientRect(); return [node.textContent.trim(), Math.round(r.top), Math.round(r.height)]; })""")
        assert [b[0] for b in buttons] == ['♥ 收藏', '⬇ 下载原文件'] and buttons[0][1:] == buttons[1][1:] and buttons[0][2] == 36, buttons
        assert page.locator('#taskPanel').last.evaluate('node => getComputedStyle(node).borderTopLeftRadius') == '24px'
        shot(page, '42-edit-result')
        assert [p for p in page.problems if 'WebGL' not in p] == []
    finally:
        context.close()


def test_creator_banner_sticks_pictures_zoom_and_broken_records_clear(browser, finished_site, tmp_path, monkeypatch):
    site = finished_site
    context, page = sign_in(browser, site, site.member_code)
    try:
        submit_one(page, site)
        expect(page.locator('.acc-shot img').first).to_be_visible(timeout=8000)
        from io import BytesIO
        from PIL import Image
        import base64
        raw = BytesIO(); Image.new('RGB', (1600, 4000), (200, 120, 60)).save(raw, 'PNG')
        monkeypatch.setattr(site.panel, 'SHOWCASE_DIR', tmp_path / 'showcase')
        workflow = next(iter(site.panel.WORKFLOWS))
        tall_url = site.panel.showcase_admin(None, {'workflow_id': workflow, 'image': 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()})['items'][workflow]['image']
        with site.panel._lock_jobs:
            source = dict(site.panel._jobs[site.started[0]])
            for index in range(6):  # enough rows to scroll; two records whose files are gone, one failed
                copy = dict(source, id='%012x' % (index + 1), created=source['created'] - 100 - index, membership_reserved=False)
                if index < 2:
                    copy['images'] = [{'url': '/static/assets/gone-%d.png' % index, 'file': 'gone.png'}]
                if index == 2:  # a failure whose provider outcome was never confirmed is clearable too
                    copy.update(status='error', error='comfyui timeout after 1800s', provider_status='RUNNING', images=[])
                if index == 3:  # a tall original, far larger than the window
                    copy['images'] = [{'url': tall_url, 'file': 'tall.png'}]
                site.panel._jobs[copy['id']] = copy
        page.reload()
        expect(page.locator('#accountGate')).to_be_hidden(timeout=15000)

        # Banner: whole hole inside it; it shrinks and stays on top when the stream scrolls.
        hero, hole, feed = page.locator('.acc-feed-hero'), page.locator('.acc-hole'), page.locator('.acc-feed')
        expect(page.locator('.acc-shot.expired')).to_have_count(2, timeout=8000)
        inside = lambda: page.evaluate("""() => { const root = window.jtApp.router.pages.get('/').shadow,
            a = root.querySelector('.acc-feed-hero').getBoundingClientRect(), b = root.querySelector('.acc-hole').getBoundingClientRect();
            return b.left >= a.left && b.right <= a.right && b.top >= a.top && b.bottom <= a.bottom; }""")
        assert inside(), 'the black hole is not cut by the banner edge'
        tall, top = hero.bounding_box()['height'], hero.bounding_box()['y']
        shot(page, '50-creator-banner')
        feed.evaluate('node => node.scrollTo(0, 600)')
        expect(hero).to_have_class(re.compile(r'\bcompact\b'))
        page.wait_for_timeout(400)
        slim = hero.bounding_box()
        assert slim['height'] < tall / 2 and abs(slim['y'] - top) <= 6, (slim, tall, top)
        assert inside()
        assert feed.evaluate('node => node.scrollTop') == 600, 'shrinking the banner does not move the stream'
        shot(page, '51-creator-banner-compact')
        feed.evaluate('node => node.scrollTo(0, 0)')
        expect(hero).not_to_have_class(re.compile(r'\bcompact\b'))

        # Failed and expired records: placeholders, one clear per record, one for all of them.
        tools = page.locator('.acc-feed-tools')
        expect(tools).to_contain_text('有 3 条出错或图片已失效的记录')
        failed = page.locator('.acc-group', has=page.locator('.acc-shot.failed'))
        failed.get_by_role('button', name='清除').click()
        expect(tools).to_contain_text('有 2 条')
        shot(page, '52-creator-expired')
        tools.get_by_role('button', name='全部清除').click()
        expect(tools).to_have_count(0)
        expect(page.locator('.acc-shot.expired')).to_have_count(0)
        left = page.evaluate("async () => (await (await fetch('/api/jobs?scope=creator&limit=30')).json()).map(job => job.id)")
        assert sorted(left) == sorted([site.started[0], '%012x' % 4, '%012x' % 5, '%012x' % 6])
        expect(page.locator('#histCount')).to_have_text('4', timeout=8000)

        # Library: the image view is large, a click opens the lightbox, which can go full screen.
        page.locator('#histOpen').first.click()
        page.locator('#histList .history-card').first.get_by_role('button', name='查看图片').click()
        picture = page.locator('#histList .history-view .gallery-main img')
        expect(picture).to_be_visible()
        shot(page, '53-library-view')
        picture.click()
        box = page.locator('#jtLightbox')
        expect(box).to_be_visible()
        assert lightbox_state(page)['media'] == 'IMG'
        shot(page, '54-library-lightbox')
        box.get_by_role('button', name='全屏').click()
        for _ in range(30):  # the page's CSP rules out wait_for_function
            if page.evaluate('document.fullscreenElement && document.fullscreenElement.id') == 'jtLightbox':
                break
            page.wait_for_timeout(100)
        assert page.evaluate('document.fullscreenElement && document.fullscreenElement.id') == 'jtLightbox'
        shot(page, '55-lightbox-fullscreen')
        box.get_by_role('button', name='关闭').click()
        expect(box).to_be_hidden()
        for _ in range(30):
            if page.evaluate('!document.fullscreenElement'):
                break
            page.wait_for_timeout(100)
        assert page.evaluate('!document.fullscreenElement')
        expect(picture).to_be_visible()
        # 2026-11-12 (owner's screenshot): a picture larger than the window shows whole, not half of it.
        page.locator('#histList .history-back').click()
        page.locator('#histList .history-card', has=page.locator('img[src="%s"]' % tall_url)).get_by_role('button', name='查看图片').click()
        page.locator('#histList .history-view .gallery-main img').click()
        expect(box).to_be_visible()
        fits = lambda: page.evaluate("""() => { const img = document.querySelector('#jtLightbox .lb-stage img'), r = img.getBoundingClientRect(),
            bar = document.querySelector('#jtLightbox .lb-bar').getBoundingClientRect();
            return img.naturalHeight === 4000 && r.top >= 0 && r.left >= 0 && r.right <= innerWidth && r.bottom <= bar.top
                && Math.abs(r.width / r.height - 0.4) < 0.01; }""")
        for _ in range(50):  # the original replaces the preview once it has loaded
            if fits():
                break
            page.wait_for_timeout(100)
        assert fits(), 'the whole picture is inside the window, above the buttons'
        shot(page, '56-lightbox-tall')
        page.keyboard.press('Escape')
        expect(box).to_be_hidden()
        # The library's own clear button removes failed records from the list.
        with site.panel._lock_jobs:
            site.panel._jobs['f' * 12] = dict(source, id='f' * 12, status='error', error='x', images=[], membership_reserved=False)
        page.locator('#histList .history-back').click()
        page.locator('#histOpen').first.click()
        page.locator('#histOpen').first.click()
        expect(page.locator('#histList .history-card[data-status=error]')).to_have_count(1)
        page.locator('#histOverlay .acc-lib-clear').click()
        expect(page.locator('#histList .history-card[data-status=error]')).to_have_count(0)
        assert site.panel._jobs['f' * 12].get('history_cleared') is True
        assert [p for p in page.problems if 'WebGL' not in p and '404' not in p] == []
    finally:
        context.close()


def test_admin_showcase_picture_and_name_reach_the_scheme_cards(browser, site, tmp_path, monkeypatch):
    monkeypatch.setattr(site.panel, 'SHOWCASE_DIR', tmp_path / 'showcase')
    site.gateway.showcase_callback = site.panel.showcase_admin
    context, page = sign_in(browser, site, site.admin_code)
    try:
        page.locator('#sideAdminOpen').click()
        page.locator('[data-admin-tab="showcase"]').click()
        card = page.locator('[data-showcase="member-video"]')
        expect(card).to_contain_text('原名：member-video', timeout=15000)  # the tab loads three lists first
        expect(card).to_contain_text('未上传展示图')
        card.locator('input[type=text]').fill('让照片动起来')
        card.get_by_role('button', name='保存名字').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('名字已保存。')
        card.locator('input[type=file]').set_input_files(str(Path(__file__).parents[1] / 'static' / 'favicon.png'))
        expect(card.locator('.admin-showcase-art img')).to_have_attribute('src', re.compile(r'^/api/showcase-image/[0-9a-f]{32}\.(webp|jpg)$'))
        expect(card.get_by_role('button', name='移除图片')).to_be_visible()
        assert page.locator('[data-showcase]').count() >= 4
        shot(page, '60-admin-showcase')
        # Creator style cards are managed in the same tab (owner, 2026-11-12).
        style = page.locator('[data-showcase="style.sketch"]')
        expect(style).to_contain_text('原名：铅绘')
        assert page.locator('[data-showcase^="style."]').count() == 10
        style.locator('input[type=text]').fill('手绘铅笔')
        style.get_by_role('button', name='保存名字').click()
        expect(page.locator('#membershipAdminStatus')).to_have_text('名字已保存。')
        style = page.locator('[data-showcase="style.sketch"]')
        style.locator('input[type=file]').set_input_files(str(Path(__file__).parents[1] / 'static' / 'favicon.png'))
        expect(style.locator('.admin-showcase-art img')).to_have_attribute('src', re.compile(r'^/api/showcase-image/'))
        page.locator('#membershipAdminClose').click()
        # The creator's style sheet and style chip follow without a reload.
        page.locator('.acc-chip[data-group="style"]').click()
        tile = page.locator('#styleSwitch button[data-style="sketch"]')
        expect(tile.locator('.acc-style-name')).to_have_text('手绘铅笔')
        expect(tile.locator('.acc-style-art')).to_have_attribute('src', re.compile(r'^/api/showcase-image/'))
        assert tile.locator('.acc-style-art').evaluate('img => img.complete && img.naturalWidth > 0')
        expect(page.locator('#styleSwitch button[data-style="cold"] .acc-style-name')).to_have_text('冷脸萌')
        shot(page, '63-creator-styles')
        tile.click()
        expect(page.locator('.acc-chip[data-group="style"] .acc-style-label')).to_have_text('手绘铅笔')
        page.keyboard.press('Escape')

        page.locator('body > .app-shell > .topbar .topnav-link', has_text='视频').click()
        expect(page.locator('body')).to_have_attribute('data-page', '/video')
        page.locator('.wb-scheme').click()
        scheme = page.locator('.wb-card[data-pick="member-video"]')
        expect(scheme.locator('b')).to_have_text('让照片动起来')
        expect(scheme.locator('.wb-art img')).to_have_attribute('src', re.compile(r'^/api/showcase-image/'))
        assert scheme.locator('.wb-art img').evaluate('img => img.complete && img.naturalWidth > 0')
        shot(page, '61-video-schemes')
        scheme.click()
        expect(page.locator('.wb-scheme b')).to_have_text('让照片动起来')
        # Rounded task rail (owner's screenshot 8) and one height for the result buttons.
        assert page.locator('#taskPanel').evaluate('node => getComputedStyle(node).borderTopLeftRadius') == '24px'
        shot(page, '62-video-page')
        # The fixture server does not ship the stock style thumbnails; opening the style sheet logs their 404s.
        assert [p for p in page.problems if 'WebGL' not in p and '404' not in p] == []
    finally:
        context.close()
