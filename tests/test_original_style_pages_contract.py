from pathlib import Path
import json,re,sys
ROOT = Path(__file__).resolve().parents[1]
HOME=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
SERVER=(ROOT/'server.py').read_text(encoding='utf8')
match=re.search(r"const STYLE_CONFIGS=(.*?);const DRAWERS=",HOME,re.S)
styles=json.loads(match.group(1)) if match else {}
checks={
 'original profiles embedded':set(['original_sketch','original_graphic']).issubset(styles),
 'original pool category counts':len(styles.get('original_sketch',{}).get('pools',{}))==17 and len(styles.get('original_graphic',{}).get('pools',{}))==12,
 'original exact option row counts':sum(map(len,styles.get('original_sketch',{}).get('pools',{}).values()))==230 and sum(map(len,styles.get('original_graphic',{}).get('pools',{}).values()))==66,
 'trusted backend identities':styles.get('original_sketch',{}).get('trigger')=='jt_style1_v1' and styles.get('original_graphic',{}).get('trigger')=='jt_style2_v1' and all(x in SERVER for x in ['"original_sketch": {','"original_graphic": {']),
 'original sketch uses ordinary generation':all(x in HOME for x in ["const sequence_mode='off'",'batch:+genBatch.value']) and 'id="sketchProcess"' not in HOME,
 'home unified style buttons':all(x in HOME for x in ['data-style="original_sketch"','原始铅绘','data-style="original_graphic"','原始古风']),
 'home has no duplicate top nav':all(x not in HOME for x in ['href="/original-sketch"','href="/original-graphic"']),
 'server legacy redirects':all(x in SERVER for x in ['path in ("/original-sketch", "/original-graphic")','/?style=']),
}
for name,target in [('original_sketch.html','/?style=original_sketch'),('original_graphic.html','/?style=original_graphic')]:
 html=(ROOT/'static'/name).read_text(encoding='utf8')
 checks[name+' lightweight redirect']=target in html and 'location.replace' in html and len(html)<1500
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
