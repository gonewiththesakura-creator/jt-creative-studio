import http.client,http.server,importlib.util,json,tempfile,threading
from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel");spec=importlib.util.spec_from_file_location('fav_video',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp());m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m.FAVORITES_DIR=root/'favorites';m.FAVORITES_DIR.mkdir();m.FAVORITES_FILE=root/'favorites.json';m._favorites={};m.save_favorites=lambda:None;m.download_file_resilient=lambda url,dest,timeout=120:dest.write_bytes(b'\x00\x00\x00\x18ftypmp42fixture')
m._jobs={'v':{'id':'v','status':'done','workflow':'scail2_multi','style_id':'video','prompt':'x','images':[{'url':'https://example.test/out.mp4','remote':True}]}}
srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=srv.serve_forever,daemon=True).start()
def call(method,path,payload=None):
 c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=5);raw=json.dumps(payload).encode() if payload else None;c.request(method,path,raw,{'Content-Type':'application/json'} if raw else {});r=c.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;c.close();return status,data,headers
try:
 status,raw,_=call('POST','/api/favorites',{'job_id':'v','image_index':0});assert status==200,(status,raw);fav=json.loads(raw);assert fav['favorite_media_type']=='video/mp4' and Path(fav['image_path']).suffix=='.mp4',fav
 status,data,headers=call('GET','/api/favorite-image/'+fav['id']);assert status==200 and headers['Content-Type']=='video/mp4' and data[4:8]==b'ftyp'
 status,_,_=call('GET','/api/favorite-preview/'+fav['id']);assert status==415,status
 print('VIDEO_FAVORITE_HTTP_OK',{'suffix':'.mp4','mime':'video/mp4','preview_status':415})
finally:srv.shutdown();srv.server_close()
