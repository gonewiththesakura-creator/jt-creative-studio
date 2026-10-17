"""Reuse the video workbench's maintained task interactions on image editing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def image_edit_task_runtime():
    source = (ROOT / 'sources/video_business.js').read_text(encoding='utf-8')
    start = source.index('function safeMediaUrl(')
    submit = source.index('async function generate(){')
    library = source.index('let historyVersion=0;')
    end = source.index("window.addEventListener('pagehide'")
    code = source[start:submit] + source[library:end]
    for old, new in (
        ('/api/video-generate', '/api/image-edit-generate'),
        ('/api/video-queue', '/api/image-edit-queue'),
        ('/api/video-clear', '/api/image-edit-clear'),
        ("scope:'video'", "scope:'realism'"),
        ("f.style_id==='video'||String(f.favorite_media_type||'').startsWith('video/')",
         "f.style_id==='realism'||['realism','realcomic'].includes(f.selection_snapshot?.source_page)"),
        ('WFS', 'workflows'), ('videoEmpty', 'previewEmpty'), ('genStatus', 'generateStatus'),
        ('原视频首帧', '参考图片'), ('原视频', '参考图片'),
        ('暂无首帧', '暂无缩略图'), ('视频任务', '图片编辑任务'),
        ('视频历史', '图片编辑历史'), ('视频收藏', '图片编辑收藏'),
        ('视频提示词与 LoRA 详情', '图片提示词与参数详情'),
        ('播放结果', '查看结果'), ('播放器列表', '结果列表'),
    ):
        code = code.replace(old, new)
    return code.replace('d.append(promptNode,holder,configurationDetails(f));',
        "const apply=document.createElement('button');apply.type='button';apply.className='dl apply';apply.textContent='套用参数';apply.onclick=()=>applySnapshot(f.selection_snapshot);d.append(promptNode,holder,configurationDetails(f),apply);")
