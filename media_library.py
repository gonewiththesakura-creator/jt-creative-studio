"""Two-hour capability-addressed media libraries. Originals never leave this root."""
import hashlib
import json
import math
import os
import pathlib
import re
import secrets
import shutil
import threading
import time


class MediaLibrary:
    TTL = 7200
    MAX_FILE = 60 * 1024 * 1024
    MAX_BYTES = 4 * 1024 ** 3

    def __init__(self, root, clock=time.time):
        self.root = pathlib.Path(root)
        self.clock = clock
        self.lock = threading.RLock()
        self.active = {}

    def _folder(self, code):
        if not re.fullmatch(r'ml_[A-Za-z0-9_-]{43}', str(code)):
            raise LookupError('素材库访问码无效或已过期')
        return self.root / hashlib.sha256(code.encode()).hexdigest()

    def _read(self, folder):
        try:
            row = json.loads((folder / 'index.json').read_text(encoding='utf8'))
        except (OSError, ValueError):
            raise LookupError('素材库不存在或已过期') from None
        if row['expires'] <= self.clock():
            raise LookupError('素材库已过期，请新建素材库')
        return row

    def _save(self, folder, row):
        temp = folder / 'index.tmp'
        with temp.open('w', encoding='utf8') as stream:
            json.dump(row, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(folder / 'index.json')

    def cleanup(self):
        with self.lock:
            if not self.root.exists():
                return
            for folder in self.root.iterdir():
                if not folder.is_dir() or not re.fullmatch(r'[0-9a-f]{64}', folder.name):
                    continue
                if any(key[0] == folder.name and value['status'] == 'processing'
                       for key, value in self.active.items()):
                    continue
                try:
                    self._read(folder)
                except LookupError:
                    shutil.rmtree(folder)
                    self.active = {k: v for k, v in self.active.items() if k[0] != folder.name}

    def create(self):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.cleanup()
            if len(list(self.root.iterdir())) >= 128:
                raise ValueError('临时素材库容量已满，请稍后再试')
            code = 'ml_' + secrets.token_urlsafe(32)
            folder = self._folder(code)
            folder.mkdir(mode=0o700)
            self._save(folder, {'expires': self.clock() + self.TTL, 'assets': {}})
            return dict(code=code, **self.snapshot(code))

    def snapshot(self, code):
        with self.lock:
            folder = self._folder(code)
            row = self._read(folder)
            assets = []
            for aid, asset in row['assets'].items():
                if asset.get('deleted'):
                    continue
                assets.append({k: asset.get(k) for k in
                               ('id', 'name', 'size', 'type', 'ready', 'duration', 'thumbnail')})
                assets[-1]['offset'] = (folder / (aid + '.bin')).stat().st_size
            return {'expires': row['expires'], 'assets': assets, 'limit': 10}

    def start(self, code, name, size, media_type):
        if not 0 < size <= self.MAX_FILE or media_type not in ('image', 'video'):
            raise ValueError('请选择 60MB 以内的视频或图片')
        with self.lock:
            folder = self._folder(code)
            row = self._read(folder)
            if len([a for a in row['assets'].values() if not a.get('deleted')]) >= 10:
                raise ValueError('每个素材库最多 10 个素材，请先删除不需要的素材')
            reserved = 0
            for manifest in self.root.glob('*/index.json'):
                data = json.loads(manifest.read_text(encoding='utf8'))
                reserved += sum(a['size'] for a in data['assets'].values())
            if reserved + size > self.MAX_BYTES:
                raise ValueError('服务器临时素材空间已满，请稍后再试')
            aid = secrets.token_hex(16)
            (folder / (aid + '.bin')).touch(mode=0o600)
            row['assets'][aid] = dict(id=aid, name=name, size=size, type=media_type,
                                      ready=False, duration=None, thumbnail=None)
            self._save(folder, row)
            return {'id': aid, 'offset': 0}

    def _asset(self, code, aid):
        folder = self._folder(code)
        row = self._read(folder)
        asset = row['assets'].get(aid)
        if not asset or asset.get('deleted'):
            raise LookupError('素材已删除或已过期')
        return folder, row, asset, folder / (asset['id'] + '.bin')

    def chunk(self, code, aid, offset, data):
        if not 0 < len(data) <= 512 * 1024:
            raise ValueError('无效的上传分块')
        with self.lock:
            _, _, asset, path = self._asset(code, aid)
            current = path.stat().st_size
            with path.open('r+b') as stream:
                if 0 <= offset < current and offset + len(data) <= current:
                    stream.seek(offset)
                    if stream.read(len(data)) == data:
                        return {'offset': current}
                if asset['ready'] or offset != current or current + len(data) > asset['size']:
                    raise ValueError('上传进度不一致，请刷新素材库后继续')
                stream.seek(current)
                stream.write(data)
            return {'offset': current + len(data)}

    def finish(self, code, aid, thumbnail, duration, validate):
        with self.lock:
            folder, row, asset, path = self._asset(code, aid)
            if path.stat().st_size != asset['size']:
                raise ValueError('文件尚未传完')
            if not asset['ready']:
                asset['content_type'] = validate(path, asset['name'], asset['type'])
                asset['thumbnail'] = thumbnail
                if isinstance(duration, (int, float)) and math.isfinite(duration) and 0 < duration < 86400:
                    asset['duration'] = duration
                asset['ready'] = True
                self._save(folder, row)
            return {'ready': True}

    def delete(self, code, aid):
        with self.lock:
            folder, row, asset, path = self._asset(code, aid)
            active = any(k[:2] == (folder.name, aid) and v['status'] == 'processing'
                         for k, v in self.active.items())
            if active:
                asset['deleted'] = True
            else:
                path.unlink(missing_ok=True)
                del row['assets'][aid]
            self._save(folder, row)
            return {'deleted': True}

    def use(self, code, aid, fingerprint, upload, slots, retry=False):
        with self.lock:
            folder, row, asset, path = self._asset(code, aid)
            if not asset['ready']:
                raise ValueError('素材尚未保存完成')
            cached = asset.get('provider', {})
            if cached.get('fingerprint') == fingerprint:
                return {'status': 'done', 'provider_name': cached['name'],
                        'asset': dict(asset), 'expires': row['expires']}
            key = (folder.name, aid, fingerprint)
            state = self.active.get(key)
            if state and (state['status'] != 'error' or not retry):
                return dict(state)
            if sum(value['status'] == 'processing' for value in self.active.values()) >= 32:
                raise ValueError('素材接收队列已满，请稍后选用')
            self.active[key] = {'status': 'processing'}

            def worker():
                try:
                    with slots:
                        with self.lock:
                            self._asset(code, aid)  # It may have expired while waiting.
                        name = upload(path, asset['name'], asset['content_type'])
                    with self.lock:
                        _, fresh, saved, _ = self._asset(code, aid)
                        saved['provider'] = {'fingerprint': fingerprint, 'name': name}
                        self._save(folder, fresh)
                        self.active.pop(key, None)
                except Exception:
                    with self.lock:
                        self.active[key] = {'status': 'error', 'error': 'RunningHub 暂未接收成功，素材仍保存在库中，可重新选用重试'}
                finally:
                    with self.lock:
                        try:
                            fresh = self._read(folder)
                            if fresh['assets'].get(aid, {}).get('deleted'):
                                path.unlink(missing_ok=True)
                                del fresh['assets'][aid]
                                self._save(folder, fresh)
                        except LookupError:
                            pass
                        self.cleanup()

            threading.Thread(target=worker, daemon=True).start()
            return {'status': 'processing'}
