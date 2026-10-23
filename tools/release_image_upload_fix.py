"""Publish the upload admission fix through the production preservation transaction."""
import json
import subprocess
import release_video_queue_plan as transaction

BASE=transaction.t.BASE


def scope(baseline,manifest,data):
    previous=json.loads(subprocess.check_output(['git','show',baseline+':static/app-manifest.json'],cwd=BASE))
    assert manifest==previous, 'No frontend changes in this fix'
    # The other runtime modules ship only to keep server.py's closure whole; they
    # must equal the baseline, so their presence is never part of this fix.
    for path,raw in data.items():
        if path=='server.py':continue
        old=subprocess.check_output(['git','show',baseline+':'+path],cwd=BASE)
        assert old.replace(b'\r\n',b'\n')==raw.replace(b'\r\n',b'\n'),path


def main():
    transaction.MODULES=transaction.RUNTIME_MODULES
    transaction.DEFAULT_STATE=BASE/'audit/image-upload-fix-20261018/release.json'
    transaction.verify_frontend_scope=scope
    transaction.main()


if __name__ == '__main__':
    # Retired 2026-10-23; main() stays importable for its offline tests.
    import retired_release
    retired_release.refuse(__file__)
