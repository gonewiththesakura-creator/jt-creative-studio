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
