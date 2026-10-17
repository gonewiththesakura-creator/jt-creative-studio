"""Publish image editing and replay caching using the verified preservation transaction.

All existing membership data and queued jobs are preserved. This invokes the
same lock, admission fence, natural drain, backup, swap, rollback and cleanup
as release_video_queue_plan; only the explicitly listed candidate files differ.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

import release_video_queue_plan as transaction

BASE=transaction.t.BASE


def verify_scope(baseline, manifest, data):
    old=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest['main']==old['main']
    assert manifest['pages']['/']==old['pages']['/'], 'Creator code must remain unchanged'
    changed=set(old['assets']) ^ set(manifest['assets'])
    assert all(re.fullmatch(r'/static/assets/(realism|video)\.[0-9a-f]{12}\.(js|html|css)',p) for p in changed)
    for path in manifest['assets']:
        relative=path.lstrip('/')
        assert hashlib.sha256(data[relative]).hexdigest()[:12]==relative.split('.')[-2]
    previous=json.loads(subprocess.check_output(['git','show',baseline+':config.json'],cwd=BASE))
    config=json.loads(data['config.json'])
    workflows=config.pop('workflows'); old_workflows=previous.pop('workflows')
    assert config==previous
    assert [w for w in workflows if w['id']!='qwen21_wardrobe']==old_workflows
    new=next(w for w in workflows if w['id']=='qwen21_wardrobe')
    assert new['rh_workflow_id']=='2111378115142823938'
    assert {k:m['node'] for k,m in new['rh_media'].items()}=={'person':'470','clothing':'475'}
    assert new['source_api_json_sha256']=='9603bf4b7ac5480f977d68bec3e939f16541e7258a6987e893ef5e7a0ae4455d'


def checks():
    with tempfile.TemporaryDirectory(prefix='jt-image-edit-release-') as directory:
        subprocess.run([sys.executable,'-m','pytest','-q',
            'tests/test_image_edit_queue.py','tests/test_image_edit_browser.py','tests/test_video_replay_cache.py','tests/test_membership_image_edit.py',
            'tests/test_video_queue.py','tests/test_video_redo.py','tests/test_video_cancel.py',
            'tests/test_video_clear.py','tests/test_video_thumbnails.py','tests/test_favorite_streaming.py',
            'tests/test_membership_media.py','tests/test_membership_http.py','tests/test_membership_store.py',
            'tests/test_membership_video_queue.py','tests/test_access_code_http.py',
            'tests/test_app_shell.py','tests/test_video_queue_layout.py',
            '--basetemp',str(pathlib.Path(directory)/'pytest')],cwd=BASE,check=True)
    subprocess.run([sys.executable,'tests/test_realism_workbench_contract.py'],cwd=BASE,check=True)
    subprocess.run(['node','frontend/verify-contracts.mjs'],cwd=BASE,check=True)


def main():
    transaction.MODULES=('server.py','membership_media.py','config.json')
    transaction.DEFAULT_STATE=BASE/'audit/image-edit-release-20261018/release.json'
    transaction.verify_frontend_scope=verify_scope
    transaction.run_checks=checks
    transaction.main()


if __name__=='__main__':main()
