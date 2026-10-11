"""Bounded, account-scoped previews for remote image results.

The cache contains only derived JPEG previews.  It never replaces or removes
the original provider result, and its key includes the source URL so a reused
result index cannot serve stale pixels.
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import re
import threading
import time

from PIL import Image, ImageOps


THUMB_SIZE = 256
VIEW_SIZE = 1536
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 32 * 1024 * 1024
MAX_CACHE_BYTES = 512 * 1024 * 1024
MAX_CACHE_FILES = 2048
TTL_SECONDS = 24 * 60 * 60
SIZES = {"thumb": THUMB_SIZE, "view": VIEW_SIZE}


class PreviewError(ValueError):
    """A source cannot safely be decoded as an image preview."""


class ResultImageCache:
    """Create and serve two derived sizes while coalescing the source fetch."""

    _decode_lock = threading.Lock()

    def __init__(self, root, *, ttl=TTL_SECONDS, max_bytes=MAX_CACHE_BYTES,
                 max_files=MAX_CACHE_FILES):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = int(ttl)
        self.max_bytes = int(max_bytes)
        self.max_files = int(max_files)
        self._lock = threading.Lock()
        self._keys = {}
        self.cleanup()

    @staticmethod
    def _digest(owner, job_id, index, source_url):
        value = "\x00".join((str(owner), str(job_id), str(index), str(source_url)))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _paths(self, owner, job_id, index, source_url):
        key = self._digest(owner, job_id, index, source_url)
        return {size: self.root / f"{key}.{size}.jpg" for size in SIZES}

    def _fresh(self, path, now=None):
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False
        return stat.st_size > 0 and (now or time.time()) - stat.st_mtime <= self.ttl

    def lookup(self, owner, job_id, index, source_url, size):
        if size not in SIZES:
            raise PreviewError("invalid preview size")
        path = self._paths(owner, job_id, index, source_url)[size]
        if not self._fresh(path):
            return None
        try:
            return path.read_bytes()
        except (FileNotFoundError, OSError):
            return None

    def get_or_create(self, owner, job_id, index, source_url, downloader):
        """Return ``{thumb, view}`` bytes, downloading at most once per key.

        ``downloader`` receives a maximum byte count and returns the source
        bytes. It is called only after ownership has already been checked by
        the HTTP handler.
        """
        paths = self._paths(owner, job_id, index, source_url)
        key = self._digest(owner, job_id, index, source_url)
        with self._lock:
            entry = self._keys.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
            lock = entry[0]
        try:
            with lock:
                now = time.time()
                if all(self._fresh(path, now) for path in paths.values()):
                    try:
                        return {size: paths[size].read_bytes() for size in SIZES}
                    except FileNotFoundError:
                        pass  # A different cache request may have evicted it.
                source = downloader(MAX_SOURCE_BYTES)
                if not isinstance(source, (bytes, bytearray)) or not source:
                    raise PreviewError("empty remote image")
                if len(source) > MAX_SOURCE_BYTES:
                    raise PreviewError("remote image is too large")
                encoded = self._encode_pair(bytes(source))
                temporary = {}
                try:
                    for size, data in encoded.items():
                        tmp = paths[size].with_suffix(f".{os.getpid()}.{threading.get_ident()}.{size}.tmp")
                        with tmp.open("wb") as fp:
                            fp.write(data)
                            fp.flush()
                            os.fsync(fp.fileno())
                        temporary[size] = tmp
                    for size, tmp in temporary.items():
                        tmp.replace(paths[size])
                finally:
                    for tmp in temporary.values():
                        tmp.unlink(missing_ok=True)
                self.cleanup()
                return encoded
        finally:
            with self._lock:
                entry[1] -= 1
                if entry[1] == 0:
                    self._keys.pop(key, None)

    @classmethod
    def _encode_pair(cls, source):
        # Bound decoded memory as well as the source bytes. Serialization keeps
        # several permitted downloads from each decoding a 32 MP image at once.
        # Do not mutate Pillow's global MAX_IMAGE_PIXELS used by other routes.
        with cls._decode_lock:
            try:
                with Image.open(io.BytesIO(source)) as decoded:
                    if decoded.width <= 0 or decoded.height <= 0 or decoded.width * decoded.height > MAX_SOURCE_PIXELS:
                        raise PreviewError("remote image dimensions are too large")
                    if decoded.format not in {'PNG', 'JPEG', 'WEBP', 'GIF', 'AVIF'}:
                        raise PreviewError("unsupported remote image format")
                    decoded.load()
                    oriented = ImageOps.exif_transpose(decoded)
                    try:
                        image = oriented.convert('RGBA') if 'A' in oriented.getbands() or 'transparency' in oriented.info else oriented.convert('RGB')
                    finally:
                        oriented.close()
                try:
                    output = {}
                    for size, edge in SIZES.items():
                        with image.copy() as copy:
                            copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                            with Image.new('RGB', copy.size, 'white') as canvas:
                                canvas.paste(copy, mask=copy.getchannel('A') if copy.mode == 'RGBA' else None)
                                buffer = io.BytesIO()
                                canvas.save(buffer, "JPEG", quality=82, optimize=True, progressive=True)
                                output[size] = buffer.getvalue()
                    return output
                finally:
                    image.close()
            except PreviewError:
                raise
            except Exception as error:
                raise PreviewError("remote image is invalid") from error

    def cleanup(self, now=None):
        now = now or time.time()
        files = []
        try:
            candidates = list(self.root.iterdir())
        except OSError:
            return
        for path in candidates:
            try:
                stat = path.stat()
                # Recover interrupted writes only inside this dedicated cache.
                # Live downloads have a 25-second deadline; active transforms
                # never use these temporary files beyond two minutes.
                is_temporary = (path.name.startswith('source-')
                                or re.fullmatch(r'[0-9a-f]{64}\.(thumb|view)\..*\.tmp', path.name))
                if is_temporary:
                    if now - stat.st_mtime > 120:
                        path.unlink(missing_ok=True)
                    continue
                if path.suffix != '.jpg':
                    continue
                if now - stat.st_mtime > self.ttl:
                    path.unlink(missing_ok=True)
                else:
                    files.append((stat.st_mtime, stat.st_size, path))
            except FileNotFoundError:
                continue
            except OSError:
                continue
        total = sum(item[1] for item in files)
        if len(files) <= self.max_files and total <= self.max_bytes:
            return
        remaining = len(files)
        for _, size, path in sorted(files):
            if remaining <= self.max_files and total <= self.max_bytes:
                break
            try:
                path.unlink(missing_ok=True)
                total -= size
                remaining -= 1
            except OSError:
                continue
