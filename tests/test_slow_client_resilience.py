import importlib.util,socket,threading,time,urllib.error,urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('slowhard',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.MAX_HTTP_WORKERS>=16,m.MAX_HTTP_WORKERS
assert 'def handle(self):' in (ROOT/'server.py').read_text(encoding='utf8').split('class Handler',1)[1]
srv=m.BoundedHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=srv.serve_forever,daemon=True).start();port=srv.server_port
slow=[]
try:
 for _ in range(8):
  s=socket.create_connection(('127.0.0.1',port),timeout=2);s.sendall(b'GET /api/health HTTP/1.1\r\nHost: x\r\nX-Slow: ');slow.append(s)
 time.sleep(.2);start=time.perf_counter();r=urllib.request.urlopen(f'http://127.0.0.1:{port}/api/workflows',timeout=2);body=r.read();elapsed=time.perf_counter()-start
 assert r.status==200 and body.startswith(b'[') and elapsed<1,(r.status,elapsed)
 assert srv.request_queue_size>=64,srv.request_queue_size
 assert m.CLIENT_SOCKET_TIMEOUT<=10,m.CLIENT_SOCKET_TIMEOUT
 assert m.MAX_REQUESTS_PER_CONNECTION==1,m.MAX_REQUESTS_PER_CONNECTION
 assert m.MAX_LARGE_REQUESTS==2,m.MAX_LARGE_REQUESTS
 assert hasattr(srv,'_large_request_slots')
 extra=[]
 for _ in range(m.MAX_HTTP_WORKERS-len(slow)):
  s=socket.create_connection(('127.0.0.1',port),timeout=2);s.sendall(b'GET /api/health HTTP/1.1\r\nHost: x\r\nX-Slow: ');extra.append(s)
 time.sleep(.2);start=time.perf_counter()
 try:urllib.request.urlopen(f'http://127.0.0.1:{port}/api/live',timeout=2);status=200
 except urllib.error.HTTPError as error:status=error.code
 assert status==503 and time.perf_counter()-start<1,(status,time.perf_counter()-start)
 assert srv.liveness_snapshot()['overload_rejections']>=1
 slow.extend(extra)
 print('SLOW_CLIENT_RESILIENCE_OK',{'slow_clients':len(slow),'seconds':round(elapsed,3),'workers':m.MAX_HTTP_WORKERS,'backlog':srv.request_queue_size})
finally:
 for s in slow:
  try:s.close()
  except:pass
 srv.shutdown();srv.server_close()
