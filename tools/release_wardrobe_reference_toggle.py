"""Publish only the wardrobe reference switch, preserving production data."""
import hashlib
import json
import re
import subprocess
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


def main():
    transaction.MODULES=(*transaction.RUNTIME_MODULES,'config.json')
    transaction.DEFAULT_STATE=BASE/'audit/wardrobe-reference-toggle-20261018/release.json'
    transaction.verify_frontend_scope=verify_scope
    transaction.main()


if __name__=='__main__':main()
