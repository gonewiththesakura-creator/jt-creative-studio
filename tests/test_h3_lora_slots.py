import json

import pytest
from test_server_review_regressions import panel
from test_app_shell import browser, serve_page, current


def job(params=None):
    return {'provider_media': {'reference_image': 'api/ref.png', 'source_video': 'api/clip.mp4'},
            'prompt': 'Keep the original scene', 'params': params or {}}


def test_chain_consumers_optional_images_and_audio(panel):
    w = panel.WORKFLOWS['h3_edit_n']
    request = job()
    request['provider_media']['reference_image_2'] = 'api/ref2.png'
    graph = panel.rh_build_h3_graph(request, w)
    assert graph['301']['inputs']['model'] == ['284', 0]
    assert graph['302']['inputs']['model'] == ['301', 0]
    assert graph['303']['inputs']['model'] == ['302', 0]
    assert [graph[str(n)]['inputs']['strength_model'] for n in (301, 302, 303)] == [.6, .6, .7]
    assert graph['303']['inputs']['lora_name'] == w['rh_lora_catalog']['minimax-n4']
    assert graph['221']['inputs']['model'] == graph['224']['inputs']['model'] == ['303', 0]
    assert graph['225']['inputs']['ref_images.ref_image_1'] == ['294', 0]
    assert graph['294']['class_type'] == 'LoadImage'
    assert graph['223']['inputs']['audio'] == ['275', 2]
    assert not {'279', '280', '292', '285'} & graph.keys()
    for row in graph.values():
        for value in row['inputs'].values():
            if isinstance(value, list) and len(value) == 2:
                assert value[0] in graph


def test_disabled_slots_bypass_without_loading(panel):
    w = panel.WORKFLOWS['h3_edit_n']
    graph = panel.rh_build_h3_graph(job({'lora_1_model': 'none', 'lora_2_strength': 0,
                                       'lora_3_model': 'minimax-n1', 'lora_3_strength': .85}), w)
    assert '301' not in graph and '302' not in graph
    assert graph['303']['inputs']['model'] == ['284', 0]
    assert graph['303']['inputs']['strength_model'] == .85
    assert graph['303']['inputs']['lora_name'] == w['rh_lora_catalog']['minimax-n1']
    graph = panel.rh_build_h3_graph(job({f'lora_{i}_model': 'none' for i in range(1, 4)}), w)
    assert graph['221']['inputs']['model'] == graph['224']['inputs']['model'] == ['284', 0]
    assert all(row['class_type'] != 'LoraLoaderModelOnly' for row in graph.values())


def test_model_allowlist_and_numeric_validation(panel):
    w = panel.WORKFLOWS['h3_edit_n']
    for params in ({'lora_1_model': '../anything.safetensors'}, {'lora_2_strength': float('nan')},
                   {'lora_3_strength': 2.1}, {'lora_1_strength': ''}):
        with pytest.raises(ValueError):
            panel.rh_build_h3_graph(job(params), w)
    public = json.dumps(panel.public_workflow(w))
    assert '.safetensors' not in public and 'rh_lora_catalog' not in public


def test_single_reference_uses_full_graph_once(panel, monkeypatch):
    calls = []
    def provider(req, **kwargs):
        calls.append(json.loads(req.data))
        return {'code': 0, 'data': {'taskId': 'offline-task'}}
    monkeypatch.setattr(panel, '_provider_json_request', provider)
    monkeypatch.setattr(panel, 'persist_provider_task', lambda *a: None)
    monkeypatch.setattr(panel, '_rh_wait_task', lambda *a: [{'fileUrl': 'https://example.test/video.mp4', 'fileType': 'mp4'}])
    request = job()
    panel.rh_run_video(request, panel.WORKFLOWS['h3_edit_n'])
    assert len(calls) == 1
    assert '303' in json.loads(calls[0]['workflow'])


def test_browser_slots_roundtrip(browser, panel):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    serve_page(page)
    workflow = panel.public_workflow(panel.WORKFLOWS['h3_edit_n'])
    page.route('**/api/workflows', lambda route: route.fulfill(json=[workflow]))
    page.route('**/api/video-queue', lambda route: route.fulfill(json={'jobs': [], 'running': 0, 'waiting': 0, 'limit': 2}))
    try:
        page.goto('http://fixture.test/video')
        host = current(page)
        details = host.locator('.lora-settings')
        details.wait_for()
        assert not details.evaluate('(e) => e.open')
        details.locator('summary').click()
        assert details.locator('select').count() == 3
        host.locator('#param_lora_1_model').select_option('none')
        assert host.locator('#param_lora_1_strength').is_disabled()
        host.locator('#param_lora_2_strength').fill('0.85')
        assert details.locator('input[type=range]').nth(1).input_value() == '0.85'
        details.locator('summary').click()
        details.locator('summary').click()
        assert host.locator('#param_lora_2_strength').input_value() == '0.85'
        page.screenshot(path=str(panel.BASE/'audit/h3_lora_revision_20260928/integrated-slots.png'))
        details.locator('.lora-reset').click()
        assert host.locator('#param_lora_1_model').input_value() == 'minimax-n6'
        assert host.locator('#param_lora_2_strength').input_value() == '0.6'
        assert not errors
    finally:
        page.close()
