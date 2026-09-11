from pathlib import Path
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SERVER=(ROOT/'server.py').read_text(encoding='utf-8')
BUILDER=(ROOT/'build_realism_workbench.py').read_text(encoding='utf-8')
PAGES=[ROOT/'static'/name for name in ['index.html','promptgen.html','original_sketch.html','original_graphic.html','video.html','realcomic.html','realism.html']]

def test_one_realism_top_level_navigation():
 for page in PAGES:
  html=page.read_text(encoding='utf-8')
  if page.name == 'realcomic.html':
   assert 'href="/realism?workflow=realcomic"' in html
   continue
  if page.name in ('original_sketch.html','original_graphic.html'):
   assert 'http-equiv="refresh"' in html and '创作台画风' in html
   continue
  assert html.count('href="/realism"')==1,(page.name,html.count('href="/realism"'))
  assert 'href="/realcomic"' not in html,page.name
  assert '>真人化<' in html
  assert '真人化工作流' not in html.split('<nav class="topnav">',1)[1].split('</nav>',1)[0]

def test_legacy_realcomic_route_redirects_to_unified_console():
 assert 'if path == "/realcomic"' in SERVER
 assert 'Location", "/realism?workflow=realcomic"' in SERVER

def test_unified_console_supports_ai_app_adapter():
 assert "current.kind==='ai_app'" in BUILDER
 assert "/api/realcomic-upload" in BUILDER
 assert "/api/ai-app-generate" in BUILDER
 assert "new URLSearchParams(location.search).get('workflow')" in BUILDER
 assert '快速真人化（原漫画转真人）' in (ROOT/'config.json').read_text(encoding='utf-8')

def test_3in1_is_absent_after_user_retirement_decision():
 config=(ROOT/'config.json').read_text(encoding='utf-8')
 assert '"id": "realism_3in1"' not in config
 audit=(ROOT/'audit/private_realism_workflows/e2e_manifest.json').read_text(encoding='utf-8')
 assert '"three_in_one_retired": true' in audit

def test_legacy_realcomic_jobs_and_favorites_are_migrated():
 assert 'jt-active-realcomic-cloud' in BUILDER
 assert "[SOURCE_PAGE,'realcomic'].includes" in BUILDER
 assert "snapshot.source_page==='realcomic'" in BUILDER
