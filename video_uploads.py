"""Bounded resumable staging; no generation calls or provider credentials here."""
import pathlib, secrets, threading, time


class UploadStaging:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}
        self.provider_slots = threading.BoundedSemaphore(2)

    def start(self, root, owner, scope, size):
        if not 0 < size <= 60 * 1024 * 1024:
            raise ValueError('文件大小必须在 1 字节到 60MB 之间')
        with self.lock:
            for uid, row in list(self.rows.items()):
                if time.time()-row['updated'] > 3600 and row['status'] != 'processing':
                    row['path'].unlink(missing_ok=True)
                    del self.rows[uid]
            if len(self.rows) >= 256 or sum(r['status'] not in ('done','error') for r in self.rows.values()) >= 32 or sum(r['owner'] == owner and r['status'] not in ('done','error') for r in self.rows.values()) >= 6:
                raise ValueError('正在上传的文件过多，请先完成已有上传')
            folder = pathlib.Path(root)/'upload_tmp'
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            uid = secrets.token_hex(24)
            path = folder/(uid+'.part')
            path.touch(mode=0o600, exist_ok=False)
            self.rows[uid] = dict(owner=owner, scope=scope, size=size, path=path,
                offset=0, status='receiving', updated=time.time(), lock=threading.Lock())
            return uid

    def get(self, uid, owner):
        with self.lock:
            row = self.rows.get(uid)
            if not row or not secrets.compare_digest(row['owner'], owner):
                raise LookupError('上传记录已过期，请重新选择文件')
            return row

    def chunk(self, uid, owner, offset, data):
        row = self.get(uid, owner)
        if not 0 < len(data) <= 512*1024:
            raise ValueError('上传分块大小无效')
        with row['lock']:
            if row['status'] != 'receiving' or offset < 0 or offset+len(data) > row['size']:
                raise ValueError('上传状态无效')
            if offset < row['offset']:
                with row['path'].open('rb') as f:
                    f.seek(offset)
                    if f.read(len(data)) != data: raise ValueError('重复分块内容不一致')
            elif offset == row['offset']:
                with row['path'].open('r+b') as f:
                    f.seek(offset); f.write(data)
                row['offset'] += len(data)
            else: raise ValueError('上传顺序不一致')
            row['updated'] = time.time()
            return row['offset']

    def finish(self, uid, owner, process):
        row = self.get(uid, owner)
        with row['lock']:
            if row['status'] == 'receiving':
                if row['offset'] != row['size']: raise ValueError('文件尚未传完')
                row['status'] = 'processing'
                def work():
                    try:
                        with self.provider_slots:
                            result = process(row)
                        with row['lock']: row.update(status='done', result=result)
                    except Exception as error:
                        # Never expose provider filenames or credentials.
                        print('VIDEO_UPLOAD_FAILED', type(error).__name__, flush=True)
                        with row['lock']: row.update(status='error', error=(getattr(error, 'public_message', None) if isinstance(getattr(error, 'public_message', None), str) else '云端接收失败，请重新选择文件重试'))
                    finally:
                        row['path'].unlink(missing_ok=True)
                        row['updated'] = time.time()
                try: threading.Thread(target=work, daemon=True).start()
                except Exception:
                    row['status'] = 'receiving'
                    raise
            return {'status':row['status'], **row.get('result',{}), **({'error':row['error']} if 'error' in row else {})}
