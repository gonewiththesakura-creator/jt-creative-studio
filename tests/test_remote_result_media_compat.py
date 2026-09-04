import importlib.util,subprocess,tempfile
from pathlib import Path
P=Path(r"D:/LAN-Share/lora/_work/comfy_panel/server.py")
spec=importlib.util.spec_from_file_location('remote_media_runtime',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp())
samples={
 'png':(bytes((137,80,78,71,13,10,26,10))+b'payload','image/png'),
 'jpg':(b'\xff\xd8\xff\xe0'+b'payload','image/jpeg'),
 'webp':(b'RIFF'+(4).to_bytes(4,'little')+b'WEBPpayload','image/webp'),
}
old_run=subprocess.run
for suffix,(data,ctype) in samples.items():
 dest=root/f'favorite.{suffix}'
 def fake_run(cmd,**kwargs):
  Path(cmd[cmd.index('-o')+1]).write_bytes(data)
  return subprocess.CompletedProcess(cmd,0,'','')
 m.subprocess.run=fake_run
 size=m.download_file_resilient('https://example.test/result.'+suffix,dest,timeout=3)
 assert size==len(data) and dest.read_bytes()==data
 assert m.image_content_type(dest.read_bytes(),dest.name)==ctype
m.subprocess.run=old_run
source=P.read_text(encoding='utf8')
assert 'favorite_media_type' in source
assert 'image_content_type(data, p.name)' in source
print('REMOTE_RESULT_MEDIA_COMPAT_OK')
