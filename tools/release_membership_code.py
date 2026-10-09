"""Publish reviewed account code with membership disabled; retain live ledgers."""
import json
import release_video_queue_presets as release


def main():
    root = release.t.BASE
    manifest = json.loads((root / 'static/app-manifest.json').read_text(encoding='utf-8'))
    base = {'server.py', 'static/video.html', 'static/app-manifest.json', 'static/app.html'}
    base.update(p.lstrip('/') for p in manifest['pages']['/video'].values() if p.startswith('/static/'))
    extra = {p.lstrip('/') for p in manifest['assets']}
    extra.update(('membership_store.py', 'membership_auth.py', 'membership_http.py', 'membership_media.py',
                  'requirements-membership.txt', 'tools/migrate_membership_owner.py'))
    release.STATE = root / 'audit/membership-code-release-20261009/release.json'
    if release.STATE.exists():
        raise RuntimeError('Inspect existing release state before another publish')
    release.main(extra_paths=sorted(extra - base))


if __name__ == '__main__':
    main()
