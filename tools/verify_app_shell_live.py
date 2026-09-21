"""Public App Shell smoke; a paid video requires an explicit CLI flag.

The state file is created before clicking Generate. Never rerun paid submission
with an existing state file; collect the recorded job instead.
"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://8.210.125.65:8189')
    parser.add_argument('--paid-video', action='store_true')
    parser.add_argument('--state', default=str(ROOT / 'panel_data/app-shell-video-canary.json'))
    args = parser.parse_args()
    state = Path(args.state)
    if args.paid_video and state.exists():
        raise RuntimeError('Paid submission already attempted; query recorded job, never resubmit')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors, documents, posts = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('requestfailed', lambda req: print('REQUEST_FAILED', req.url, req.failure, flush=True))
        page.on('response', lambda response: print('HTTP_ERROR', response.status, response.url, flush=True)
                if response.status >= 400 else None)
        page.on('request', lambda req: documents.append(req.url) if req.resource_type == 'document' else None)
        page.on('request', lambda req: posts.append(req.url) if req.method == 'POST' else None)
        page.goto(args.base + '/', wait_until='domcontentloaded', timeout=90000)
        expect(page.locator('#genApiBtn')).to_be_enabled(timeout=60000)
        page.wait_for_function("['ready','fallback'].includes(document.body.dataset.singularity)", timeout=90000)
        initial = page.evaluate('({renderers:jtApp.metrics.renderers,scene:document.body.dataset.singularity})')
        for route in ('/realism', '/video', '/'):
            page.locator(f'body > .app-shell > .topbar a[href="{route}"]').click()
            page.wait_for_function('document.body.dataset.page === ' + json.dumps(route), timeout=60000)
        page.go_back()
        page.wait_for_function("document.body.dataset.page === '/video'")
        page.go_forward()
        page.wait_for_function("document.body.dataset.page === '/'")
        assert len(documents) == 1, documents
        assert page.evaluate('jtApp.metrics.renderers') == initial['renderers'] == 1, initial
        assert not posts, posts
        assert not errors, errors
        print(json.dumps({'smoke': 'PASS', 'documents': len(documents), **initial}), flush=True)
        if args.paid_video:
            page.locator('body > .app-shell > .topbar a[href="/video"]').click()
            page.wait_for_function("document.body.dataset.page === '/video'")
            page.locator('[data-wf="h3_t2v_i2v"]').click()
            page.locator('#param_prompt').fill('A calm ocean at sunrise, gentle waves, static camera, natural light.')
            for key, value in {'width': '512', 'height': '512', 'duration': '4'}.items():
                page.locator('#param_' + key).fill(value)
            state.parent.mkdir(parents=True, exist_ok=True)
            record = {'phase': 'submission_uncertain', 'submit_attempts': 1, 'started_at': time.time()}
            state.write_text(json.dumps(record, indent=2), encoding='utf8')
            with page.expect_response(lambda r: r.url.endswith('/api/video-generate'), timeout=120000) as response:
                page.locator('#genBtn').click()
            reply = response.value.json()
            if not reply.get('job_id'):
                record.update(phase='rejected', status=response.value.status, error=reply.get('error'))
                state.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
                raise RuntimeError('Video submission rejected: ' + str(reply.get('error')))
            record.update(phase='accepted', job_id=reply['job_id'])
            state.write_text(json.dumps(record, indent=2), encoding='utf8')
            page.context.storage_state(path=str(state.with_suffix('.session.json')))
            print(json.dumps(record), flush=True)
            page.locator('body > .app-shell > .topbar a[href="/"]').click()
            deadline = time.monotonic() + 1200
            last_status = None
            while time.monotonic() < deadline:
                response = page.request.get(args.base + '/api/job/' + record['job_id'], timeout=60000)
                if not response.ok:
                    print('POLL_HTTP', response.status, flush=True)
                    page.wait_for_timeout(5000)
                    continue
                result = response.json()
                status = result.get('status')
                if status != last_status:
                    print(json.dumps({k: result.get(k) for k in ('id', 'status', 'provider_status', 'elapsed')}), flush=True)
                    last_status = status
                if status in ('done', 'error', 'cancelled', 'canceled'):
                    record.update(phase=status, result={k: result.get(k) for k in
                        ('id', 'status', 'provider_status', 'elapsed', 'error', 'width', 'height')})
                    state.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
                    assert status == 'done', record
                    page.locator('body > .app-shell > .topbar a[href="/video"]').click()
                    expect(page.locator('video').first).to_be_visible(timeout=30000)
                    page.wait_for_function("jtApp.router.pages.get('/video').shadow.querySelector('video')?.readyState >= 2", timeout=90000)
                    record['media'] = page.locator('video').first.evaluate('(v)=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration})')
                    state.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
                    assert len(documents) == 1
                    print('VIDEO_DONE_AND_KEEP_ALIVE_PASS', flush=True)
                    break
                page.wait_for_timeout(5000)
            else:
                raise RuntimeError('Video still pending; collect original job only')
        browser.close()


if __name__ == '__main__':
    main()
