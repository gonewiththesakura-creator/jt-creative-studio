"""Verified optimized graph, private submission, and account-scoped queue contracts."""
import copy
import itertools
import json

import pytest
from test_membership_http import membership_env, panel, activate, json_request


def make_job(panel, media=None, **overrides):
    w=panel.WORKFLOWS['h3_reference_optimized']
    media,params=panel.normalize_rh_workflow_inputs(w,media if media is not None else {'reference_image':'api/person.png'},
        {'prompt':'Move naturally.',**overrides})
    return w,dict(id='test-task',provider_media=media,params=params,prompt=params['prompt'])


@pytest.mark.parametrize('second,save_first',[(False,True),(True,True),(True,False)])
def test_branch_wiring_and_pruning(panel,second,save_first):
    w,j=make_job(panel,second_pass=second,save_first=save_first)
    before=copy.deepcopy(w);g=panel.rh_build_h3_optimized_graph(j,w)
    assert ('214' in g)==second and ('264' in g)==save_first
    assert ('140' in g)==second and ('144' in g)==second
    if second:
        assert g['139']['inputs']['av_latent']==['226',1]
        assert g['140']['inputs']['latent']==['139',0]
        assert g['140']['inputs']['mode.scale']==['283',0]
        assert g['144']['inputs']['latent_image']==['142',0]
        assert g['144']['inputs']['sigmas']==['289',1]
    assert g['226']['inputs']['sigmas']==['289',0]
    assert g['265']['inputs']['ref_images.ref_image_0']==['51',0]
    assert g['51']['inputs']['image']=='api/person.png'
    assert all(node not in g for node in ('49','50','27','25','26','48','14','15'))
    for row in g.values():
        for value in row['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[1],int):assert value[0] in g
        if row['class_type']=='VHS_VideoCombine':
            assert row['inputs']['save_metadata'] is False and row['inputs']['frame_rate']==24
    assert w==before


def test_media_trimming_audio_and_lora_bypass(panel):
    media={'reference_image_9':'api/last.png','source_video_2':'api/motion.mp4','reference_audio_3':'api/music.wav'}
    w,j=make_job(panel,media,source_video_2_audio=True,source_video_2_skip=12,source_video_2_frames=96,
        lora_1_enabled=False,lora_2_enabled=False,lora_3_enabled=False,memory_attention=False)
    g=panel.rh_build_h3_optimized_graph(j,w);inputs=g['265']['inputs']
    assert inputs['ref_images.ref_image_0']==['201',0]
    assert inputs['ref_videos.ref_video_0']==['25',0]
    assert inputs['ref_video_audios.ref_video_audio_0']==['25',2]
    assert inputs['ref_audios.ref_audio_0']==['15',0]
    assert g['25']['inputs']['skip_first_frames']==12
    assert g['25']['inputs']['frame_load_cap']==96 and g['25']['inputs']['force_rate']==24
    assert not set(('53','128','322','58')) & g.keys()
    assert g['223']['inputs']['model']==g['261']['inputs']['model']==['192',0]
    w,j=make_job(panel,lora_3_enabled=True,lora_3_strength=.4)
    g=panel.rh_build_h3_optimized_graph(j,w)
    assert g['128']['inputs']['model']==['322',0] and g['322']['inputs']['strength_model']==.4


def test_defaults_seed_and_public_boundary(panel):
    w,j=make_job(panel);assert j['params']['second_pass'] is False
    g=panel.rh_build_h3_optimized_graph(j,w);seed=g['256']['inputs']['noise_seed']
    assert 0<=seed<=2**53-1
    assert panel.rh_build_h3_optimized_graph(j,w)['256']['inputs']['noise_seed']==seed
    j['id']='another-task';assert panel.rh_build_h3_optimized_graph(j,w)['256']['inputs']['noise_seed']!=seed
    j['params']['seed']=42;j['params']['workflow']={'evil':True};j['params']['api_key']='evil'
    j['prompt']='unvalidated bypass'
    g=panel.rh_build_h3_optimized_graph(j,w)
    assert g['256']['inputs']['noise_seed']==42 and g['263']['inputs']['text']=='Move naturally.'
    public=json.dumps(panel.public_workflow(w))
    for private in ('rh_graph','safetensors','rh_workflow_id','2111727257252290561','source_editor_json_sha256'):
        assert private not in public


@pytest.mark.parametrize('params',[
    {'save_first':False,'second_pass':False},{'save_first':False,'save_second':False,'second_pass':True},
    {'total_steps':8,'first_steps':9},{'total_steps':8,'first_steps':8,'second_pass':True},
    {'duration':31},{'megapixels':5},{'second_pass':'maybe'}, {'aspect_ratio':'evil'},
])
def test_invalid_settings_rejected(panel,params):
    with pytest.raises(ValueError):make_job(panel,**params)


def test_reference_limits(panel):
    with pytest.raises(ValueError):make_job(panel,{})
    with pytest.raises(ValueError):make_job(panel,{'reference_audio':'api/test.wav'})
    w=panel.WORKFLOWS['h3_reference_optimized']
    media={k:'api/test.'+{'image':'png','video':'mp4','audio':'wav'}[v['type']] for k,v in w['rh_media'].items()}
    with pytest.raises(ValueError):make_job(panel,media)
    media=dict(list(media.items())[:12]);w,j=make_job(panel,media)
    g=panel.rh_build_h3_optimized_graph(j,w)
    assert len([k for k in g['265']['inputs'] if k.startswith(('ref_images.','ref_videos.'))])==12


def test_private_submission_run_id(panel,monkeypatch):
    w,j=make_job(panel,second_pass=True);calls=[]
    def request(req,timeout):
        body=json.loads(req.data);calls.append(body)
        assert body['workflowId']=='2111727257252290561' and body['nodeInfoList']==[]
        assert body['addMetadata'] is False and '144' in json.loads(body['workflow'])
        return dict(code=0,data=dict(taskId='offline-task'))
    monkeypatch.setattr(panel,'_provider_json_request',request)
    assert panel.rh_submit_h3_multi(j,w)=='offline-task' and len(calls)==1


def test_queue_ownership_redo_idempotency(membership_env):
    env=membership_env;activate(env,video_units=20);activate(env,user='bob',video_units=20)
    token=env.panel.issue_upload_capability('api/test.png','h3_reference_optimized','reference_image','image','test.png',env.users['alice']['owner_key'])
    payload=dict(workflow='h3_reference_optimized',prompt='Keep original clothing.',media={'reference_image':token},
                 params={'second_pass':True,'lora_2_strength':.35},client_request_id='optimized-first')
    assert json_request(env,'POST','/api/video-generate',payload,None)[0]==401
    assert json_request(env,'POST','/api/video-generate',payload,'alice',{'X-CSRF-Token':'bad'})[0]==403
    assert json_request(env,'POST','/api/video-generate',payload,'bob')[0]==400
    status,body,_=json_request(env,'POST','/api/video-generate',payload,'alice');assert status==200,body
    job=env.panel._jobs[body['job_id']];assert job['status']=='queued' and job['membership_reserved']
    duplicate=json_request(env,'POST','/api/video-generate',payload,'alice')[1]
    assert duplicate['job_id']==job['id'] and duplicate['deduplicated']
    assert json_request(env,'GET','/api/video-queue',None,'bob')[1]['jobs']==[]
    job.update(status='error',provider_status='FAILED',video_queued=False,error='test failure')
    status,body,_=json_request(env,'POST','/api/video-generate',dict(redo_job_id=job['id'],client_request_id='optimized-redo'),'alice')
    assert status==200,body
    child=env.panel._jobs[body['job_id']]
    assert child['provider_media']==job['provider_media'] and child['prompt']==job['prompt']
    assert child['params']['second_pass'] is True and child['params']['lora_2_strength']==.35
    assert json_request(env,'POST','/api/video-generate',dict(redo_job_id=job['id'],client_request_id='steal'),'bob')[0]==404
    assert not env.provider_calls
