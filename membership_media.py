"""Authenticated result proxy. URLs come from trusted job outputs, never queries."""
import http.client
import ipaddress
import os
import pathlib
import re
import socket
import ssl
import tempfile
import threading
import time
import urllib.parse

MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
MEDIA_TYPES = frozenset(('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif',
                         'video/mp4', 'video/webm', 'video/quicktime'))


class MediaOwnerSlots:
    """Count active transfers by stable account, not by tab or session cookie."""
    def __init__(self, limit=2):
        self.limit = limit
        self._lock = threading.Lock()
        self._active = {}

    def acquire(self, owner):
        if not owner:
            return True
        with self._lock:
            count = self._active.get(owner, 0)
            if count >= self.limit:
                return False
            self._active[owner] = count + 1
            return True

    def release(self, owner):
        if not owner:
            return
        with self._lock:
            count = self._active.get(owner, 0)
            if count > 1:
                self._active[owner] = count - 1
            else:
                self._active.pop(owner, None)


def acquire_media_slot(handler):
    owners = getattr(handler.server, '_media_owner_slots', None)
    session = getattr(handler, '_membership_session', None) or {}
    owner = (session.get('user') or {}).get('id') if getattr(handler, 'path', '/api/').startswith('/api/') else None
    if owners and not owners.acquire(owner):
        return None
    if not handler.server._large_response_slots.acquire(blocking=False):
        if owners:
            owners.release(owner)
        return None
    return (handler.server._large_response_slots, owners, owner)


def release_media_slot(lease):
    slots, owners, owner = lease
    slots.release()
    if owners:
        owners.release(owner)


def public_endpoint(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or any(ord(c) < 32 or ord(c) == 127 for c in url)):
        raise ValueError('invalid media endpoint')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('non-public media endpoint')
    return parsed, addresses[0][4][0]


def _public_endpoint_before(url, deadline):
    # getaddrinfo has no socket timeout. Its worker never sees credentials or
    # a destination file, and cannot publish a download after the deadline.
    done = threading.Event()
    result = {}

    def resolve():
        try:
            result['endpoint'] = public_endpoint(url)
        except Exception as error:
            result['error'] = error
        finally:
            done.set()

    threading.Thread(target=resolve, daemon=True).start()
    if not done.wait(max(0, deadline - time.monotonic())):
        raise TimeoutError('media resolution timeout')
    if 'error' in result:
        raise result['error']
    return result['endpoint']


