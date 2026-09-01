from pathlib import Path
import sys
ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf-8")
checks={
 "does not auto randomize": "randomAll()" not in HTML.split("</script>")[-2].split("document.querySelectorAll('[data-style]')")[-1],
 "each style initializes no-selection": "a.find(x=>!x[1])||a[0]" in HTML,
 "drawers are collapsed initially": "openDrawers=new Set()" in HTML and ".drawer-body{display:none" in HTML,
 "drawer expands on click": "openDrawers.has(d.id)?openDrawers.delete(d.id):openDrawers.add(d.id)" in HTML,
 "five drawer groups": all(x in HTML for x in ['"id":"character"','"id":"body"','"id":"outfit"','"id":"pose"','"id":"background"']),
 "favorite snapshot restores style": "currentStyle=STYLE_CONFIGS[snapshot.style]?snapshot.style:'cold'" in HTML,
 "favorite snapshot restores mode": "currentMode=snapshot.mode||'original'" in HTML,
 "favorite restores selected values": "snapshot.state[k]" in HTML,
 "favorite has no third-level option cards": "expandedKeys" not in HTML,
 "favorite opens relevant drawers": "openDrawers=new Set(Object.keys(state()).filter" in HTML and ".map(drawerFor).filter(Boolean)" in HTML,
 "snapshot keeps dimensions batch HD": all(x in HTML for x in ["width:+genW.value","height:+genH.value","batch:+genBatch.value","hd:+genHd.value"]),
}
for k,v in checks.items(): print(k,v)
sys.exit(0 if all(checks.values()) else 1)
