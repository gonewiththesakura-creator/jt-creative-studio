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

 'realism_zi_flowmatch':({'image'},{'instruction','seed','lora_stack'}),
}

def test_compact_business_schema_only():
 for wid,(media,params) in EXPECTED.items():
  w=BY_ID[wid]
  assert set(w.get('rh_media',{}))==media,(wid,set(w.get('rh_media',{})))
  assert set(w.get('rh_params',{}))==params,(wid,set(w.get('rh_params',{})))
  assert all(p.get('group') in {'common','advanced'} for p in w.get('rh_params',{}).values())

def test_compact_schema_hides_technical_controls():
 forbidden={'steps','cfg','sampler_name','scheduler','threshold','device','offload_device','keep_model_loaded','enable_debug'}
 for wid in EXPECTED:
  assert not forbidden.intersection(p['field'] for p in BY_ID[wid].get('rh_params',{}).values() if 'field' in p)

def test_public_schema_hides_node_wiring_and_trusted_overrides():
 import importlib.util
 spec=importlib.util.spec_from_file_location('compact_server',ROOT/'server.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 public=mod.public_workflow(BY_ID['realism_zi_flowmatch'])
 for mapping in list(public['rh_media'].values())+list(public['rh_params'].values()):
  assert not {'node','field','node_type','trusted_overrides'}.intersection(mapping)



def test_custom_dimensions_depend_on_the_native_toggle():
 workflow=BY_ID['realism_4k_text']
 for key in ('width','height'):
  assert workflow['rh_params'][key]['depends_on']=={'key':'use_custom_size','value':True}

def test_public_control_keys_never_expose_node_ids():
 for wid in EXPECTED:
  keys=set(BY_ID[wid].get('rh_media',{}))|set(BY_ID[wid].get('rh_params',{}))
  assert all(not key.startswith('n') or not key[1:2].isdigit() for key in keys),(wid,keys)
