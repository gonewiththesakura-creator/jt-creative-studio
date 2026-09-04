import importlib.util,json,tempfile
from pathlib import Path
P=Path(r"D:/LAN-Share/lora/_work/comfy_panel/server.py")
spec=importlib.util.spec_from_file_location('hanmanga_runtime',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
preset=m.STYLE_PRESETS['hanmanga']
assert preset=={
 'trigger':'jt_liulistyle_v1',
 'LORA1':'08_liuli_style_v1_step600.safetensors',
 'LORA2':'08_liuli_style_v1_step600.safetensors',
 'strengths':{'LORA1':0.7,'LORA2':0.6},
}
job={'id':'han-runtime','workflow':'anima02','prompt':'jt_liulistyle_v1, adult woman in hanfu','negative_prompt':'text, watermark','trigger':preset['trigger'],'width':512,'height':768,'batch':1,'hd':0,'seed':24681357,'loras':{'LORA1':preset['LORA1'],'LORA2':preset['LORA2']},'lora_strengths':preset['strengths'],'prompt_ids':[],'progress_pct':0}
api=m.build_api('anima02',job['prompt'],512,768,1,0,24681357,{k:m.local_lora_name(v) for k,v in job['loras'].items()},job['trigger'],False,job['negative_prompt'])
assert api['70']['inputs']['lora_name']=='Anima_JT\\08_liuli_style_v1_step600.safetensors'
assert api['71']['inputs']['lora_name']=='Anima_JT\\08_liuli_style_v1_step600.safetensors'
assert api['4']['inputs']['text'].lower().count('jt_liulistyle_v1')==1
assert api['5']['inputs']['text']=='text, watermark'
cloud=m.rh_build_node_info(job);fields={(x['nodeId'],x['fieldName']):x['fieldValue'] for x in cloud}
assert fields[('7','lora_name')]=='08_liuli_style_v1_step600.safetensors'
assert fields[('8','lora_name')]=='08_liuli_style_v1_step600.safetensors'
assert fields[('7','strength_model')]==0.7 and fields[('8','strength_model')]==0.6
assert fields[('4','text')].lower().count('jt_liulistyle_v1')==1
print('HANMANGA_RUNTIME_OK')
