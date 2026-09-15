from pathlib import Path
import hashlib,importlib.util,json,re,sys
from _style_config_contract import load_style_configs
ROOT = Path(__file__).resolve().parents[1]
HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
BUILD=(ROOT/'build_unified_three_styles.py').read_text(encoding='utf8')
PREVIEW_BUILD=(ROOT/'tools/build_preview_assets.py').read_text(encoding='utf8')
styles=load_style_configs(ROOT)
style=styles.get('retro_manga_luxury') or {}
E2E=json.loads((ROOT/'audit/retro_manga_panel_e2e_cloud_w04.json').read_text(encoding='utf8'))
PREVIEW=ROOT/'static/previews/style-retro-manga-luxury.webp'
core='''retro 1980s-1990s Japanese manga fashion illustration,
vintage shoujo manga, josei manga aesthetic,
traditional hand-drawn illustration,
black ink linework,
colored pencil rendering,
alcohol marker coloring,
gouache-like highlights,
visible marker strokes,
slightly rough expressive linework,
textured paper,
scanned analog artwork,

bold black shadow masses,
deep black hair,
high contrast,
sharp colorful hair highlights,
cyan, violet, magenta, pink and golden reflected light,
chromatic highlights,
colored reflected shadows,

pale luminous skin,
blue-purple and peach skin shadows,
long narrow elegant eyes,
heavy detailed eyelashes,
delicate sharp facial features,
small glossy lips,
mature glamorous expression,

luxurious fashion illustration,
ornate gemstone jewelry,
dangling earrings,
layered necklaces,
vintage high-fashion editorial feeling,

dynamic flowing hair,
dramatic crop,
fashion portrait composition'''
negative='''worst quality, low quality, lowres, blurry,
photorealistic, realistic photography, 3d render, CGI,
smooth digital rendering, airbrushed skin, plastic skin,
modern anime screenshot, mobile game illustration, VTuber style,
chibi, kawaii, baby face, huge round eyes,
flat cel shading, clean vector lines, perfect uniform lineart,
cyberpunk, excessive neon glow,
bad anatomy, bad hands, extra fingers, missing fingers,
distorted face, asymmetrical eyes,
cluttered background,
text, watermark, logo, signature'''
doc_required={
'hair':['long black hair','short teal bob','wavy brown hair','silver long hair','blonde braided hair','red ponytail'],
'expression':['calm expression','cold expression','seductive expression','mysterious expression','confident gaze','slightly parted lips'],
'outfit':['black off-shoulder dress','silk evening gown','sleeveless halter top','white loose blouse','lace dress','fashion jacket','elegant black dress','retro glamorous outfit'],
'accessory':['emerald earrings','gold hoop earrings','layered gemstone necklaces','black choker','luxury jewelry','ornate accessories'],
'character':['slim body','curvy body','tall figure','petite figure','graceful body line','elegant proportions'],
'pose':['looking at viewer','three-quarter view','side profile','head tilted slightly','hand near lips','hand touching hair','arms raised','sitting pose','leaning pose','shoulder exposed'],
'camera':['close-up portrait','bust shot','half body','upper body portrait','dramatic crop','fashion magazine composition'],
'background':['minimal cream background','warm orange painterly background','flat yellow background','retro geometric pattern','abstract decorative background','soft pastel background'],
}
checks={
 'style button':'data-style="retro_manga_luxury"' in HTML and '>复古日漫</button>' in HTML,
 'eight style touch layout':'#styleSwitch{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}' in HTML,
 'trusted trigger':style.get('trigger')=='jt_style321_v1' and '"trigger": "jt_style321_v1"' in SERVER,
 'exact lora server trusted':'lora1' not in style and 'lora2' not in style and SERVER.count('09_style321_v1_step200.safetensors')>=2,
 'recommended weight server trusted':'strengths' not in style and '"strengths": {"LORA1": 0.4, "LORA2": 0.0}' in SERVER,
 'verified cloud mapping':E2E.get('verification')=='PASS' and E2E.get('expected_effective_mapping',{}).get('lora')=='09_style321_v1_step200.safetensors',
 'qualified preview':re.fullmatch(r'/static/previews/style-retro-manga-luxury\.webp\?v=[0-9a-f]{12}',style.get('preview','')) is not None and style.get('preview_thumb','').startswith('data:image/webp;base64,'),
 'qualified preview bytes':PREVIEW.is_file() and hashlib.sha256(PREVIEW.read_bytes()).hexdigest()=='2ebb09eea5c1f9944e3a0376991a42b46a5a75bc92d1a83e3033b7522b60bb22',
 'weighted core strengthened':all(x in style.get('style','') for x in ['(traditional hand-drawn illustration:1.3)','(alcohol marker rendering:1.25)','(bold black shadow masses:1.3)','(scanned analog artwork:1.2)']) and all(x in style.get('style','') for x in ['vintage 1980s-1990s','colored pencil','chromatic reflected highlights','luxurious gemstone jewelry']),
 'fixed negative preserved':style.get('negative')==negative,
 'adult base':all(x in style.get('head','') for x in ['1woman','adult woman']),
 'all union categories':bool(style.get('pools')) and all(k in style['pools'] for k in json.loads((ROOT/'sources/pool_union_manifest.json').read_text(encoding='utf8'))['union_counts']),
 'never fewer than union':bool(style.get('pools')) and all(len(style['pools'].get(k,[]))>=n for k,n in json.loads((ROOT/'sources/pool_union_manifest.json').read_text(encoding='utf8'))['union_counts'].items()),
 'every category has none':bool(style.get('pools')) and all(any(row[1]=='' for row in rows) for rows in style['pools'].values()),
 'all document options':bool(style.get('pools')) and all(all(any(req in row[1] for row in style['pools'].get(k,[])) for req in required) for k,required in doc_required.items()),
 'rich additive expansion':bool(style.get('pools')) and sum(len(v) for v in style['pools'].values())>=sum(json.loads((ROOT/'sources/pool_union_manifest.json').read_text(encoding='utf8'))['union_counts'].values())+70,
 'history scope':"retro_manga_luxury" in SERVER,
 'browser cannot override lora':'loras = {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]}' in SERVER,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
