"""The queued image endpoint uses the same account, CSRF and quota boundaries."""
import pytest
from test_membership_http import membership_env, panel, activate, json_request


@pytest.mark.parametrize('path', ['/api/image-edit-generate','/api/image-edit-queue','/api/image-edit-clear'])
def test_image_actions_require_session_and_csrf(membership_env, path):
    env=membership_env
    status,_,_=json_request(env,'POST',path,{},None)
    assert status==401
    status,_,_=json_request(env,'POST',path,{},'alice',{'X-CSRF-Token':'bad'})
    assert status==403
    assert not env.panel._jobs


def test_image_queue_reserves_image_quota_and_does_not_start_paid_work(membership_env):
    env=membership_env
    activate(env,image_units=1,video_units=10)
    payload={'workflow':'member-workflow','params':{'prompt':'private image edit'},'client_request_id':'member-image-1'}
    status,body,_=json_request(env,'POST','/api/image-edit-generate',payload,'alice')
    assert status==200,body
    job=env.panel._jobs[body['job_id']]
    assert job['style_id']=='realism' and job['status']=='queued' and job['membership_reserved']
    assert job['owner_user_id']==env.users['alice']['id']
    status,duplicate,_=json_request(env,'POST','/api/image-edit-generate',payload,'alice')
    assert status==200 and duplicate['job_id']==job['id']
    status,rejected,_=json_request(env,'POST','/api/image-edit-generate',dict(payload,client_request_id='member-image-2'),'alice')
    assert status==403 and rejected['code']=='quota_exhausted'
    status,rows,_=json_request(env,'GET','/api/image-edit-queue',None,'bob')
    assert status==200 and not rows['jobs']
    status,_,_=json_request(env,'POST','/api/image-edit-queue',{'job_id':job['id'],'revision':0,'action':'cancel'},'bob')
    assert status==404 and job['status']=='queued'
    status,_,_=json_request(env,'POST','/api/image-edit-queue',{'job_id':job['id'],'revision':0,'action':'cancel'},'alice')
    assert status==200 and job['status']=='cancelled'
    env.gateway.settle(job)
    status,_,_=json_request(env,'POST','/api/image-edit-generate',dict(payload,client_request_id='member-image-3'),'alice')
    assert status==200
    assert not env.provider_calls
