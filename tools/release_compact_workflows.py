"""Publish compact workflow controls while preserving production accounts and jobs."""
import hashlib
import json
import re
import subprocess
import release_video_queue_plan as transaction

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
    old_workflow['rh_params'].pop('prompt_optimizer_enabled',None)
    old_workflow['desc']=new_workflow['desc']
    old_workflow['rh_graph']['295']['inputs']['prompt_optimizer_enabled']=False
    assert previous==candidate, 'Unexpected workflow configuration change'


def main():
    import retired_release
    retired_release.refuse_main(__file__)
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/compact-workflow-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
