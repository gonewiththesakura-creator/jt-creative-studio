import http.client,http.server,importlib.util,json,tempfile,threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scail_http',ROOT/'server.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(tempfile.mkdtemp());m.DATA_DIR=root;m.JOBS_DIR=root/'jobs';m.JOBS_DIR.mkdir();m.JOBS_FILE=root/'jobs.json';m.UPLOAD_CAPABILITIES_FILE=root/'upload_capabilities.json';m._jobs={};m._upload_capabilities={};m.save_jobs=lambda:None;m.run_job=lambda job:None
srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=srv.serve_forever,daemon=True).start()
SESSION='scail-http-session-1234567890';COOKIE='jt_session='+m._encode_session_cookie(SESSION)
def token(key,name,provider):
 w=m.WORKFLOWS['scail2_multi'];return m.issue_upload_capability(provider,w['id'],key,w['rh_media'][key]['type'],name,SESSION)
def req(payload):
 c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=5);raw=json.dumps(payload).encode();c.request('POST','/api/video-generate',raw,{'Content-Type':'application/json','Cookie':COOKIE});r=c.getresponse();data=json.loads(r.read());c.close();return r.status,data
try:
 image_token=token('reference_image','ref.png','api/ref.png');video_token=token('driving_video','motion.mp4','api/motion.mp4')
 base={'workflow':'scail2_multi','prompt':'跳舞','negative_prompt':'','media':{'reference_image':image_token,'driving_video':video_token,'evil':'api/evil.exe'},'params':{'prompt':'跳舞','mask_prompt':'person','mode':'action_transfer','preserve_reference_background':False,'frame_load_cap':0,'evil':'inject'},'client_request_id':'scail-http','workflowId':'attacker','nodeInfoList':[{'nodeId':'999'}]}
 status,data=req(base);assert status==200,(status,data);job=m._jobs[data['job_id']]
 assert job['media']=={'reference_image':'ref.png','driving_video':'motion.mp4'} and job['provider_media']=={'reference_image':'api/ref.png','driving_video':'api/motion.mp4'}
 assert 'evil' not in job['params'] and job['params']['preserve_reference_background'] is False and job['params']['frame_load_cap']==0
 assert job['prompt']=='跳舞' and 'workflowId' not in job and 'nodeInfoList' not in job
 status,again=req(base);assert status==200 and again['job_id']==data['job_id'] and again['deduplicated'] is True
 job['status']='done'
 for patch in [
  {'params':{**base['params'],'mode':'attacker'},'client_request_id':'bad-mode'},
  {'params':{**base['params'],'people':99},'client_request_id':'bad-people'},
  {'media':{'reference_image':'api/ref.png'},'client_request_id':'missing-video'},
 ]:
  payload={**base,**patch};status,error=req(payload);assert status==400,(patch,status,error)
 print('SCAIL2_VIDEO_HTTP_OK',{'job':data['job_id'],'deduplicated':True})
finally:srv.shutdown();srv.server_close()
