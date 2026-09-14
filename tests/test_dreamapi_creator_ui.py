from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "build_unified_three_styles.py",
    ROOT / "static" / "index.html",
    ROOT / "static" / "promptgen.html",
]


def test_creator_exposes_three_generation_channels_and_three_result_panes():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        assert 'id="genCloudBtn"' in text
        assert 'id="genLocalBtn"' in text
        assert 'id="genApiBtn"' in text
        assert 'id="apiDrawerOpen"' in text
        assert 'id="apiDrawer"' in text
        assert 'id="apiDrawerClose"' in text
        assert "generate('cloud')" in text
        assert "generate('local')" in text
        assert "generate('api')" in text
        assert 'data-result-tab="api"' in text
        assert 'data-result-panel="api"' in text
        assert 'id="genApiStatus"' in text
        assert 'id="genApiResult"' in text
        assert "{cloud:false,local:false,api:false}" in text
        assert "['cloud','local','api'].map(resumeActiveJob)" in text


def test_creator_api_channel_has_only_trusted_image_options():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        for token in [
            'id="apiModel"', 'id="apiQuality"', 'id="apiFit"',
            'name="apiRatio"', 'value="1:1"', 'value="2:3"',
            'value="3:2"', 'value="9:16"', 'value="16:9"',
            'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst', 'gpt-image-2',
            'value="cover"', 'value="contain"', 'API每次生成1张',
            'api_model:apiModel.value', 'api_quality:apiQuality.value',
            'api_fit:apiFit.value', "backend==='api'?1:+genBatch.value",
            "backend==='api'?0:+genHd.value",
            "candidate.api_ratio=selectedApiRatio()",
            'API专属生图', '使用当前提示词',
            '上游可能覆盖质量',
        ]:
            assert token in text, (path, token)
        assert 'id="apiWidth"' not in text
        assert 'id="apiHeight"' not in text
        assert 'value="custom"' not in text.split('id="apiDrawer"', 1)[1]
        assert 'apiBaseUrl' not in text
        assert 'DREAMAPI_KEY' not in text
        assert 'gpt-5.6-sol' not in text
        assert '<option value="gpt-image-2.5-flare" selected>' in text
        assert text.index('value="gpt-image-2.5-flare"') < text.index('value="gpt-image-2"')


def test_api_model_quality_options_are_linked_and_seed_is_not_misrepresented():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        assert 'updateApiQualityOptions' in text
        assert 'API结果不受Seed控制' in text
        assert "j.seed_supported===false?'Seed：不适用'" in text
        assert "backendUi(j.generation_backend).label" in text


def test_api_settings_are_captured_and_restored_with_valid_defaults():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        for token in (
            "function defaultApiSettings()",
            "function normalizeApiSettings(snapshot={})",
            "models.includes(snapshot.api_model)&&API_QUALITIES[snapshot.api_model]",
            "qualities.includes(snapshot.api_quality)",
            "fits.includes(snapshot.api_fit)",
            "ratios.includes(snapshot.api_ratio)",
            "api_model:apiModel.value",
            "api_quality:apiQuality.value",
            "api_fit:apiFit.value",
            "api_ratio:selectedApiRatio()",
            "const api=normalizeApiSettings(snapshot)",
            "apiModel.value=api.api_model",
            "updateApiQualityOptions(api.api_quality)",
            "apiFit.value=api.api_fit",
            "input.value===api.api_ratio",
        ):
            assert token in text, (path, token)


def test_api_gallery_displays_requested_and_actual_upstream_settings():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        for token in (
            "j.api_upstream_model",
            "j.api_upstream_quality",
            "j.api_upstream_size",
            "请求质量",
            "上游实际",
        ):
            assert token in text, (path, token)


def test_main_creator_keeps_cloud_local_on_one_row_and_api_separate():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        mobile = text.split("@media(max-width:480px)", 1)[1].split("@media(prefers-reduced-motion", 1)[0]
        assert ".generation-actions{grid-template-columns:repeat(2,minmax(0,1fr));" in mobile, path
        assert ".generation-actions{grid-template-columns:1fr 1fr" not in mobile, path
        assert 'id="apiDrawerOpen"' in text


def test_creator_static_config_does_not_publish_lora_filenames():
    path = ROOT / "static" / "index.html"
    text = path.read_text(encoding="utf8")
    assert ".safetensors" not in text, path
    assert '"lora1"' not in text and '"lora2"' not in text, path


def test_creator_has_no_numeric_progress_label_markup_or_css():
    for page in FILES:
        assert "liquid-percent" not in page.read_text(encoding="utf8"), page


def test_api_generation_has_visible_stage_progress_without_fake_percentages():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        for token in (
            "function installApiProgress()",
            'data-api-progress-stage',
            'data-api-progress-elapsed',
            'role="progressbar"',
            "function describeApiProgress(job,override={})",
            "图像模型生成中 · 阶段 2/4",
            "API_PROCESSING_RESULT",
            "正在解析生成结果 · 阶段 3/4",
            "API_FITTING_RESULT",
            "正在适配目标画布 · 阶段 3/4",
            "图片已生成 · 阶段 4/4",
            "上游不提供实时百分比",
            "仅显示已确认阶段",
            "function formatApiElapsed(startedAt)",
            "function creatorPhaseText(job)",
            "status.textContent=creatorPhaseText(next)",
            "setInterval(()=>renderApiProgress",
        ):
            assert token in text, (path, token)
        assert "estimatedProgress" not in text, path
        assert "预计剩余" not in text, path


def test_api_progress_covers_terminal_retry_and_refresh_recovery_states():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        for token in (
            "function isApiCancelled(job)",
            "function isTerminalJob(job)",
            "function startApiProgress(job,override={})",
            "function finishApiProgress(job,override={})",
            "function pauseApiProgress(message)",
            "生成失败",
            "任务已取消",
            "正在确认任务状态",
            "不会重复提交",
            "刷新页面会继续恢复",
            "installApiProgress();",
        ):
            assert token in text, (path, token)
