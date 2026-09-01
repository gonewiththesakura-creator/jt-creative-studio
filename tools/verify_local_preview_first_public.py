import json,time,urllib.request,urllib.error,hashlib,struct
BASE='http://8.210.125.65:8189'
client_id='hermes-local-preview-'+str(time.time_ns())
body={
 'workflow':'anima02','prompt':'adult woman, solo, simple standing portrait, white background, clean composition',
 'negative_prompt':'low quality, blurry, bad anatomy, text, watermark','prompt_mode':'manual',
 'width':512,'height':768,'batch':1,'hd':0,'seed':314159265,'seed_mode':'fixed',
 'style_id':'sketch','mode':'original','sequence_mode':'off','generation_backend':'local',
 'client_request_id':client_id,'selection_snapshot':{'source_page':'e2e','seed':314159265,'generation_backend':'local'}
}
def request(path,data=None,timeout=120):
 req=urllib.request.Request(BASE+path,data=(json.dumps(data).encode() if data is not None else None),headers=({'Content-Type':'application/json'} if data is not None else {}),method=('POST' if data is not None else 'GET'))
 with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,r.headers,r.read()
# Submit then repeat exact idempotency key; second call must return same job.
_,_,raw=request('/api/generate',body);first=json.loads(raw);jid=first['job_id'];print('SUBMITTED',jid)
_,_,raw=request('/api/generate',body);second=json.loads(raw);print('DEDUP',second);assert second['job_id']==jid and second.get('deduplicated') is True
seen=[];started=time.time();job=None
while time.time()-started<1200:
 try:
  _,_,raw=request('/api/job/'+jid,timeout=60);job=json.loads(raw)
 except Exception as e:
  print('POLL_TRANSIENT',type(e).__name__);time.sleep(3);continue
 sample=(job.get('status'),job.get('provider_status'),job.get('progress_pct'),job.get('transfer_index'),job.get('transfer_total'))
 if not seen or sample!=seen[-1]:seen.append(sample);print('STATE',sample)
 if job['status'] in ('done','error'):break
 time.sleep(2)
assert job and job['status']=='done',job
assert job['progress_pct']==100 and len(job['images'])==1 and job.get('comfy_prompt_id')
assert all(a[2]<=b[2] for a,b in zip(seen,seen[1:]) if a[2] is not None and b[2] is not None)
im=job['images'][0];assert im['preview_url'].startswith('/api/local-preview/') and im['archive_status'] in ('pending','downloading','ready')
# Preview first: valid WebP and compact.
_,h,preview=request(im['preview_url'],timeout=120);assert h.get_content_type()=='image/webp' and preview[:4]==b'RIFF' and preview[8:12]==b'WEBP' and len(preview)<2_000_000
print('PREVIEW_OK',len(preview),'elapsed',round(time.time()-started,1))
# Wait for background original archive; task stays done throughout.
archive=None
for _ in range(180):
 _,_,raw=request('/api/job/'+jid,timeout=60);job=json.loads(raw);archive=job['images'][0].get('archive_status')
 if archive=='ready':break
 time.sleep(2)
print('ARCHIVE',archive,job['images'][0].get('size'));assert archive=='ready'
_,h,png=request(im['url'],timeout=300);assert h.get_content_type()=='image/png' and png[:8]==b'\x89PNG\r\n\x1a\n' and len(png)>10000
print('ORIGINAL_OK',len(png),hashlib.sha256(png).hexdigest()[:16])
print('LOCAL_PREVIEW_FIRST_E2E_OK',jid,seen)
