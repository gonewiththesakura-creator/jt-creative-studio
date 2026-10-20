"""Import the inspected provider graph plus disabled branches from the supplied editor export."""
import copy
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
RUN_ID='2111727257252290561'
EDITOR_ID='2112090338620891138'
WORKFLOW_ID='h3_reference_optimized'
API_SHA='5182d336c7bb2d12fe259400f01f43de617d5a2303625149d3ea514716546e83'


def install(config,original,editor,editor_sha):
    assert hashlib.sha256(json.dumps(original,ensure_ascii=False,indent=2).encode()).hexdigest()==API_SHA
    nodes={str(n['id']):n for n in editor['nodes']}
    links={row[0]:row for row in editor['links']}
    setters={n['widgets_values'][0]:n for n in nodes.values() if n['type']=='SetNode'}
    def resolve(link_id,include_disabled=True,seen=None):
        if link_id is None:return None
        seen=set() if seen is None else set(seen)
        assert link_id not in seen, 'Cyclic editor wiring'
        seen.add(link_id)
        _,source,slot,*_=links[link_id];node=nodes[str(source)]
        if node['type']=='GetNode':node=setters[node['widgets_values'][0]]
        if node['type'] in ('SetNode','Reroute'):
            return resolve(node['inputs'][0].get('link'),include_disabled,seen)
        if not include_disabled and node.get('mode')==4:
            if node['type']=='LoraLoaderModelOnly':return resolve(node['inputs'][0]['link'],False,seen)
            return None
        return [str(node['id']),slot]
    # Compare active executable edges, not editor-only routing or sample prompts.
    for key,row in original.items():
        assert nodes[key]['type']==row['class_type']
        for field in nodes[key].get('inputs',[]):
            if field.get('link') is None:continue
            expected=resolve(field['link'],False)
            if expected is not None:assert row['inputs'].get(field['name'])==expected,(key,field['name'])
    graph=copy.deepcopy(original)
    for row in graph.values():row.pop('_meta',None)
    graph={key:row for key,row in graph.items() if row['class_type']!='忽略多组孤海'}
    # These are real dormant nodes from the supplied export, not invented branches.
    scalar_fields={
        'LoraLoaderModelOnly':['lora_name','strength_model'],
        'MinimaxH3LatentUpscaler3D':['model_name','mode','mode.scale','align','device','precision','enable_chunking'],
    }
    for key in ('139','140','142','144','115','116','214','322'):
        node=nodes[key];inputs={}
        for field in node['inputs']:
            if field.get('link') is not None:inputs[field['name']]=resolve(field['link'])
        if node['type']=='VHS_VideoCombine':
            values=node['widgets_values']
            inputs.update({name:values[name] for name in ('frame_rate','loop_count','filename_prefix','format','pix_fmt','crf','save_metadata','pingpong','save_output','no_preview','trim_to_audio')})
        else:
            for name,value in zip(scalar_fields.get(node['type'],[]),node.get('widgets_values') or []):
                inputs.setdefault(name,value)
        graph[key]={'class_type':node['type'],'inputs':inputs}
    # Restore the optional middle LoRA edge; disabled loaders are pruned at runtime.
    graph['128']['inputs']['model']=['322',0]
    graph['263']['inputs']['text']=''
    for row in graph.values():
        if row['class_type']=='VHS_VideoCombine':row['inputs'].update(save_metadata=False,filename_prefix='JT_H3')
    params={}
    def p(key,label,kind,default,node=None,field=None,group='基本设置',**extra):
        row=dict(label=label,type=kind,default=default,group=group,**extra)
        if node is not None:row.update(node=str(node),field=field or key)
        params[key]=row
    def toggle(key,label,default,**extra):p(key,label,'boolean',default,**extra)
    def enum(key,label,default,choices,**extra):p(key,label,'select',default,options=[dict(value=k,label=v) for k,v in choices.items()],**extra)
    p('prompt','提示词','text','保持参考人物、服装与场景一致，镜头缓慢推进，人物自然地转身并微笑。',263,'text',required=True,max_length=10000,
      description='用 <Picture 1>、<Video 1>、<Audio 1> 按类型引用已上传素材。')
    p('duration','时长（秒）','float',10,259,'value',min=.2,max=30,step=.1)
    ratios={'1:1 (Square)':'1:1 方形','2:3 (Portrait Photo)':'2:3 竖图','3:2 (Photo)':'3:2 横图',
        '3:4 (Portrait Standard)':'3:4 竖屏','4:3 (Standard)':'4:3 横屏','9:16 (Portrait Widescreen)':'9:16 竖屏',
        '16:9 (Widescreen)':'16:9 横屏','21:9 (Ultrawide)':'21:9 超宽'}
    enum('aspect_ratio','画面比例','16:9 (Widescreen)',ratios,node=252)
    p('megapixels','一采分辨率（MP）','float',.5,252,min=.1,max=4,step=.1,description='0.5 MP 的 16:9 画面约为 960×544；提高分辨率会增加耗时。')
    toggle('second_pass','开启二次采样放大',False,description='放大一采潜空间后继续采样；关闭时仅输出一采。')
    group='一采与高级设置'
    p('seed','随机种子（-1 为随机）','int',-1,256,'noise_seed',group=group,min=-1,max=2**53-1)
    p('total_steps','总采样步数','int',12,261,'steps',group=group,min=1,max=60)
    p('first_steps','一采步数','int',8,289,'step',group=group,min=1,max=60,description='建议一采至少 6 步；开启二采时建议总步数比一采多 4 步。')
    p('denoise','去噪强度','float',1,261,group=group,min=.01,max=1,step=.01)
    enum('ref_image_size','参考图处理尺寸','max',{'match':'匹配输出尺寸 · 更快','max':'高保真参考 · 更慢'},node=265,group=group)
    toggle('memory_attention','节省显存注意力',True,group=group)
    p('second_scale','二采放大倍数','float',1.5,283,'value',group='二次采样设置',min=1,max=4,step=.1)
    toggle('second_chunking','分块放大以节省显存',False,node=140,field='enable_chunking',group='二次采样设置')
    for slot,node,label,enabled in [(1,'53','Turbo LoRA',True),(2,'128','LoRA 2（原配置）',True),(3,'322','动作 LoRA',False)]:
        toggle(f'lora_{slot}_enabled',label+' · 启用',enabled,group='LoRA 设置')
        p(f'lora_{slot}_strength',label+' · 权重','float',round(graph[node]['inputs']['strength_model'],4),node,'strength_model',group='LoRA 设置',min=-2,max=2,step=.05)
    for key,label in [('save_first','保留一采结果'),('save_second','保留二采结果')]:toggle(key,label,True,group='输出设置')
    toggle('pingpong','往返播放输出',False,group='输出设置')
    p('crf','视频压缩质量（越小越清晰）','int',19,group='输出设置',min=0,max=35)
    media={}
    for kind,ids in [('image',('51','49','50','43','19','23','199','200','201')),('video',('27','25','26')),('audio',('48','14','15'))]:
        for index,node_id in enumerate(ids,1):
            node=nodes[node_id];assert node['type']=={'image':'LoadImage','video':'VHS_LoadVideo','audio':'LoadAudio'}[kind]
            field={'image':'image','video':'video','audio':'audio'}[kind]
            inputs={field:''}
            if kind=='video':
                inputs.update({key:node['widgets_values'][key] for key in ('force_rate','force_size','custom_width','custom_height','frame_load_cap','skip_first_frames','select_every_nth','format')})
                inputs['force_rate']=24
            graph[node_id]={'class_type':node['type'],'inputs':inputs}
            key={'image':'reference_image','video':'source_video','audio':'reference_audio'}[kind]+('' if index==1 else '_'+str(index))
            media[key]=dict(node=node_id,field=field,type=kind,label={'image':'参考图','video':'参考视频','audio':'参考音频'}[kind]+' '+str(index),required=False,group='参考素材')
            if kind=='video':
                p(key+'_skip','参考视频 '+str(index)+' · 跳过帧数','int',0,node_id,'skip_first_frames',group='参考素材截取',min=0,max=100000)
                p(key+'_frames','参考视频 '+str(index)+' · 最多读取帧数（0 为全部）','int',0,node_id,'frame_load_cap',group='参考素材截取',min=0,max=720)
                toggle(key+'_audio','参考视频 '+str(index)+' · 使用音轨参考',False,group='参考素材截取')
    references=graph['265']['inputs']
    for key in list(references):
        if key.startswith(('ref_images.','ref_videos.','ref_video_audios.','ref_audios.')):del references[key]
    item=dict(id=WORKFLOW_ID,name='MiniMax H3 · 多参考生视频（优化版）',kind='video',backend='runninghub',section='MiniMax H3',
        desc='支持最多 9 张参考图、3 段视频、3 段音频，混合最多 12 个素材。可选二次采样放大，输出固定为 24 帧/秒。',
        rh_workflow_id=RUN_ID,source_editor_workflow_id=EDITOR_ID,source_editor_json_sha256=editor_sha,
        source_api_json_sha256=API_SHA,rh_graph=graph,rh_media=media,rh_params=params)
    config['workflows']=[w for w in config['workflows'] if w['id']!=WORKFLOW_ID]+[item]
    return item


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--editor',required=True);args=parser.parse_args()
    path=BASE/'config.json';config=json.loads(path.read_text(encoding='utf-8'))
    original=json.loads((BASE/'audit/h3-optimized-20261020'/(RUN_ID+'-api.json')).read_text(encoding='utf-8'))
    raw=Path(args.editor).read_bytes()
    item=install(config,original,json.loads(raw),hashlib.sha256(raw).hexdigest())
    path.write_text(json.dumps(config,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({'workflow':item['id'],'params':len(item['rh_params']),'media':len(item['rh_media'])}))
