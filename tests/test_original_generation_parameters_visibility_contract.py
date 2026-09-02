from html.parser import HTMLParser
from pathlib import Path
import sys

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
PAGES=[ROOT/"static"/"original_sketch.html",ROOT/"static"/"original_graphic.html"]
CONTROL_IDS={"cloudW","cloudH","cloudBatch","cloudHd","cloudSeedMode","cloudSeed"}

class ControlTree(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.controls={};self.headings=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=set(attrs.get("class","").split());node=(tag,classes,attrs.get("id"));self.stack.append(node)
        if attrs.get("id") in CONTROL_IDS:
            self.controls[attrs["id"]]=[set(x[1]) for x in self.stack[:-1]]
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];return

checks={}
for path in PAGES:
    html=path.read_text(encoding="utf8");tree=ControlTree();tree.feed(html);name=path.stem
    checks[f"{name} has all six controls"]=set(tree.controls)==CONTROL_IDS
    checks[f"{name} controls outside hidden legacy source"]=all(
        "original-content" not in set().union(*ancestors) for ancestors in tree.controls.values()
    )
    checks[f"{name} clear parameter heading"]="<h2>生成参数</h2>" in html
    checks[f"{name} width height batch hd labels"]=all(label in html for label in [">宽度<",">高度<",">批量<",">高清<"])
    checks[f"{name} seed labels"]=all(label in html for label in [">种子模式<",">种子值<"])
    checks[f"{name} submit carries exact controls"]=all(x in html for x in [
        "width:+cloudW.value","height:+cloudH.value","batch:+cloudBatch.value",
        "hd:+cloudHd.value","seed:+cloudSeed.value","seed_mode:cloudSeedMode.value"
    ])
    checks[f"{name} snapshot restores exact controls"]=all(x in html for x in [
        "width:+cloudW.value","height:+cloudH.value","batch:+cloudBatch.value","hd:+cloudHd.value",
        "cloudW.value=s.width||768","cloudH.value=s.height||1024","cloudBatch.value=s.batch||1",
        "cloudHd.value=s.hd||0","cloudSeed.value=s.seed||cloudNewSeed()"
    ])
for key,value in checks.items():print(key,value)
sys.exit(0 if all(checks.values()) else 1)
