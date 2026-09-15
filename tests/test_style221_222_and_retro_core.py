import json,re
from pathlib import Path
from _style_config_contract import load_style_configs
ROOT=Path(__file__).resolve().parents[1]
BUILD=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')

def styles():
    return load_style_configs(ROOT, "index.html")

def test_fixed_style_core_precedes_random_content():
    assert "parts=[cfg().prefix,cfg().head,cfg().style]" in BUILD
    assert "parts=[cfg().prefix,cfg().head]" not in BUILD

def test_retro_core_preserves_weighted_reverse_prompt_anchors():
    retro=json.loads((ROOT/'sources/retro_manga_luxury_profile.json').read_text(encoding='utf8'))
    core=retro['style']
    for token in ('(traditional hand-drawn illustration:1.3)','(alcohol marker rendering:1.25)','(bold black shadow masses:1.3)','(scanned analog artwork:1.2)'):
        assert token in core

def test_style221_and_style222_are_exact_trusted_step400_profiles():
    s=styles()
    assert s['style221']['trigger']=='zxqelun'
    assert s['style222']['trigger']=='zxqavri'
    assert set(s['style221']['pools'])==set(s['style222']['pools'])
    assert '11_style221_v1_step400.safetensors' in SERVER
    assert '10_style222_v1_step400.safetensors' in SERVER
    assert 'zxqelun' in SERVER and 'zxqavri' in SERVER
    assert SERVER.count('"strengths": {"LORA1": 0.4, "LORA2": 0.0}') >= 3

def test_new_style_cores_match_reverse_engineered_documents():
    a=json.loads((ROOT/'sources/style221_profile.json').read_text(encoding='utf8'))
    b=json.loads((ROOT/'sources/style222_profile.json').read_text(encoding='utf8'))
    for token in ('painterly digital oil painting','visible expressive brush strokes','lost and found edges','muted low-saturation colors'):
        assert token in a['style']
    for token in ('fine engraved linework','etching texture','dense parallel hatching','delicate cross-hatching'):
        assert token in b['style']
    assert 'smooth digital rendering' in a['negative']
    assert 'cheap CGI' in b['negative']


def test_style_fidelity_profiles_use_sparse_random_without_removing_options():
    s=styles()
    expected={'hair','expression','outfit','accessory','pose','camera','background','accent','special_prompt'}
    for style_id in ('retro_manga_luxury','style221','style222'):
        assert set(s[style_id]['sparseRandomKeys'])==expected
        assert len(s[style_id]['pools'])==32
    assert "cfg().sparseRandomKeys" in BUILD


def test_new_style_panel_e2e_evidence_matches_trusted_profiles():
    evidence=json.loads((ROOT/'audit/style221_222_panel_e2e_20260913.json').read_text(encoding='utf8'))
    assert evidence['verification']=='PASS'
    expected={'style221':('zxqelun',5),'style222':('zxqavri',3)}
    for style_id,(trigger,coins) in expected.items():
        row=evidence['workflows'][style_id]
        assert row['trigger']==trigger and row['weight']==0.4
        assert row['submit_attempts']==1 and row['status']=='done' and row['history_occurrences']==1
        assert row['rh_coins']==str(coins) and row['png_signature'] is True
        assert len(row['artifact_sha256'])==64 and len(row['model_sha256'])==64


def test_new_styles_disclose_that_no_quality_approved_preview_is_available():
    html=(ROOT/'static/index.html').read_text(encoding='utf8')
    assert '暂无通过质量审核的预览' in html
    assert "if(!thumb){stylePreview.removeAttribute('src')" in html
