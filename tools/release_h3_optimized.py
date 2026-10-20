"""Add one optimized workflow via the existing data-preserving release transaction."""
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
    for route in ('/','/realism'):assert manifest['pages'][route]==old['pages'][route]
    assert all(re.fullmatch(r'/static/assets/video\.[0-9a-f]{12}\.js',p)
               for p in set(old['assets']) ^ set(manifest['assets']))
    for path in manifest['assets']:
        assert hashlib.sha256(data[path.lstrip('/')]).hexdigest()[:12]==path.split('.')[-2]
    previous=json.loads(subprocess.check_output(['git','show',baseline+':config.json'],cwd=BASE))
    candidate=json.loads(data['config.json'])
    added=[w for w in candidate['workflows'] if w['id']=='h3_reference_optimized']
    assert len(added)==1 and added[0]['rh_workflow_id']=='2111727257252290561'
    assert added[0]['source_api_json_sha256']=='5182d336c7bb2d12fe259400f01f43de617d5a2303625149d3ea514716546e83'
    candidate['workflows']=[w for w in candidate['workflows'] if w['id']!='h3_reference_optimized']
    assert candidate==previous, 'Existing workflow configuration must remain intact'


def checks():
    with tempfile.TemporaryDirectory(prefix='jt-h3-optimized-') as directory:
        subprocess.run([sys.executable,'-m','pytest','-q',
            'tests/test_h3_optimized.py','tests/test_h3_optimized_browser.py','tests/test_compact_workflow_forms.py',
            'tests/test_h3_remix.py','tests/test_h3_remix_browser.py','tests/test_h3_lora_slots.py',
            'tests/test_video_resumable_multi.py','tests/test_video_queue.py','tests/test_video_redo.py',
            'tests/test_video_cancel.py','tests/test_video_queue_layout.py','tests/test_video_queue_browser.py',
            'tests/test_image_edit_browser.py','tests/test_image_edit_upload_http.py',
            'tests/test_membership_video_queue.py','tests/test_membership_http.py','tests/test_rh_upload_capabilities_http.py',
            'tests/test_app_shell.py','--basetemp',str(pathlib.Path(directory)/'pytest')],cwd=BASE,check=True)
    subprocess.run(['node','frontend/verify-contracts.mjs'],cwd=BASE,check=True)


if __name__=='__main__':
    transaction.MODULES=('server.py','config.json')
    transaction.DEFAULT_STATE=BASE/'audit/h3-optimized-20261020/release.json'
    transaction.verify_frontend_scope=scope
    transaction.run_checks=checks
    transaction.main()
