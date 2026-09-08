import http.client,http.server,importlib.util,json,tempfile,threading,re
from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel");spec=importlib.util.spec_from_file_location('cachetest',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as td:
 root=Path(td);m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m.FAVORITES_DIR=root/'favorites';m.FAVORITES_DIR.mkdir();m.FAVORITES_FILE=root/'favorites.json';m.STATIC=ROOT/'static'
 srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start();p=srv.server_port
 def head(path):
  c=http.client.HTTPConnection('127.0.0.1',p,timeout=15);c.request('GET',path);r=c.getresponse();r.read();x=(r.status,r.getheader('Cache-Control'),r.getheader('ETag'));c.close();return x
 versioned=head('/static/previews/style-cold.webp?v=88594b61ffdc')
 plain=head('/static/previews/style-cold.webp')
 srv.shutdown();srv.server_close()
assert versioned[0]==200 and versioned[1]=='public, max-age=31536000, immutable' and versioned[2]
assert plain[0]==200 and plain[1]=='public, max-age=3600, must-revalidate'
print({'versioned':versioned,'plain':plain})
