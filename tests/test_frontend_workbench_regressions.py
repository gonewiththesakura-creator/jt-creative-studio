from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_SOURCE = (ROOT / "sources" / "video_business.js").read_text(encoding="utf8")
VIDEO_BUILDER = (ROOT / "build_video_workbench.py").read_text(encoding="utf8")
REALISM_BUILDER = (ROOT / "build_realism_workbench.py").read_text(encoding="utf8")


def test_hidden_galleries_do_not_participate_in_layout():
    for source in (VIDEO_BUILDER, REALISM_BUILDER):
        assert "[hidden]{display:none!important}" in source
        assert 'id="mediaGallery" hidden' in source
    assert ".preview-empty{position:relative" in VIDEO_BUILDER
    assert ".preview-empty{position:relative" in REALISM_BUILDER


def test_video_upload_is_bound_to_originating_workflow():
    assert "mediaStateByWorkflow=new Map()" in VIDEO_SOURCE
    assert "const f=document.getElementById('wfForm'),workflow=cur,version=renderVersion" in VIDEO_SOURCE
    assert "workflow:workflow.id,input_key:key" in VIDEO_SOURCE
    assert "state.tokens[key]=r.uploadToken" in VIDEO_SOURCE
    assert "workflow:cur.id,input_key:key" not in VIDEO_SOURCE
    assert "mediaFiles" not in VIDEO_SOURCE


def test_upload_surfaces_support_drag_drop_and_keyboard():
    for source in (VIDEO_SOURCE, REALISM_BUILDER):
        assert "tabIndex=0" in source
        assert "setAttribute('role','button')" in source
        assert "event.key==='Enter'||event.key===' '" in source
        assert "ondragover" in source
        assert "ondrop" in source
        assert "dataTransfer?.files?.[0]" in source


def test_extensionless_provider_media_types_are_previewable():
    for bare_type in ("'mp4'", "'webm'", "'png'", "'jpeg'", "'webp'"):
        assert bare_type in VIDEO_SOURCE
    assert "['video','mp4','mov','webm','avi','mkv'].includes(type)" in VIDEO_SOURCE
    assert "['image','png','jpg','jpeg','webp','gif','avif'].includes(type)" in VIDEO_SOURCE


def test_video_polling_exposes_recovery_and_terminal_failure_states():
    assert "queueFetching" in VIDEO_SOURCE
    assert "队列连接中断，自动重试" in VIDEO_SOURCE
    assert "setTimeout(refreshVideoQueue" in VIDEO_SOURCE
    assert "document.hidden?15000:4000" in VIDEO_SOURCE
    assert "j.status==='error'" in VIDEO_SOURCE
    # eb3cf6b reworded the held-slot notice when it added active-task reconciliation.
    assert "提交超时，未收到云端任务号；暂占 1 个名额，正在自动核对，不会重复提交" in VIDEO_SOURCE


def test_realism_upload_does_not_drift_after_workflow_switch():
    assert "workflow=current" in REALISM_BUILDER
    assert "path=workflow.kind==='ai_app'" in REALISM_BUILDER
    assert "payload={workflow:workflow.id" in REALISM_BUILDER
    assert "current?.id===workflow.id" in REALISM_BUILDER
