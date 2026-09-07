import json
from pathlib import Path

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
CONFIG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
BY_ID={w['id']:w for w in CONFIG['workflows']}

EXPECTED={
 'realcomic':({'source_image'},{'requirements'}),
 'realism_krea2':({'image'},{'instruction','seed','input_long_edge','output_resolution'}),
 'realism_2511':({'image'},{'instruction','seed','input_long_edge'}),
 'realism_multisample':({'image'},{'instruction','seed','input_long_edge','batch'}),
 'realism_qwen_zi':({'image'},{'instruction','negative','seed','input_long_edge','output_resolution'}),
 'realism_4k_text':(set(),{'prompt','seed','resolution_preset','use_custom_size','width','height','batch','stage1_lora','stage2_lora'}),
 'realism_3in1':({'image'},{'instruction','seed','input_long_edge','local_detail_lora'}),
 'realism_zi_flowmatch':({'image'},{'instruction','seed','lora_stack'}),
}

def test_compact_business_schema_only():
 for wid,(media,params) in EXPECTED.items():
  w=BY_ID[wid]
  assert set(w.get('rh_media',{}))==media,(wid,set(w.get('rh_media',{})))
  assert set(w.get('rh_params',{}))==params,(wid,set(w.get('rh_params',{})))
  assert all(p.get('group') in {'common','advanced'} for p in w.get('rh_params',{}).values())

def test_3in1_exposes_real_branch_state_without_fake_switches():
 w=BY_ID['realism_3in1']
 assert w['subworkflows']==[
  {'id':'anime_to_real','label':'漫画转真人','available':True},
  {'id':'image_edit','label':'图像编辑','available':False,'reason':'需要单独的RunningHub运行ID'},
  {'id':'local_wardrobe','label':'局部换装','available':False,'reason':'需要单独的RunningHub运行ID'},
 ]
 assert w['fixed_features']==['Z-Image质感增强','面部修复','SeedVR2高清放大']
 adult=w['rh_params']['local_detail_lora']
 assert adult['type']=='boolean' and adult['default'] is True and '仅控制一组' in adult['label']
 assert adult['trusted_overrides']['true']==[
  {'node':'1304','field':'strength_model','value':0.5},
  {'node':'1399','field':'prompt','value':'shaved pussy\n'},
 ]
 assert adult['trusted_overrides']['false']==[
  {'node':'1304','field':'strength_model','value':0.0},
  {'node':'1399','field':'prompt','value':''},
 ]

def test_compact_schema_hides_technical_controls():
 forbidden={'steps','cfg','sampler_name','scheduler','threshold','device','offload_device','keep_model_loaded','enable_debug'}
 for wid in EXPECTED:
  assert not forbidden.intersection(p['field'] for p in BY_ID[wid].get('rh_params',{}).values() if 'field' in p)

def test_public_schema_hides_node_wiring_and_trusted_overrides():
 import importlib.util
 spec=importlib.util.spec_from_file_location('compact_server',ROOT/'server.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 public=mod.public_workflow(BY_ID['realism_3in1'])
 for mapping in list(public['rh_media'].values())+list(public['rh_params'].values()):
  assert not {'node','field','node_type','trusted_overrides'}.intersection(mapping)

def test_3in1_adult_switch_expands_only_trusted_server_overrides():
 import importlib.util
 spec=importlib.util.spec_from_file_location('compact_server_runtime',ROOT/'server.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 workflow=BY_ID['realism_3in1']
 base_media={key:'api/input.png' for key in workflow['rh_media']}
 _,off=mod.normalize_rh_workflow_inputs(workflow,base_media,{'local_detail_lora':False})
 nodes=mod.rh_build_generic_node_info({'media':base_media,'params':off},workflow)
 assert [n for n in nodes if n['nodeId'] in {'1304','1399'}]==[
  {'nodeId':'1304','fieldName':'strength_model','fieldValue':0.0},
  {'nodeId':'1399','fieldName':'prompt','fieldValue':''},
 ]

def test_custom_dimensions_depend_on_the_native_toggle():
 workflow=BY_ID['realism_4k_text']
 for key in ('width','height'):
  assert workflow['rh_params'][key]['depends_on']=={'key':'use_custom_size','value':True}

def test_public_control_keys_never_expose_node_ids():
 for wid in EXPECTED:
  keys=set(BY_ID[wid].get('rh_media',{}))|set(BY_ID[wid].get('rh_params',{}))
  assert all(not key.startswith('n') or not key[1:2].isdigit() for key in keys),(wid,keys)
