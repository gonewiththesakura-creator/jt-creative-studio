"""Publish reviewed account code with membership disabled; retain live ledgers."""
import argparse
import json
import release_video_queue_presets as release

STATE = release.t.BASE / 'audit/membership-code-release-20261009/release.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true',
                        help='run the full release gate and publish; without it only read-only production checks run')
    args = parser.parse_args(argv)
    root = release.t.BASE
    manifest = json.loads((root / 'static/app-manifest.json').read_text(encoding='utf-8'))
    # The presets release already ships server.py's module closure and the video page,
    # and skips extra paths it carries itself.
    extra = {p.lstrip('/') for p in manifest['assets']}
    extra.update(('requirements-membership.txt', 'tools/migrate_membership_owner.py'))
    release.STATE = STATE
    if release.STATE.exists():
        raise RuntimeError('Inspect existing release state before another publish')
    release.main(extra_paths=sorted(extra), execute=args.execute)


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
