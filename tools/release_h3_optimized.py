"""Add one optimized workflow via the existing data-preserving release transaction."""
import hashlib
import json
import re
import subprocess
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


def main():
    import retired_release
    retired_release.refuse_main(__file__)
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/h3-optimized-20261020/release.json'
    transaction.verify_frontend_scope=scope
    transaction.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
