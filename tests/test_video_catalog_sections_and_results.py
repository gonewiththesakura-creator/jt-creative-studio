from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "sources" / "video_business.js").read_text(encoding="utf8")
BUILDER = (ROOT / "build_video_workbench.py").read_text(encoding="utf8")
PAGE = (ROOT / "static" / "video.html").read_text(encoding="utf8")
SPEC = importlib.util.spec_from_file_location("catalog_server", ROOT / "server.py")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def test_video_catalog_is_grouped_by_server_supplied_section():
    for text in (SOURCE, PAGE):
        assert "workflow-section" in text
        assert "w.section||'其他'" in text
        assert "Object.entries(grouped)" in text
    assert '"section": w.get("section", "其他")' in (ROOT / "server.py").read_text(encoding="utf8")


def test_non_previewable_video_results_render_as_download_only_files():
    for text in (SOURCE, PAGE):
        assert "resultMediaKind" in text
        assert "file-result" in text
        assert "下载结果文件" in text
        assert "application/zip" in text
        assert "document.createElement(kind==='video'?'video':'img')" in text
        assert "if(kind==='file')" in text


def test_video_builder_owns_group_and_generic_file_styles():
    assert ".workflow-section" in BUILDER
    assert ".file-result" in BUILDER


def test_runninghub_result_type_is_preserved_without_fake_image_preview():
    results = [
        {"url": "https://cdn.example.test/result", "fileType": "application/zip"},
        {"url": "https://cdn.example.test/frame", "fileType": "image/png"},
        {"url": "https://cdn.example.test/movie", "outputType": "mp4"},
        {"url": "https://cdn.example.test/archive", "outputType": "zip"},
        {"url": "https://cdn.example.test/another-frame", "outputType": "png"},
        {"url": "https://cdn.example.test/output/压缩文件_00001.zip?name=结果", "outputType": "zip"},
    ]
    converted = SERVER._rh_results_to_images(results, "task")
    assert converted[0]["file_type"] == "application/zip"
    assert converted[0]["preview_url"] == converted[0]["url"]
    assert converted[1]["file_type"] == "image/png"
    assert "imageMogr2/thumbnail/640x640" in converted[1]["preview_url"]
    assert converted[2]["file_type"] == "mp4"
    assert converted[2]["preview_url"] == converted[2]["url"]
    assert converted[3]["file_type"] == "zip"
    assert converted[3]["preview_url"] == converted[3]["url"]
    assert converted[4]["file_type"] == "png"
    assert "imageMogr2/thumbnail/640x640" in converted[4]["preview_url"]
    assert converted[5]["url"].isascii()
    assert "%E5%8E%8B%E7%BC%A9%E6%96%87%E4%BB%B6" in converted[5]["url"]
    assert "%E7%BB%93%E6%9E%9C" in converted[5]["url"]
    assert converted[5]["file"] == "压缩文件_00001.zip"


def test_both_workbenches_consume_the_normalized_file_type_field():
    realism = (ROOT / "build_realism_workbench.py").read_text(encoding="utf8")
    for text in (SOURCE, PAGE, realism):
        assert "file_type" in text


def test_unicode_url_normalization_preserves_existing_signed_escapes():
    original = "https://cdn.example.test/目录/result%2Fpart.zip?token=a%2Bb%2Fc%26d&name=结果"
    normalized, display_name = SERVER._ascii_remote_url(original)
    assert normalized.isascii()
    assert "/%E7%9B%AE%E5%BD%95/" in normalized
    assert "result%2Fpart.zip" in normalized
    assert "token=a%2Bb%2Fc%26d" in normalized
    assert "name=%E7%BB%93%E6%9E%9C" in normalized
    assert display_name == "part.zip"


def test_multi_output_workflows_label_primary_and_comparison_results():
    by_id = {item["id"]: item for item in SERVER.CONFIG["workflows"]}
    expected = {
        "h3_edit_t3": ["编辑后主视频", "原片 / 生成片对比"],
        "h3_edit_remove": ["移除后主视频", "原片 / 生成片对比"],
        "scail2_action_replace": ["动作迁移主视频", "输入 / 参考 / 结果对比"],
    }
    for workflow_id, labels in expected.items():
        workflow = by_id[workflow_id]
        assert workflow["rh_result_labels"] == labels
        converted = SERVER._rh_results_to_images(
            [
                {"url": f"https://cdn.example/{workflow_id}-{idx}.mp4", "outputType": "mp4"}
                for idx in range(len(labels))
            ],
            "task-1",
            result_labels=workflow["rh_result_labels"],
        )
        assert [item["stage_label"] for item in converted] == labels


def test_video_ui_prefers_business_result_label_over_provider_filename():
    source = (ROOT / "sources" / "video_business.js").read_text(encoding="utf8")
    generated = (ROOT / "static" / "video.html").read_text(encoding="utf8")
    assert "stage_label||item.im.file||'结果'" in source
    assert "stage_label||item.im.file||'结果'" in generated
