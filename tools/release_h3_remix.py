"""Release one additive video workflow through the existing preservation transaction."""
import hashlib
import json
import re
import subprocess
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


def main():
    import retired_release
    retired_release.refuse_main(__file__)
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/h3-remix-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
