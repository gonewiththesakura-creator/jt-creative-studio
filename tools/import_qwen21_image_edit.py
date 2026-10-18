"""Install the verified two-image Qwen 2.1 schema; never submit provider work."""
import hashlib
import copy
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RUN_ID = '2111378115142823938'
EDITOR_ID = '2111383542247743489'


def install(config, graph, editor_sha):
    for node, kind, fields in (
        ('470', 'LoadImage', ('image',)), ('475', 'LoadImage', ('image',)),
        ('484', 'TextEncodeQwenImage21', ('prompt', 'negative_prompt', 'resolution')),
        ('481', 'KSampler', ('seed', 'steps', 'cfg', 'denoise')),
        ('499', 'SaveImage', ('images',)),
    ):
        assert graph[node]['class_type'] == kind
        assert all(field in graph[node]['inputs'] for field in fields)
    assert graph['484']['inputs']['images.image_1'] == ['470', 0]
    assert graph['484']['inputs']['images.image_2'] == ['475', 0]
    single = copy.deepcopy(graph)
    del single['475']
    del single['484']['inputs']['images.image_2']
    single['470']['inputs']['image'] = ''
    single['484']['inputs']['prompt'] = ''
    for node in single.values():
        node.pop('_meta', None)
    def control(node, field, label, type, default, **kwargs):
        return dict(node=node, field=field, label=label, type=type, default=default, **kwargs)
    item = dict(
        id='qwen21_wardrobe', name='Qwen 2.1 · 固定人物换装', kind='rh_workflow', backend='runninghub',
        desc='上传人物图，按提示词编辑服装；可开启图二，使用服装参考图。保持人物身份、姿态与背景。',
        section='换装与图片编辑', rh_workflow_id=RUN_ID, source_editor_workflow_id=EDITOR_ID,
        source_editor_json_sha256=editor_sha,
        source_api_json_sha256=hashlib.sha256(json.dumps(graph, ensure_ascii=False, indent=2).encode()).hexdigest(),
        rh_optional_reference=dict(param='use_clothing', media='clothing', single_image_graph=single),
        rh_media={
            'person': dict(node='470', field='image', label='人物参考图', type='image', required=True),
            'clothing': dict(node='475', field='image', label='图二 · 服装参考图', type='image', required=True,
                depends_on=dict(key='use_clothing', value=True)),
        },
        rh_params={
            'use_clothing': dict(type='boolean', label='使用图二参考图', default=True, client_only=True,
                group='common', description='开启：参考图二的服装；关闭：只用人物图和提示词。'),
            'prompt': control('484', 'prompt', '换装要求', 'text',
                '按文字要求编辑 <image1> 中人物的服装。有图二时参考其服装的颜色、材质与款式，不转移衣架或人台；没有图二时按文字描述修改。保持人物面容、发型、姿态、身形、光线和背景不变。', required=True, max_length=10000),
            'seed': control('481', 'seed', '随机种子', 'int', 0, min=0, max=2**53-1, group='advanced'),
            'resolution': control('484', 'resolution', '输出分辨率', 'select', 1024, vtype='int',
                options=[dict(value=1024, label='1024 · 标准'), dict(value=0, label='原图尺寸 · 更耗显存')], group='common'),
            'steps': control('481', 'steps', '采样步数', 'int', 40, min=1, max=60, group='advanced'),
            'cfg': control('481', 'cfg', '提示词引导', 'float', 1, min=0, max=10, step=0.1, group='advanced'),
        },
        rh_result_labels=['换装结果'],
    )
    config['workflows'] = [w for w in config['workflows'] if w['id'] != item['id']] + [item]
    return item


def main():
    editor = Path(r'C:/Users/admin/Downloads/Qwen2.1_固定人物换装_精简版 (2).json')
    graph = json.loads((BASE / 'audit/image-edit-workflows-20261017' / (RUN_ID + '-api.json')).read_text(encoding='utf-8'))
    path = BASE / 'config.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    item = install(config, graph, hashlib.sha256(editor.read_bytes()).hexdigest())
    path.write_text(json.dumps(config, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'installed': item['id'], 'run_id': RUN_ID, 'editor_id': EDITOR_ID}))


if __name__ == '__main__':
    main()
