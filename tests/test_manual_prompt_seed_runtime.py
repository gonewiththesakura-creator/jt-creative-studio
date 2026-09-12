import importlib.util,json,tempfile
from pathlib import Path
P = Path(__file__).resolve().parents[1] / 'server.py'
spec=importlib.util.spec_from_file_location('panel_server_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def fields(rows):return {(x['nodeId'],x['fieldName']):x['fieldValue'] for x in rows}
base={"workflow":"anima02","prompt":"jt_style1_v1, portrait, closed book","negative_prompt":"bad hands, text","trigger":"jt_style1_v1","width":768,"height":1024,"batch":4,"hd":1,"seed":123456789,"loras":{"LORA1":"01_style1_step900.safetensors","LORA2":"01_style1_step900.safetensors"},"lora_strengths":{"LORA1":0.7,"LORA2":0.6}}
f=fields(m.rh_build_node_info(base))
assert f[('4','text')].startswith('jt_style1_v1, ')
assert f[('4','text')].lower().count('jt_style1_v1')==1
assert f[('5','text')]=='bad hands, text'
assert f[('6','batch_size')]==4
assert f[('10','seed')]==123456789
assert f[('20','index')]==1
assert f[('7','lora_name')]=='01_style1_step900.safetensors' and f[('8','lora_name')]=='01_style1_step900.safetensors'
# Changing only seed must change exactly the seed node value.
g=dict(base);g['seed']=987654321;g=fields(m.rh_build_node_info(g));diff={k:(f.get(k),g.get(k)) for k in set(f)|set(g) if f.get(k)!=g.get(k)}
assert diff=={('10','seed'):(123456789,987654321)},diff
# Retired staged values are no longer dispatched by run_job; ordinary payloads retain batch and seed.
source=P.read_text(encoding='utf8')
assert 'rh_run_sketch_sequence(job, jobdir, w)' not in source
assert 'local_run_sketch_sequence(job, jobdir, w)' not in source
assert 'sequence_mode = "off"' in source
print('REQUEST_CONSTRUCTION_OK ordinary_batch=4 one_task fixed_seed staged_retired')
