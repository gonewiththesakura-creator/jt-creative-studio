from pathlib import Path
import sys
s=Path(r'D:/LAN-Share/lora/_work/comfy_panel/static/promptgen.html').read_text(encoding='utf8')
checks={
 'hd selector exists':'id="genHd"' in s,
 'three hd choices':all(x in s for x in ['关闭（原图直出）','ClearReality 极速2×','UltraSharp 精细2×']),
 'hd submitted':"parseInt(document.getElementById('genHd').value)" in s,
 'hd in snapshot':"hd: parseInt(document.getElementById('genHd')?.value" in s,
 'hd reapplied':"document.getElementById('genHd').value=String(snapshot.hd||0)" in s,
 'lora still hidden':all(x not in s for x in ['id="genLora1"','id="genLora2"','id="genTrigger"']),
}
for k,v in checks.items(): print(k,v)
sys.exit(0 if all(checks.values()) else 1)
