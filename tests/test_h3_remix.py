"""Graph/HTTP contracts for the imported Remix workflow; no paid generation."""
import copy
import io
import itertools
import json
import time
import wave

import pytest
from test_membership_http import membership_env, panel, activate, json_request
from video_uploads import UploadStaging


def remix_job(panel, **overrides):
    workflow=panel.WORKFLOWS['h3_remix_full']
    media={'reference_image':'api/person.png','source_video':'api/motion.mp4','reference_audio':'api/music.wav'}
    media,params=panel.normalize_rh_workflow_inputs(workflow,media,{'prompt':'Move naturally.',**overrides})
    return workflow,dict(provider_media=media,params=params,prompt=params['prompt'])


@pytest.mark.parametrize('second,face',itertools.product([False,True],repeat=2))
def test_optional_sampling_is_pruned_and_output_links_are_valid(panel,second,face):
    w,j=remix_job(panel,second_pass=second,face_refine=face)
    before=copy.deepcopy(w)
    g=panel.rh_build_h3_remix_graph(j,w)
    assert ('310' in g)==second
    assert ('340' in g)==face
    assert ('351' in g)==second
    assert ('350' in g)==face
    assert '349' in g and '297' not in g
    if face:assert g['340']['inputs']['images']==['323' if second else '298',0]
    for node in g.values():
        for value in node['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[1],int):assert value[0] in g
        if node['class_type']=='VHS_VideoCombine':assert node['inputs']['save_metadata'] is False
    assert before==w


def test_media_toggles_loras_trims_and_security(panel):
    w,j=remix_job(panel,original_audio=True,sparse_attention=False,lora_1_enabled=False,
                  lora_2_strength=.3,lora_3_bypass=False,source_video_start=1.2,source_video_end=3.4,
                  use_face_reference=True,face_refine=False)
    j['provider_media']['face_reference']='api/unused.png'
    j['params'].update(prompt_optimizer_api_key='attacker',prompt_optimizer_api_url='http://127.0.0.1',workflow={'evil':True})
    g=panel.rh_build_h3_remix_graph(j,w);setup=g['295']['inputs']
    assert '339' not in g and '327' not in g and '283' not in g
    assert g['298']['inputs']['audio']==['287',7]
    assert g['284']['inputs']['lora_1']['on'] is False
    assert g['342']['inputs']['lora_1']['strength']==.3
    assert g['342']['inputs']['lora_2']['bypass'] is False
    assert setup['prompt_optimizer_api_key']==setup['prompt_optimizer_api_url']==''
    rows=json.loads(setup['embedded_media_json'])
    assert [r['filename'] for r in rows]==['api/person.png','api/motion.mp4','api/music.wav']
    assert rows[1]['audio_trim']=='00:01:200-00:03:400'
    assert setup['media_2']=='api/motion.mp4'
    public=json.dumps(panel.public_workflow(w))
    for secret in ('rh_graph','safetensors','rh_workflow_id','prompt_optimizer_api_key','2111635037301452801'):
        assert secret not in public
    w,j=remix_job(panel,mode='image',face_refine=False)
    assert j['provider_media']=={'reference_image':'api/person.png'}
    assert len(json.loads(panel.rh_build_h3_remix_graph(j,w)['295']['inputs']['embedded_media_json']))==1


def test_face_reference_and_only_final_output(panel):
    w,j=remix_job(panel,save_first=False,save_second=False)
    j['params']['use_face_reference']=True;j['provider_media']['face_reference']='api/face.png'
    g=panel.rh_build_h3_remix_graph(j,w)
    assert '349' not in g and '351' not in g and '350' in g
    assert g['340']['inputs']['reference_face']==['339',0]
    assert g['339']['inputs']['image']=='api/face.png'
    assert len(json.loads(g['295']['inputs']['embedded_media_json']))==3


def test_advanced_submission_uses_run_id_and_private_graph(panel,monkeypatch):
    w,j=remix_job(panel,second_pass=False,face_refine=False)
    calls=[]
    def request(req,timeout):
        body=json.loads(req.data);calls.append(body)
        assert body['workflowId']=='2111635037301452801'
        assert body['nodeInfoList']==[] and body['addMetadata'] is False
        assert '310' not in json.loads(body['workflow'])
        return dict(code=0,data=dict(taskId='offline-task'))
    monkeypatch.setattr(panel,'_provider_json_request',request)
    assert panel.rh_submit_h3_multi(j,w)=='offline-task'
    assert len(calls)==1


@pytest.mark.parametrize('params',[
    {'save_first':False,'save_second':False,'save_face':False},
    {'mode':'image','original_audio':True},
    {'mode':'image','audio_duration_auto':'video'},
    {'source_video_start':6,'source_video_end':2},
    {'duration':31},{'second_pass':'maybe'}, {'mode':'executable'},
])
def test_invalid_requests_never_reach_provider(panel,params):
    with pytest.raises(ValueError):remix_job(panel,**params)


def test_new_workflow_queue_ownership_redo_and_idempotency(membership_env):
    env=membership_env;activate(env,video_units=20);activate(env,user='bob',video_units=20)
    # Use the account's stable upload owner identifier, as production does.
    session_id=env.users['alice']['owner_key']
    token=env.panel.issue_upload_capability('api/test.png','h3_remix_full','reference_image','image','test.png',session_id)
    payload=dict(workflow='h3_remix_full',prompt='test prompt',media={'reference_image':token},params={'face_refine':False,'second_pass':False},client_request_id='remix-first')
    assert json_request(env,'POST','/api/video-generate',payload,None)[0]==401
    assert json_request(env,'POST','/api/video-generate',payload,'alice',{'X-CSRF-Token':'bad'})[0]==403
    assert json_request(env,'POST','/api/video-generate',payload,'bob')[0]==400
    status,body,_=json_request(env,'POST','/api/video-generate',payload,'alice');assert status==200,body
    job=env.panel._jobs[body['job_id']]
    assert job['status']=='queued' and job['membership_reserved']
    duplicate=json_request(env,'POST','/api/video-generate',payload,'alice')[1]
    assert duplicate['job_id']==job['id'] and duplicate['deduplicated']
    assert json_request(env,'GET','/api/video-queue',None,'bob')[1]['jobs']==[]
    job.update(status='error',provider_status='FAILED',video_queued=False,error='test failure')
    status,body,_=json_request(env,'POST','/api/video-generate',dict(redo_job_id=job['id'],client_request_id='remix-redo'),'alice')
    assert status==200,body
    child=env.panel._jobs[body['job_id']]
    assert child['provider_media']==job['provider_media']
    assert child['params']['second_pass'] is False
    assert child['params']['lora_2_strength']==job['params']['lora_2_strength']
    assert child['prompt']==job['prompt']
    assert json_request(env,'POST','/api/video-generate',dict(redo_job_id=job['id'],client_request_id='steal'),'bob')[0]==404
    assert not env.provider_calls


def test_audio_upload_uses_authenticated_chunk_pipeline(membership_env,monkeypatch):
    env=membership_env;activate(env);activate(env,user='bob')
    monkeypatch.setattr(env.panel,'_video_upload_staging',UploadStaging())
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*800)
    raw=buffer.getvalue();calls=[]
    def provider(path,name,ctype):
        calls.append((path.read_bytes(),name,ctype));return 'api/test.wav'
    monkeypatch.setattr(env.panel,'rh_upload_temp_file',provider)
    status,body,_=json_request(env,'POST','/api/upload-start',dict(workflow='h3_remix_full',input_key='reference_audio',filename='test.wav',size=len(raw)),'alice')
    assert status==200,body
    uid=body['upload_id'];path='/api/upload-chunk?id='+uid+'&offset=0'
    assert json_request(env,'POST',path,None,'bob',{'Content-Type':'application/octet-stream'},raw=raw)[0]==404
    assert json_request(env,'POST',path,None,'alice',{'Content-Type':'application/octet-stream'},raw=raw)[0]==200
    for _ in range(50):
        status,body,_=json_request(env,'POST','/api/upload-finish',{'upload_id':uid},'alice')
        if body.get('uploadToken'):break
        time.sleep(.01)
    assert status==200 and body.get('uploadToken'),body
    assert calls==[(raw,'test.wav','audio/wav')]
    with pytest.raises(ValueError):env.panel.upload_media_content_type(raw,'test.png','image')
    with pytest.raises(ValueError):env.panel.upload_media_content_type(b'<script>bad</script>','test.wav','audio')
