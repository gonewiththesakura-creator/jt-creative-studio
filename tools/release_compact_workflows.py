"""Publish compact workflow controls while preserving production accounts and jobs."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
import release_video_queue_plan as transaction
import release_h3_remix as previous_release

BASE=transaction.t.BASE


def scope(baseline,manifest,data):
    old=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest['main']==old['main'] and manifest['pages']['/']==old['pages']['/']
    assert all(re.fullmatch(r'/static/assets/(video|realism)\.[0-9a-f]{12}\.(js|css)',path)
               for path in set(old['assets']) ^ set(manifest['assets']))
    for path in manifest['assets']:
        assert hashlib.sha256(data[path.lstrip('/')]).hexdigest()[:12]==path.split('.')[-2]
    previous=json.loads(subprocess.check_output(['git','show',baseline+':config.json'],cwd=BASE))
    candidate=json.loads(data['config.json'])
    old_workflow=next(w for w in previous['workflows'] if w['id']=='h3_remix_full')
    new_workflow=next(w for w in candidate['workflows'] if w['id']=='h3_remix_full')
    assert 'prompt_optimizer_enabled' not in new_workflow['rh_params']
    old_workflow['rh_params'].pop('prompt_optimizer_enabled')
    old_workflow['desc']=new_workflow['desc']
    old_workflow['rh_graph']['295']['inputs']['prompt_optimizer_enabled']=False
    assert previous==candidate, 'Unexpected workflow configuration change'


def checks():
    previous_release.checks()
    with tempfile.TemporaryDirectory(prefix='jt-compact-release-') as directory:
        subprocess.run([previous_release.sys.executable,'-m','pytest','-q',
                        'tests/test_compact_workflow_forms.py','--basetemp',str(Path(directory)/'pytest')],cwd=BASE,check=True)


if __name__=='__main__':
    transaction.MODULES=('server.py','config.json')
    transaction.DEFAULT_STATE=BASE/'audit/compact-workflow-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.run_checks=checks
    transaction.main()
