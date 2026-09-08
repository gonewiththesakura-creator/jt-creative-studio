import importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
CONFIG=json.loads((ROOT/'config.json').read_text(encoding='utf8'))
BY_ID={w['id']:w for w in CONFIG['workflows']}
spec=importlib.util.spec_from_file_location('scail_server',ROOT/'server.py');server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

def test_two_scail_workflows_have_curated_business_schema():
    plus=BY_ID['scail2_plus'];multi=BY_ID['scail2_multi']
    assert plus['rh_workflow_id']=='2096841102812053505'
    assert multi['rh_workflow_id']=='2096840691372924929'
    assert set(plus['rh_media'])=={'reference_image','driving_video'}
    assert set(plus['rh_params'])=={'prompt','width','height','frame_rate','frame_load_cap','skip_first_frames','seed','vae_tiling','long_video_low_memory'}
    assert set(multi['rh_media'])=={'reference_image','driving_video'}
    assert set(multi['rh_params'])=={'prompt','mask_prompt','long_edge','frame_rate','frame_load_cap','skip_first_frames','people','seed','mode','preserve_reference_background','vae_tiling'}

def test_scail_schema_does_not_expose_missing_editor_branches_or_technical_fields():
    forbidden_keys={'multi_image','pose_detection','skeleton_action','background_image','black_background','model','lora','steps','cfg','scheduler','device','blocks_to_swap'}
    forbidden_fields={'model','model_name','lora','lora_0','steps','cfg','scheduler','render_device','blocks_to_swap','device','load_device'}
    for wid in ('scail2_plus','scail2_multi'):
        w=BY_ID[wid]
        assert not forbidden_keys.intersection(w['rh_media'])
        assert not forbidden_keys.intersection(w['rh_params'])
        direct={m.get('field') for m in w['rh_params'].values() if m.get('field')}
        assert not forbidden_fields.intersection(direct)

def test_video_controls_preserve_native_types_and_expand_trusted_overrides():
    plus=BY_ID['scail2_plus'];media={'reference_image':'api/ref.png','driving_video':'api/motion.mp4'}
    trusted_media,params=server.normalize_rh_workflow_inputs(plus,media,{'long_video_low_memory':True,'vae_tiling':False,'frame_load_cap':0,'skip_first_frames':0})
    nodes=server.rh_build_video_node_info({'media':trusted_media,'params':params,'prompt':params['prompt'],'negative_prompt':''},plus)
    by={(n['nodeId'],n['fieldName']):n['fieldValue'] for n in nodes}
    assert by[('197','render_device')]=='cpu'
    assert by[('43','enable_vae_tiling')] is False
    assert by[('110','value')]==0 and by[('111','value')]==0
    assert isinstance(by[('45','seed')],int)

def test_multi_mode_and_background_are_real_booleans():
    w=BY_ID['scail2_multi'];media={'reference_image':'api/ref.png','driving_video':'api/motion.mp4'}
    _,params=server.normalize_rh_workflow_inputs(w,media,{'mode':'character_replace','preserve_reference_background':False,'vae_tiling':True})
    nodes=server.rh_build_video_node_info({'media':media,'params':params,'prompt':params['prompt'],'negative_prompt':''},w)
    by={(n['nodeId'],n['fieldName']):n['fieldValue'] for n in nodes}
    assert by[('423','value')] is True
    assert by[('432','value')] is False
    assert by[('267','enable_vae_tiling')] is True

def test_invalid_video_enum_and_range_are_rejected():
    w=BY_ID['scail2_multi'];media={'reference_image':'api/ref.png','driving_video':'api/motion.mp4'}
    with pytest.raises(ValueError):server.normalize_rh_workflow_inputs(w,media,{'mode':'attacker'})
    with pytest.raises(ValueError):server.normalize_rh_workflow_inputs(w,media,{'people':99})
