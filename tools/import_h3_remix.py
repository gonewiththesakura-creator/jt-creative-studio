"""Compile the inspected H3 Remix graph into the private workflow catalog."""
import copy
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RUN_ID = '2111635037301452801'
EDITOR_ID = '2111655708270211074'


def install(config, original, editor_sha):
    graph = copy.deepcopy(original)
    for node, kind in [('295','FeiHouEasyH3RH'),('341','FeiHouEasyH3RHRemixLoader'),
                       ('340','FeiHouEasyH3RHFaceRefine'),('349','VHS_VideoCombine'),
                       ('350','VHS_VideoCombine'),('351','VHS_VideoCombine')]:
        assert graph[node]['class_type'] == kind
    for node in graph.values():
        node.pop('_meta', None)
        if node['class_type'] == 'VHS_VideoCombine':
            node['inputs']['save_metadata'] = False
    setup = graph['295']['inputs']
    setup.update(embedded_media_json='[]', prompt='', prompt_optimizer_enabled=False, prompt_optimizer_api_key='',
                 prompt_optimizer_api_url='', prompt_optimizer_api_format='auto',
                 reference_mention_mode='index')
    # Model/resource names and executable wiring remain server-only.
    params = {}
    def p(key, label, type, default, node=None, field=None, group='基本设置', **extra):
        value = dict(label=label, type=type, default=default, group=group, **extra)
        if node is not None:
            value.update(node=str(node), field=field or key)
        params[key] = value
    def toggle(key, label, default, **extra):
        p(key, label, 'boolean', default, **extra)
    def enum(key, label, default, choices, **extra):
        p(key, label, 'select', default, options=[dict(value=v,label=n) if isinstance(v,str) else v
          for v,n in (choices.items() if isinstance(choices,dict) else [(v,v) for v in choices])], **extra)
    p('prompt','提示词','text','保持参考人物的身份、外貌与场景一致，按文字要求生成自然流畅的视频。',295,
      required=True, max_length=10000, description='按类型编号引用素材：<Picture 1>、<Video 1>、<Audio 1>。')
    enum('mode','生成模式','reference',{'reference':'参考生视频','image':'图生视频 / 首尾帧'},node=295)
    p('duration','时长（秒）','float',5,295,'seconds',min=.2,max=30,step=.1)
    enum('audio_duration_auto','自动对齐时长','off',{'off':'关闭 · 手动时长','video':'参考视频 1','audio':'参考音频 1'},node=295)
    resolutions=['360P','416P','480P','540P','640P','720P','768P','832P','928P','1024P','1080P','custom']
    enum('resolution','一采分辨率','540P',resolutions,node=295)
    enum('aspect_ratio','画面比例','9:16',['1:1','2:3','3:2','3:4','4:3','9:16','16:9','21:9'],node=295)
    toggle('second_pass','开启二次采样',True,description='再次采样提升细节；关闭后跳过整个二采分支。')
    toggle('face_refine','开启人脸精修',True,description='可独立于二采启用；增加生成耗时。')
    toggle('original_audio','使用参考原声音频',False,node=297,field='switch',description='关闭则使用生成音频；开启需要参考视频或参考音频。')
    toggle('advanced','启用高级设置',True,node=295,group='一采与高级设置')
    enum('keyframe_role','首尾帧顺序','first',{'first':'图 1 为首帧，图 2 为尾帧','last':'图 1 为尾帧，图 2 为首帧'},node=295,group='一采与高级设置')
    enum('ref_image_size','参考图处理尺寸','640',['match','480','544','640','736','768','832','928','1024','1088'],node=295,group='一采与高级设置')
    p('fps','帧率','float',24,295,min=1,max=120,step=1,group='一采与高级设置')
    for key,label,default in [('force_offload','采样后释放显存',True),('low_vram_streamed_attention','低显存流式注意力',False),('reference_text_only','只用多模态文字参考',False)]:
        toggle(key,label,default,node=295,group='一采与高级设置',depends_on=dict(key='advanced',value=True))
    for prefix,node,group in [('',295,'一采与高级设置'),('second_',321,'二次采样设置')]:
        if prefix:
            enum(prefix+'resolution','二采分辨率','720P',resolutions,node=node,field='resolution',group=group)
        for dimension,label,value in [('width','自定义宽度',1344),('height','自定义高度',768)]:
            p(prefix+dimension,label,'int',value,node,dimension,group=group,min=32,max=4096,step=32,
              depends_on=dict(key=prefix+'resolution',value='custom'))
    for prefix,noise,scheduler,sigma,steps,group in [('',276,251,326,8,'一采与高级设置'),('second_',317,320,318,4,'二次采样设置')]:
        p(prefix+'seed','随机种子（-1 为随机）','int',-1,noise,'seed',group=group,min=-1,max=2**53-1)
        p(prefix+'steps','采样步数','int',steps,scheduler,'steps',group=group,min=1,max=60)
        p(prefix+'denoise','去噪强度','float',1,scheduler,'denoise',group=group,min=.01,max=1,step=.01)
        p(prefix+'video_shift','视频偏移','float',12,sigma,'shift_video',group=group,min=0,max=30,step=.1)
        p(prefix+'audio_shift','音频偏移','float',3,sigma,'shift_audio',group=group,min=0,max=30,step=.1)
    toggle('sparse_attention','稀疏注意力加速',True,group='一采与高级设置')
    p('second_prompt','二采提示词','text',graph['312']['inputs']['text'],312,'text',group='二次采样设置',max_length=10000,allow_blank=True)
    p('second_cfg','二采提示词引导','float',1,307,'cfg',group='二次采样设置',min=0,max=10,step=.1)
    for slot,label,default in [(1,'一采 Turbo',1),(2,'二采 LMS',.75),(3,'二采 Turbo',.8)]:
        group='LoRA 设置'
        toggle(f'lora_{slot}_enabled',label+' · 启用',True,group=group)
        p(f'lora_{slot}_strength',label+' · 权重','float',default,group=group,min=-2,max=2,step=.05)
        toggle(f'lora_{slot}_bypass',label+' · Bypass 加载',True,group=group,
               description='这是 LoRA 加载方式；要停用请关闭“启用”。')
    for key,label,default in [('advanced','高级精修选项',False),('audio_lock','音频约束（实验性）',False),
                              ('clean_second_model','使用纯净二采模型',True),('force_offload','精修后释放显存',True)]:
        toggle('face_'+key,label,default,node=340,field=key,group='人脸精修设置')
    enum('face_mode','精修人数','单人',['单人','多人'],node=340,group='人脸精修设置')
    enum('face_target','人脸选择','largest_face',{'largest_face':'最大人脸','reference_identity':'按参考图匹配身份'},node=340,field='target',group='人脸精修设置')
    enum('face_canvas','精修画布','768',['512','640','768','1024'],node=340,field='canvas_size',group='人脸精修设置')
    enum('face_chunks','分段帧数','不分段',['不分段','240','192','120','72'],node=340,field='chunk_frames',group='人脸精修设置')
    for key,label,type,default,low,high,step in [('seed','精修种子','int',335463569070439,0,2**53-1,1),
        ('steps','精修步数','int',8,1,60,1),('denoise','精修去噪','float',.25,.01,1,.01),
        ('confidence','人脸检测置信度','float',.35,.05,1,.05),('crop_factor','裁剪范围','float',2.5,1.2,5,.1),
        ('max_faces','最多精修人数','int',2,2,8,1)]:
        p('face_'+key,label,type,default,340,key,group='人脸精修设置',min=low,max=high,step=step)
    p('face_prompt','精修提示词','text',graph['340']['inputs']['prompt'],340,'prompt',group='人脸精修设置',max_length=10000)
    toggle('use_face_reference','使用独立人脸参考图',False,group='人脸精修设置')
    for key,label in [('save_first','保留一采结果'),('save_second','保留二采结果'),('save_face','保留精修结果')]:
        toggle(key,label,True,group='输出设置')
    toggle('pingpong','往返播放输出',False,group='输出设置')
    p('crf','视频压缩质量（越小越清晰）','int',19,group='输出设置',min=0,max=35)
    media={}
    for kind,count in [('image',9),('video',3),('audio',3)]:
        for index in range(1,count+1):
            key=('reference_image' if kind=='image' else 'source_video' if kind=='video' else 'reference_audio') + ('' if index==1 else '_'+str(index))
            group='参考素材' if index==1 and kind!='audio' else '更多参考素材'
            media[key]=dict(node='295',field='embedded_media_json',type=kind,label={'image':'参考图','video':'参考视频','audio':'参考音频'}[kind]+' '+str(index),group=group,required=False)
            if kind != 'image' or index > 2:
                media[key]['depends_on']=dict(key='mode',value='reference')
            if kind!='image':
                p(key+'_start','参考'+('视频' if kind=='video' else '音频')+str(index)+' · 截取起点（秒）','float',0,group='参考素材截取',min=0,max=86400,step=.1)
                p(key+'_end','参考'+('视频' if kind=='video' else '音频')+str(index)+' · 截取终点（0 为末尾）','float',0,group='参考素材截取',min=0,max=86400,step=.1)
    media['face_reference']=dict(node='339',field='image',type='image',label='独立人脸参考图',group='独立人脸参考',required=True,depends_on=dict(key='use_face_reference',value=True))
    item=dict(id='h3_remix_full',name='MiniMax H3 Remix · 全功能双采样',kind='video',backend='runninghub',section='MiniMax H3',
        desc='支持参考生视频与首尾帧、二次采样、独立人脸精修和原声切换。参考模式至少上传图片或视频；首尾帧模式仅使用前两张参考图。',
        rh_workflow_id=RUN_ID,source_editor_workflow_id=EDITOR_ID,source_editor_json_sha256=editor_sha,
        source_api_json_sha256=hashlib.sha256(json.dumps(original,ensure_ascii=False,indent=2).encode()).hexdigest(),
        rh_graph=graph,rh_media=media,rh_params=params)
    config['workflows']=[w for w in config['workflows'] if w['id']!=item['id']]+[item]
    return item


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--editor',required=True);args=parser.parse_args()
    path=BASE/'config.json';config=json.loads(path.read_text(encoding='utf-8'))
    graph=json.loads((BASE/'audit/image-edit-workflows-20261017'/f'{RUN_ID}-api.json').read_text(encoding='utf-8'))
    item=install(config,graph,hashlib.sha256(Path(args.editor).read_bytes()).hexdigest())
    path.write_text(json.dumps(config,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({'workflow':item['id'],'controls':len(item['rh_params']),'media':len(item['rh_media'])}))
