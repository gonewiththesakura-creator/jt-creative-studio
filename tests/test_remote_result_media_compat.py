import importlib.util,tempfile,io
from types import SimpleNamespace
import membership_media
from pathlib import Path
P = Path(__file__).resolve().parents[1] / 'server.py'
spec=importlib.util.spec_from_file_location('remote_media_runtime',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp())
samples={
 'png':(bytes((137,80,78,71,13,10,26,10))+b'payload','image/png'),
 'jpg':(b'\xff\xd8\xff\xe0'+b'payload','image/jpeg'),
 'webp':(b'RIFF'+(4).to_bytes(4,'little')+b'WEBPpayload','image/webp'),
 'mp4':(b'\x00\x00\x00\x18ftypmp42'+b'payload','video/mp4'),
}
old_open=membership_media.open_media
for suffix,(data,ctype) in samples.items():
 dest=root/f'favorite.{suffix}'
 def fake_open(*args,**kwargs):
  response=io.BytesIO(data)
  response.status=200
  response.getheader=lambda name,default=None:{'Content-Type':ctype,'Content-Length':str(len(data))}.get(name,default)
  return SimpleNamespace(sock=None,close=lambda:None),response
 membership_media.open_media=fake_open
 size=m.download_file_resilient('https://example.test/result.'+suffix,dest,timeout=3)
 assert size==len(data) and dest.read_bytes()==data
 assert m.downloaded_media_content_type(dest.read_bytes(),dest.name)==ctype
membership_media.open_media=old_open
source=P.read_text(encoding='utf8')
assert 'favorite_media_type' in source
assert 'image_content_type(data, p.name)' in source
print('REMOTE_RESULT_MEDIA_COMPAT_OK')
