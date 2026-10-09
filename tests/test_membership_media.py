import io
from types import SimpleNamespace
import threading

import pytest

import membership_media as media


@pytest.mark.parametrize('url', ['http://cdn.example/video.mp4', 'https://user:pass@cdn.example/a',
    'https://cdn.example:444/a', 'https://cdn.example/\nheader'])
def test_invalid_endpoints_rejected_before_dns(monkeypatch, url):
    monkeypatch.setattr(media.socket, 'getaddrinfo', lambda *a, **kw: pytest.fail('must not resolve'))
    with pytest.raises(ValueError):
        media.public_endpoint(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', 'fc00::1'])
def test_private_dns_is_rejected(monkeypatch, address):
    monkeypatch.setattr(media.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',(address,443))])
    with pytest.raises(ValueError):
        media.public_endpoint('https://cdn.example/video.mp4')


def test_all_dns_addresses_must_be_public(monkeypatch):
    monkeypatch.setattr(media.socket, 'getaddrinfo', lambda *a, **kw: [(2,1,6,'',(ip,443)) for ip in ['8.8.8.8','127.0.0.1']])
    with pytest.raises(ValueError):
        media.public_endpoint('https://cdn.example/a')


@pytest.mark.parametrize('byte_range', ['bytes=0-1,3-4', 'bytes=a-b', 'bytes=1-\r\nHost: x'])
def test_invalid_range_does_not_fetch(monkeypatch, byte_range):
    monkeypatch.setattr(media, 'public_endpoint', lambda *a: pytest.fail('must not fetch'))
    with pytest.raises(ValueError):
        media.open_media('https://cdn.example/a', byte_range)


def test_stream_preserves_range_and_does_not_forward_cookie(monkeypatch):
    chunks = iter([b'media', b''])
    response = SimpleNamespace(status=206, getheader=lambda k,d=None: {
        'Content-Type':'video/mp4', 'Content-Length':'5', 'Content-Range':'bytes 5-9/10'}.get(k,d),
        read=lambda n: next(chunks))
    closed=[]
    def opened(url, byte_range):
        assert byte_range=='bytes=5-9'
        return SimpleNamespace(close=lambda: closed.append(True)), response
    monkeypatch.setattr(media, 'open_media', opened)
    headers={}
    status=[]
    handler=SimpleNamespace(headers={'Range':'bytes=5-9', 'Cookie':'secret'},
        server=SimpleNamespace(_large_response_slots=threading.BoundedSemaphore(1)),
        send_response=lambda x:status.append(x), send_header=lambda k,v:headers.update({k:v}),
        end_headers=lambda:None, wfile=io.BytesIO(), _send=lambda *a,**kw:pytest.fail('unexpected failure'))
    media.stream_media(handler,'https://cdn.example/a.mp4','a.mp4')
    assert status==[206] and handler.wfile.getvalue()==b'media'
    assert headers['Content-Range']=='bytes 5-9/10'
    assert headers['Cache-Control']=='private, no-store'
    assert closed and handler.server._large_response_slots.acquire(False)
