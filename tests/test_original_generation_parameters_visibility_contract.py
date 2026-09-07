from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/'static/promptgen.html').read_text(encoding='utf8')
checks={
 'unified styles expose six generation controls':all(x in HTML for x in ['id="genW"','id="genH"','id="genBatch"','id="genHd"','id="seedMode"','id="genSeed"']),
 'controls have clear labels':all(x in HTML for x in ['>宽<','>高<','>批量<','>高清<','>种子模式<','>种子值<']),
 'submit carries exact controls':all(x in HTML for x in ['width:+genW.value','height:+genH.value','batch:+genBatch.value','hd:+genHd.value','seed:seed','seed_mode:seedMode.value']),
 'snapshot stores exact controls':all(x in HTML for x in ['width:+genW.value','height:+genH.value','batch:+genBatch.value','hd:+genHd.value','seed:+genSeed.value','seed_mode:seedMode.value']),
 'snapshot restores exact controls':all(x in HTML for x in ['genW.value=snapshot.width||768','genH.value=snapshot.height||1024','genBatch.value=snapshot.batch||1','genHd.value=snapshot.hd||0','genSeed.value=snapshot.seed||newRandomSeed()']),
 'both original styles use same controls':all(x in HTML for x in ['data-style="original_sketch"','data-style="original_graphic"']),
 'staged painting removed':'id="sketchProcess"' not in HTML,
}
for k,v in checks.items():print(k,v)
sys.exit(0 if all(checks.values()) else 1)
