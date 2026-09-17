import gzip,http.client,http.server,importlib.util,json,tempfile,threading,re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('cachetest',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as td:
 root=Path(td);m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m.FAVORITES_DIR=root/'favorites';m.FAVORITES_DIR.mkdir();m.FAVORITES_FILE=root/'favorites.json';m.STATIC=ROOT/'static'
 srv=m.BoundedHTTPServer(('127.0.0.1',0),m.Handler);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start();p=srv.server_port
 def head(path):
  c=http.client.HTTPConnection('127.0.0.1',p,timeout=15);c.request('GET',path);r=c.getresponse();r.read();x=(r.status,r.getheader('Cache-Control'),r.getheader('ETag'));c.close();return x
 versioned=head('/static/previews/style-cold.webp?v=88594b61ffdc')
 plain=head('/static/previews/style-cold.webp')
 style_data_files=list((ROOT/'static').glob('style-configs.*.json'))
 assert len(style_data_files)==1
 style_data=head('/static/'+style_data_files[0].name)
 def gzip_get(path):
  c=http.client.HTTPConnection('127.0.0.1',p,timeout=15);c.request('GET',path,headers={'Accept-Encoding':'gzip'});r=c.getresponse();body=r.read();x=(r.status,r.getheader('Content-Encoding'),r.getheader('Vary'),gzip.decompress(body));c.close();return x
 style_data_gzip=gzip_get('/static/'+style_data_files[0].name)
 srv.shutdown();srv.server_close()
assert versioned[0]==200 and versioned[1]=='public, max-age=31536000, immutable' and versioned[2]
assert plain[0]==200 and plain[1]=='public, max-age=3600, must-revalidate'
assert style_data[0]==200 and style_data[1]=='public, max-age=31536000, immutable' and style_data[2]
assert style_data_gzip[0]==200 and style_data_gzip[1]=='gzip' and style_data_gzip[2]=='Accept-Encoding'
assert style_data_gzip[3]==style_data_files[0].read_bytes()
print({'versioned':versioned,'plain':plain,'style_data':style_data})
