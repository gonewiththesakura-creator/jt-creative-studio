from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "sources" / "video_business.js").read_text(encoding="utf8")
REALISM = (ROOT / "build_realism_workbench.py").read_text(encoding="utf8")


def test_video_upload_sends_trusted_scope_and_stores_only_opaque_token():
    assert "workflow:workflow.id,input_key:key,filename:file.name" in VIDEO
    assert "state.tokens[key]=r.uploadToken" in VIDEO
    assert "mediaFiles[key]=r.fileName" not in VIDEO


def test_realism_and_ai_app_uploads_send_scope_and_store_only_opaque_token():
    assert "workflow:workflow.id,input_key:key,filename:file.name,data" in REALISM
    assert "state.media[key]=result.uploadToken" in REALISM
    assert "state.media[key]=result.fileName" not in REALISM


def test_applying_history_never_reuses_expired_or_private_provider_media():
    assert "stateByWorkflow.set(workflow.id,{params,media:{},mediaNames:" in REALISM
    assert "JSON.parse(JSON.stringify(snapshot.media||{}))" not in REALISM
    assert "请重新上传" in REALISM


def test_generated_pages_never_reference_provider_filename_response():
    for relative in ("static/realism.html", "static/video.html"):
        page = (ROOT / relative).read_text(encoding="utf8")
        assert "result.fileName" not in page
        assert "r.fileName" not in page
        assert "uploadToken" in page


def test_video_concurrency_matches_the_live_personal_api_limit():
    server = (ROOT / "server.py").read_text(encoding="utf8")
    assert "VIDEO_MAX_CONCURRENT = 2" in server
    assert "最多2个并发" in VIDEO
    assert "最多3个并发" not in VIDEO