def open_media(url, byte_range=None, *, timeout=20, deadline=None):
    headers = {'Accept': 'image/*,video/*', 'Accept-Encoding': 'identity'}
    if byte_range:
        if not re.fullmatch(r'bytes=(?:[0-9]{1,12}-[0-9]{0,12}|-[0-9]{1,12})', byte_range):
            raise ValueError('invalid byte range')
        headers['Range'] = byte_range
    for _ in range(4):
        parsed, address = _public_endpoint_before(url, deadline) if deadline else public_endpoint(url)
        remaining = min(timeout, deadline - time.monotonic()) if deadline else timeout
        if remaining <= 0:
            raise TimeoutError('media connection timeout')
        connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=remaining, context=ssl.create_default_context())
        # Pin the validated address while preserving TLS SNI + hostname checks.
        connection._create_connection = lambda addr, timeout=20, source_address=None, ip=address: socket.create_connection((ip, 443), timeout, source_address)
        timer = None
        if deadline:
            def expire(current=connection):
                sock = current.sock
                if sock:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                current.close()
            timer = threading.Timer(max(.01, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
        try:
            target = urllib.parse.urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            connection.request('GET', target, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, response.getheader('Location', ''))
                response.close()
                connection.close()
                continue
            return connection, response
        except BaseException:
            connection.close()
            raise
        finally:
            if timer:
                timer.cancel()
    raise ValueError('media redirect limit')


def media_content_type(response, filename):
    content_type = (response.getheader('Content-Type') or '').split(';')[0].strip().lower()
    if content_type == 'application/octet-stream':
        content_type = {'mp4':'video/mp4', 'mov':'video/quicktime', 'webm':'video/webm',
                        'png':'image/png', 'jpg':'image/jpeg', 'jpeg':'image/jpeg', 'webp':'image/webp'}.get(
                            filename.rsplit('.', 1)[-1].lower(), '')
    return content_type


def download_media(url, dest, *, timeout=900, max_bytes=MAX_MEDIA_BYTES, validator=None):
    """Bounded, IP-pinned HTTPS archive download with atomic publication.

    A failed attempt leaves the existing archive intact. Callers retain their
    existing retry schedule; this function never resubmits generation work.
    """
    dest = pathlib.Path(dest)
    deadline = time.monotonic() + max(0.01, float(timeout))
    connection = None
    part = None
    try:
        connection, response = open_media(url, timeout=min(5, timeout), deadline=deadline)
        if response.status != 200:
            raise ValueError('media download response rejected')
        length = response.getheader('Content-Length')
        if length and (not length.isdigit() or not 8 <= int(length) <= max_bytes):
            raise ValueError('media download size rejected')
        if media_content_type(response, dest.name) not in MEDIA_TYPES:
            raise ValueError('media download type rejected')
        fd, name = tempfile.mkstemp(prefix=dest.name + '.', suffix='.part', dir=dest.parent)
        part = pathlib.Path(name)
        total, magic = 0, b''
        low_speed_started, low_speed_bytes = time.monotonic(), 0
        with os.fdopen(fd, 'wb') as target:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('media download timeout')
                sock = connection.sock or getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                if sock:
                    sock.settimeout(min(30, remaining))
                chunk = response.read1(min(256 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                low_speed_bytes += len(chunk)
                if total > max_bytes:
                    raise ValueError('media download size rejected')
                if len(magic) < 32:
                    magic += chunk[:32 - len(magic)]
                target.write(chunk)
                elapsed = time.monotonic() - low_speed_started
                if elapsed >= 30:
                    if low_speed_bytes / elapsed < 1024:
                        raise TimeoutError('media download too slow')
                    low_speed_started, low_speed_bytes = time.monotonic(), 0
            if total < 8 or (length and total != int(length)):
                raise ValueError('media download is incomplete')
            if validator and not validator(magic, dest.name):
                raise ValueError('media download signature rejected')
            if time.monotonic() >= deadline:
                raise TimeoutError('media download timeout')
            target.flush()
            os.fsync(target.fileno())
        part.replace(dest)
        return total
    finally:
        if connection:
            connection.close()
        if part:
            part.unlink(missing_ok=True)


def stream_media(handler, url, filename):
    lease = acquire_media_slot(handler)
    if lease is None:
        handler._send(503, b'{"error":"media capacity busy"}', headers={'Retry-After':'3'})
        return
    connection = None
    started = False
    try:
        connection, response = open_media(url, handler.headers.get('Range'), deadline=time.monotonic() + 25)
        if response.status not in (200, 206):
            handler._send(502, '{"error":"文件暂时无法读取，请稍后重试"}'.encode())
            return
        content_type = media_content_type(response, filename)
        # Some provider CDNs label binary media generically; the trusted output
        # filename supplies a constrained fallback, never HTML/SVG/javascript.
        length = response.getheader('Content-Length')
        if content_type not in MEDIA_TYPES or (length and (not length.isdigit() or int(length) > MAX_MEDIA_BYTES)):
            handler._send(415, b'{"error":"unsupported media"}')
            return
        handler.send_response(response.status)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Cache-Control', 'private, no-store')
        handler.send_header('Vary', 'Cookie')
        if length:
            handler.send_header('Content-Length', length)
        content_range = response.getheader('Content-Range', '')
        if content_range and re.fullmatch(r'bytes \d+-\d+/(?:\d+|\*)', content_range):
            handler.send_header('Content-Range', content_range)
        handler.send_header('Accept-Ranges', 'bytes')
        handler.send_header('Content-Disposition', "inline; filename*=UTF-8''" + urllib.parse.quote(filename, safe=''))
        handler.end_headers()
        started = True
        deadline = time.monotonic() + 180
        total = 0
        while time.monotonic() < deadline:
            sock = getattr(connection, 'sock', None) or getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock:
                sock.settimeout(min(20, max(.01, deadline - time.monotonic())))
            # read1 returns available data instead of waiting indefinitely for
            # a complete buffer while a slow peer drips occasional bytes.
            data = response.read1(256 * 1024)
            if not data:
                break
            total += len(data)
            if total > MAX_MEDIA_BYTES:
                break
            handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        if not started:
            handler._send(502, '{"error":"文件暂时无法读取，请稍后重试"}'.encode())
    finally:
        try:
            if connection:
                connection.close()
        finally:
            release_media_slot(lease)
