"""Authenticated result proxy. URLs come from trusted job outputs, never queries."""
import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse

MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
MEDIA_TYPES = frozenset(('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif',
                         'video/mp4', 'video/webm', 'video/quicktime'))


def public_endpoint(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or any(ord(c) < 32 for c in url)):
        raise ValueError('invalid media endpoint')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('non-public media endpoint')
    return parsed, addresses[0][4][0]


def open_media(url, byte_range=None):
    headers = {'Accept': 'image/*,video/*', 'Accept-Encoding': 'identity'}
    if byte_range:
        if not re.fullmatch(r'bytes=(?:[0-9]{1,12}-[0-9]{0,12}|-[0-9]{1,12})', byte_range):
            raise ValueError('invalid byte range')
        headers['Range'] = byte_range
    for _ in range(4):
        parsed, address = public_endpoint(url)
        connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=20, context=ssl.create_default_context())
        # Pin the validated address while preserving TLS SNI + hostname checks.
        connection._create_connection = lambda addr, timeout=20, source_address=None, ip=address: socket.create_connection((ip, 443), timeout, source_address)
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
    raise ValueError('media redirect limit')


def stream_media(handler, url, filename):
    slots = handler.server._large_response_slots
    if not slots.acquire(blocking=False):
        handler._send(503, b'{"error":"media capacity busy"}', headers={'Retry-After':'3'})
        return
    connection = None
    started = False
    try:
        connection, response = open_media(url, handler.headers.get('Range'))
        if response.status not in (200, 206):
            handler._send(502, '{"error":"文件暂时无法读取，请稍后重试"}'.encode())
            return
        content_type = (response.getheader('Content-Type') or '').split(';')[0].lower()
        # Some provider CDNs label binary media generically; the trusted output
        # filename supplies a constrained fallback, never HTML/SVG/javascript.
        if content_type == 'application/octet-stream':
            suffix = filename.rsplit('.', 1)[-1].lower()
            content_type = {'mp4':'video/mp4', 'mov':'video/quicktime', 'webm':'video/webm',
                            'png':'image/png', 'jpg':'image/jpeg', 'jpeg':'image/jpeg', 'webp':'image/webp'}.get(suffix, '')
        length = response.getheader('Content-Length')
        if content_type not in MEDIA_TYPES or (length and (not length.isdigit() or int(length) > MAX_MEDIA_BYTES)):
            handler._send(415, b'{"error":"unsupported media"}')
            return
        handler.send_response(response.status)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Cache-Control', 'private, no-store')
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
            data = response.read(256 * 1024)
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
        if connection:
            connection.close()
        slots.release()
