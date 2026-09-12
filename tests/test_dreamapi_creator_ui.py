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
            'gpt-image-2.5-flare', 'gpt-image-2.5-sunburst', 'gpt-image-2',
            'value="cover"', 'value="contain"', 'API每次生成1张',
            'api_model:apiModel.value', 'api_quality:apiQuality.value',
            'api_fit:apiFit.value', "backend==='api'?1:+genBatch.value",
            "backend==='api'?0:+genHd.value",
        ]:
            assert token in text, (path, token)
        assert 'apiBaseUrl' not in text
        assert 'DREAMAPI_KEY' not in text
        assert 'gpt-5.6-sol' not in text


def test_api_model_quality_options_are_linked_and_seed_is_not_misrepresented():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        assert 'updateApiQualityOptions' in text
        assert 'API结果不受Seed控制' in text
        assert "j.seed_supported===false?'Seed：不适用'" in text
        assert "backendUi(j.generation_backend).label" in text


def test_mobile_creator_keeps_all_three_provider_actions_on_one_row():
    for path in FILES:
        text = path.read_text(encoding="utf8")
        mobile = text.split("@media(max-width:480px)", 1)[1].split("@media(prefers-reduced-motion", 1)[0]
        assert ".generation-actions{grid-template-columns:repeat(3,minmax(0,1fr));" in mobile, path
        assert ".generation-actions{grid-template-columns:1fr 1fr" not in mobile, path


def test_creator_static_config_does_not_publish_lora_filenames():
    path = ROOT / "static" / "index.html"
    text = path.read_text(encoding="utf8")
    assert ".safetensors" not in text, path
    assert '"lora1"' not in text and '"lora2"' not in text, path
