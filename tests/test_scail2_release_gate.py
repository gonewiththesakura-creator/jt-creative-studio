import importlib.util,json
from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SCRIPT=ROOT/'tools/deploy_realism_release.py';spec=importlib.util.spec_from_file_location('deploy_scail',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
config=json.loads((ROOT/'config.json').read_text(encoding='utf8'))
def test_scail_release_targets_are_gated():
 assert m.SCAIL_VIDEO_TARGETS=={'scail2_plus':'2096841102812053505','scail2_multi':'2096840691372924929'}
 result=m.validate_scail_video_config(config)
 assert result==[]
 assert m.validate_scail_e2e_manifest()==[]
def test_scail_release_rejects_missing_or_unsafe_schema():
 bad=json.loads(json.dumps(config));w=next(x for x in bad['workflows'] if x['id']=='scail2_plus');w['rh_params']['device']={'node':'197','field':'render_device','type':'select','options':['gpu','cpu']}
 assert m.validate_scail_video_config(bad)
 bad['workflows']=[x for x in bad['workflows'] if x['id']!='scail2_multi']
 errors=m.validate_scail_video_config(bad);assert any('scail2_multi' in x for x in errors)
