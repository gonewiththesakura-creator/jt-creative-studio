from pathlib import Path
import sys
s = (Path(__file__).resolve().parents[1] / 'static' / 'promptgen.html').read_text(encoding='utf8')
checks={
 'hd selector exists':'id="genHd"' in s,
 'three hd choices':all(x in s for x in ['关闭','ClearReality 2×','UltraSharp 2×']),
 'hd submitted':'hd:+genHd.value' in s,
 'hd in snapshot':'hd:+genHd.value' in s and 'selection_snapshot:{...snapshotSelections()' in s,
 'hd reapplied':'genHd.value=snapshot.hd||0' in s,
 'lora still hidden':all(x not in s for x in ['id="genLora1"','id="genLora2"','id="genTrigger"']),
}
for k,v in checks.items(): print(k,v)
sys.exit(0 if all(checks.values()) else 1)
