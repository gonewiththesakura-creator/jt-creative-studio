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

        page.locator('text="历史" >> visible=true').first.click()
        history = page.locator('#histList')
        expect(history).to_contain_text('失败')
        shot(page, '04-history')
        assert history.get_by_role('button', name='查看图片', exact=True).count() == 0
        page.locator('text="收藏" >> visible=true').first.click()
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
