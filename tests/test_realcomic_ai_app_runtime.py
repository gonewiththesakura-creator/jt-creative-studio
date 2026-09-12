import importlib.util,json
from pathlib import Path
P = Path(__file__).resolve().parents[1] / 'server.py'
spec=importlib.util.spec_from_file_location('realcomic_runtime',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
w=next(x for x in m.CONFIG['workflows'] if x['id']=='realcomic')
job={'workflow':'realcomic','media':{'source_image':'source.png'},'provider_media':{'source_image':'api/source.png'},'params':{'requirements':'保留构图并去除文字'}}
node_info=m.rh_build_ai_app_node_info(job,w)
assert node_info==[
 {'nodeId':'504','fieldName':'image','fieldValue':'api/source.png'},
 {'nodeId':'491','fieldName':'text','fieldValue':'保留构图并去除文字'},
]
class Resp:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self):return json.dumps({'taskId':'task-ai-app','status':'RUNNING','errorCode':'','errorMessage':''}).encode()
captured={}
def open_bounded(req,data,timeout):
 captured['url']=req.full_url;captured['headers']={k.lower():v for k,v in req.header_items()};captured['body']=json.loads(req.data);return Resp()
m._urlopen_bounded=open_bounded;m.RH_KEY='test-secret-not-real'
task=m.rh_submit_ai_app(w['rh_ai_app_id'],node_info)
assert task=='task-ai-app'
assert captured['url']=='https://www.runninghub.ai/openapi/v2/run/ai-app/2025090022289973249'
assert captured['body']=={'nodeInfoList':node_info}
assert captured['headers']['authorization']=='Bearer test-secret-not-real'
images=m._rh_results_to_images([{'fileUrl':'https://example.test/out.png','fileType':'png'}],'task-ai-app')
assert images[0]['url']=='https://example.test/out.png' and images[0]['remote'] is True
assert m.image_content_type(b'\x89PNG\r\n\x1a\nrest','x.png')=='image/png'
assert m.image_content_type(b'not-image','x.png') is None
print('REALCOMIC_AI_APP_RUNTIME_OK')
