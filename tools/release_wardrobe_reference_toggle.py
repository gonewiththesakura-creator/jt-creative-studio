"""Publish only the wardrobe reference switch, preserving production data."""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import import_qwen21_image_edit as importer
import release_video_queue_plan as transaction

BASE=transaction.t.BASE


def verify_scope(baseline,manifest,data):
    old=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest['main']==old['main']
    assert manifest['pages']['/']==old['pages']['/']
    assert manifest['pages']['/video']==old['pages']['/video']
    changed=set(old['assets'])^set(manifest['assets'])
    assert all(re.fullmatch(r'/static/assets/realism\.[0-9a-f]{12}\.(js|html|css)',path) for path in changed)
    for path in manifest['assets']:
        assert hashlib.sha256(data[path.lstrip('/')]).hexdigest()[:12]==path.split('.')[-2]
    previous=json.loads(subprocess.check_output(['git','show',baseline+':config.json'],cwd=BASE))
    config=json.loads(data['config.json'])
    graph=json.loads((BASE/'audit/image-edit-workflows-20261017'/ (importer.RUN_ID+'-api.json')).read_text(encoding='utf-8'))
    original=next(w for w in previous['workflows'] if w['id']=='qwen21_wardrobe')
    digest=hashlib.sha256(json.dumps(graph,ensure_ascii=False,indent=2).encode()).hexdigest()
    assert digest==original['source_api_json_sha256']
    importer.install(previous,graph,original['source_editor_json_sha256'])
    assert config==previous, 'Only the verified wardrobe schema may change'


def checks():
    with tempfile.TemporaryDirectory(prefix='jt-reference-toggle-') as directory:
        subprocess.run([sys.executable,'-m','pytest','-q',
            'tests/test_wardrobe_reference_toggle.py','tests/test_image_edit_queue.py',
            'tests/test_image_edit_browser.py','tests/test_generic_rh_workflow_runtime.py',
            'tests/test_membership_image_edit.py','tests/test_video_queue.py',
            'tests/test_video_redo.py','tests/test_video_cancel.py','tests/test_video_clear.py',
            'tests/test_video_thumbnails.py','tests/test_membership_media.py',
            'tests/test_membership_http.py','tests/test_membership_store.py',
            'tests/test_membership_video_queue.py','tests/test_access_code_http.py',
            'tests/test_app_shell.py','tests/test_video_queue_layout.py',
            '--basetemp',str(pathlib.Path(directory)/'pytest')],cwd=BASE,check=True)
    subprocess.run([sys.executable,'tests/test_realism_workbench_contract.py'],cwd=BASE,check=True)
    subprocess.run(['node','frontend/verify-contracts.mjs'],cwd=BASE,check=True)


def main():
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/wardrobe-reference-toggle-20261018/release.json'
    transaction.verify_frontend_scope=verify_scope
    transaction.run_checks=checks
    transaction.main()


if __name__=='__main__':main()
