"""Publish the upload admission fix through the production preservation transaction."""
import json
import pathlib
import subprocess
import sys
import tempfile
import release_video_queue_plan as transaction

BASE=transaction.t.BASE


def scope(baseline,manifest,data):
    previous=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest==previous, 'No frontend changes in this fix'
    for path,raw in data.items():
        if path=='server.py':continue
        old=subprocess.check_output(['git','show',baseline+':'+path],cwd=BASE)
        assert old.replace(b'\r\n',b'\n')==raw.replace(b'\r\n',b'\n'),path


def checks():
    with tempfile.TemporaryDirectory(prefix='jt-image-upload-') as directory:
        subprocess.run([sys.executable,'-m','pytest','-q',
            'tests/test_image_edit_upload_http.py','tests/test_video_resumable_multi.py',
            'tests/test_large_upload_resilience.py','tests/test_rh_upload_capabilities_http.py',
            'tests/test_membership_http.py','tests/test_membership_image_edit.py',
            'tests/test_image_edit_queue.py','tests/test_wardrobe_reference_toggle.py',
            '--basetemp',str(pathlib.Path(directory)/'pytest')],cwd=BASE,check=True)


if __name__=='__main__':
    transaction.MODULES=('server.py',)
    transaction.DEFAULT_STATE=BASE/'audit/image-upload-fix-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.run_checks=checks
    transaction.main()
