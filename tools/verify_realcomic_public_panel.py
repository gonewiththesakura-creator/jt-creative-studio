import base64,hashlib,json,pathlib,time,urllib.request,urllib.error
from PIL import Image,ImageStat

BASE='http://8.210.125.65:8189'
SOURCE=pathlib.Path.home()/r'AppData/Local/Temp/liuli_step600_local_smoke.png'
REQUEST_ID='realcomic-public-liuli-e2e-20260904-v1'
assert SOURCE.exists() and SOURCE.stat().st_size>50000

def request(path,payload=None,timeout=180):
 data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
 req=urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'} if data else {})
 try:
  with urllib.request.urlopen(req,timeout=timeout) as response:return response.status,json.load(response)
 except urllib.error.HTTPError as error:
  body=json.loads(error.read() or b'{}');return error.code,body

with urllib.request.urlopen(BASE+'/api/health',timeout=30) as response:health=json.load(response)
assert health.get('ok') and health.get('running_cloud') is None,health
blob=SOURCE.read_bytes();status,uploaded=request('/api/realcomic-upload',{'filename':'liuli_step600_public_e2e.png','data':base64.b64encode(blob).decode()},240)
assert status==200 and uploaded.get('fileName'),(status,uploaded);print('UPLOAD',{'status':status,'input_bytes':len(blob),'mediaType':uploaded.get('mediaType')})
payload={'workflow':'realcomic','media':{'source_image':uploaded['fileName']},'params':{'requirements':'保留原图构图和汉服服装，转换为自然真实的成年女性，去除水印和文字'},'client_request_id':REQUEST_ID,'selection_snapshot':{'source_page':'realcomic','requirements':'保留原图构图和汉服服装，转换为自然真实的成年女性，去除水印和文字','source_filename':SOURCE.name,'generation_backend':'cloud','e2e':True}}
status,accepted=request('/api/ai-app-generate',payload,180);assert status==200 and accepted.get('job_id'),(status,accepted);job_id=accepted['job_id'];print('ACCEPTED',{'job_id':job_id,'deduplicated':accepted.get('deduplicated',False)})
status,duplicate=request('/api/ai-app-generate',payload,180);assert status==200 and duplicate.get('job_id')==job_id and duplicate.get('deduplicated') is True,(status,duplicate);print('IDEMPOTENT',{'job_id':job_id,'deduplicated':True})
started=time.time();last=None;job=None
while time.time()-started<1800:
 status,job=request('/api/job/'+job_id,None,60);assert status==200,(status,job)
 state=(job.get('status'),job.get('provider_status'),job.get('progress_pct'))
 if state!=last:print('STATE',state);last=state
 if job.get('status') in ('done','error'):break
 time.sleep(4)
assert job and job.get('status')=='done' and job.get('images'),job
image=job['images'][0];url=image['url']
with urllib.request.urlopen(url,timeout=300) as response:result=response.read();ctype=response.headers.get('Content-Type','')
out=pathlib.Path.home()/r'AppData/Local/Temp/realcomic_public_panel_result.png';out.write_bytes(result)
with Image.open(out) as im:
 im.load();stats=ImageStat.Stat(im.convert('RGB'));meta={'format':im.format,'size':im.size,'bytes':len(result),'stddev':[round(x,2) for x in stats.stddev],'sha256':hashlib.sha256(result).hexdigest(),'content_type':ctype,'job_id':job_id,'provider_task':job.get('rh_task_id'),'elapsed':job.get('elapsed')}
assert meta['format'] in ('PNG','JPEG','WEBP') and max(meta['stddev'])>20 and meta['bytes']>50000,meta
print('RESULT',json.dumps(meta,ensure_ascii=False))
# Favorite exactly once for this real task, then verify durable copy and media type.
_,favorites=request('/api/favorites');existing=next((x for x in favorites if x.get('job_id')==job_id),None)
if existing is None:
 status,favorite=request('/api/favorites',{'job_id':job_id,'image_index':0},240);assert status==200,(status,favorite)
else:favorite=existing
with urllib.request.urlopen(BASE+favorite['image_url'],timeout=180) as response:fav_blob=response.read();fav_type=response.headers.get('Content-Type','')
assert len(fav_blob)>50000 and fav_type.startswith('image/'),(len(fav_blob),fav_type)
_,history=request('/api/jobs');assert any(x.get('id')==job_id and x.get('workflow')=='realcomic' and x.get('status')=='done' for x in history),(job_id,history)
print('FAVORITE_HISTORY',{'favorite_id':favorite.get('id'),'favorite_type':fav_type,'favorite_bytes':len(fav_blob),'history':True})
print('PUBLIC_REALCOMIC_PANEL_E2E_OK',out,job_id)
