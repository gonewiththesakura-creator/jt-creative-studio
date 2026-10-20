"""Release one additive video workflow through the existing preservation transaction."""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import release_video_queue_plan as transaction

BASE=transaction.t.BASE


def scope(baseline,manifest,data):
    old=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest['main']==old['main']
    for route in ('/','/realism'):
        assert manifest['pages'][route]==old['pages'][route]
    assert all(re.fullmatch(r'/static/assets/video\.[0-9a-f]{12}\.(js|css|html)',p)
               for p in set(old['assets']) ^ set(manifest['assets']))
    for path in manifest['assets']:
        assert hashlib.sha256(data[path.lstrip('/')]).hexdigest()[:12]==path.split('.')[-2]
    previous=json.loads(subprocess.check_output(['git','show',baseline+':config.json'],cwd=BASE))
    candidate=json.loads(data['config.json'])
    added=[w for w in candidate['workflows'] if w['id']=='h3_remix_full']
    assert len(added)==1 and added[0]['rh_workflow_id']=='2111635037301452801'
    assert added[0]['source_api_json_sha256']=='3a8e4b89bd61da3d0ffe4ce5c54574b4c6849b7957a517eb09f243dee68b7680'
    candidate['workflows']=[w for w in candidate['workflows'] if w['id']!='h3_remix_full']
    assert candidate==previous, 'Existing workflows and configuration must remain intact'


def checks():
    with tempfile.TemporaryDirectory(prefix='jt-remix-release-') as directory:
        subprocess.run([sys.executable,'-m','pytest','-q',
            'tests/test_h3_remix.py','tests/test_h3_remix_browser.py','tests/test_h3_lora_slots.py',
            'tests/test_video_resumable_multi.py','tests/test_video_queue.py','tests/test_video_redo.py',
            'tests/test_video_cancel.py','tests/test_video_queue_layout.py','tests/test_video_queue_browser.py',
            'tests/test_image_edit_browser.py','tests/test_image_edit_upload_http.py',
            'tests/test_membership_video_queue.py','tests/test_membership_http.py','tests/test_rh_upload_capabilities_http.py',
            'tests/test_app_shell.py','--basetemp',str(pathlib.Path(directory)/'pytest')],cwd=BASE,check=True)
    subprocess.run(['node','frontend/verify-contracts.mjs'],cwd=BASE,check=True)


def main():
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/h3-remix-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.run_checks=checks
    transaction.main()


if __name__=='__main__':main()
