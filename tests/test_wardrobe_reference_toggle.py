"""Exercise the real queue admission and provider payload without billed requests."""
import copy
import json
import pytest
from test_server_review_regressions import panel, SESSION_ID, running_server, json_request, session_cookie


@pytest.mark.parametrize('use_clothing', [True, False])
def test_queue_and_redo_preserve_reference_mode(panel, use_clothing):
    workflow=panel.WORKFLOWS['qwen21_wardrobe']
    person=panel.issue_upload_capability('api/person.png',workflow['id'],'person','image','person.png',SESSION_ID)
    media={'person':person}
    if use_clothing:
        media['clothing']=panel.issue_upload_capability('api/dress.png',workflow['id'],'clothing','image','dress.png',SESSION_ID)
    else:
        # Disabled stale/forged reference tokens must never reach the graph.
        media['clothing']='an-expired-token'
    with running_server(panel) as httpd:
        status,body,_=json_request(httpd,'POST','/api/image-edit-generate',{
            'workflow':workflow['id'],'media':media,'params':{'prompt':'蓝色外套','use_clothing':use_clothing},
            'workflow_graph':{'malicious':True},'client_request_id':'wardrobe-toggle-original',
        },cookie=session_cookie(panel))
        assert status==200, body
        job=panel._jobs[body['job_id']]
        assert job['params']['use_clothing'] is use_clothing
        assert set(job['provider_media'])==({'person','clothing'} if use_clothing else {'person'})
        assert set(job['selection_snapshot']['media_names'])==set(job['provider_media'])
        job.update(status='error',provider_status='FAILED')
        status,result,_=json_request(httpd,'POST','/api/image-edit-generate',{
            'redo_job_id':job['id'],'client_request_id':'wardrobe-toggle-redo',
        },cookie=session_cookie(panel))
        assert status==200,result
        child=panel._jobs[result['job_id']]
        assert child['params']['use_clothing'] is use_clothing
        assert child['provider_media']==job['provider_media']
        if not use_clothing:
            graph=panel.rh_build_single_image_graph(child,workflow)
            assert '475' not in graph and 'images.image_2' not in graph['484']['inputs']
            assert graph['470']['inputs']['image']=='api/person.png'
            assert graph['484']['inputs']['prompt']=='蓝色外套'
            assert graph['484']['inputs']['images.image_1']==['470',0]
            assert all(value!=['475',0] for node in graph.values() for value in node['inputs'].values())
        public=json.dumps(panel.public_workflow(workflow))
        assert 'single_image_graph' not in public and 'qwen_image_2.1_int8' not in public


@pytest.mark.parametrize('params,media,missing', [
    ({'use_clothing':True},{'person':'api/person.png'},'图二'),
    ({},{'person':'api/person.png'},'图二'),
    ({'use_clothing':False},{},'人物'),
])
def test_enabled_reference_and_person_stay_required(panel,params,media,missing):
    with pytest.raises(ValueError,match=missing):
        panel.normalize_rh_workflow_inputs(panel.WORKFLOWS['qwen21_wardrobe'],media,params)


def test_single_image_submission_serialization_and_no_ambiguous_retry(panel,monkeypatch):
    workflow=panel.WORKFLOWS['qwen21_wardrobe']
    unchanged=copy.deepcopy(workflow)
    media,params=panel.normalize_rh_workflow_inputs(workflow,{'person':'api/person.png','clothing':'must-not-send'},
        {'prompt':'blue jacket','seed':47,'use_clothing':False,'workflow':'attacker-controlled'})
    job={'provider_media':media,'params':params,'workflow_graph':{'injected':True}}
    calls=[]
    def submit(request,**kwargs):
        calls.append(request)
        return {'code':0,'data':{'taskId':'fixture-task','taskStatus':'QUEUED'}}
    monkeypatch.setattr(panel,'_provider_json_request',submit)
    assert panel.rh_submit_single_image_graph(job,workflow)=='fixture-task'
    body=json.loads(calls[0].data)
    graph=json.loads(body['workflow'])
    assert calls[0].full_url=='https://www.runninghub.ai/task/openapi/create'
    assert body['addMetadata'] is False and body['usePersonalQueue'] is False
    assert graph['481']['inputs']['seed']==47
    assert len(graph)==9 and '475' not in graph and 'images.image_2' not in graph['484']['inputs']
    assert 'injected' not in graph and 'must-not-send' not in body['workflow']
    assert workflow==unchanged
    def uncertain(request,**kwargs):
        calls.append(request)
        raise TimeoutError('lost reply')
    monkeypatch.setattr(panel,'_provider_json_request',uncertain)
    with pytest.raises(RuntimeError,match='not retried'):
        panel.rh_submit_single_image_graph(job,workflow)
    assert len(calls)==2


def test_runner_chooses_single_or_two_image_path(panel,monkeypatch):
    workflow=panel.WORKFLOWS['qwen21_wardrobe']; calls=[]
    monkeypatch.setattr(panel,'rh_submit_single_image_graph',lambda *a,**kw:calls.append('single') or 'fixture-task')
    monkeypatch.setattr(panel,'rh_submit',lambda *a,**kw:calls.append('double') or 'fixture-task')
    monkeypatch.setattr(panel,'persist_provider_task',lambda *a:None)
    monkeypatch.setattr(panel,'_rh_wait_task',lambda *a:[])
    monkeypatch.setattr(panel,'_rh_results_to_images',lambda *a:['fixture-image'])
    for value in [False,True,None]:
        panel.rh_run_generic({'params':{} if value is None else {'use_clothing':value}},workflow)
    assert calls==['single','double','double']
