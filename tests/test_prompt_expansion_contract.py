from pathlib import Path
import json,re,sys

ROOT = Path(__file__).resolve().parents[1]
HTML=(ROOT/"static"/"promptgen.html").read_text(encoding="utf8")
MANIFEST=ROOT/"sources"/"pool_union_manifest.json"
EXPECTED={
 "character_inspired":{"祢豆子（成年再演绎）"},
 "character":{"温柔丰润沙漏型","高挑曲线模特型","柔软梨形曲线","健美曲线型"},
 "expression":{"羞涩忍笑","被发现后的微惊","害羞回避目光","若有所思微红","欲言又止","安静回神","尴尬浅笑","温柔疲倦"},
 "interaction":{"抱书回眸","翻书时抬眼","书签夹好后转头","听见呼唤后抱书转身","从肩后轻轻偷看","回头后移开视线","低头抱书发呆","递出合上的书"},
 "prop":{"硬壳素描本","旧精装书","夹着书签的书","小开本诗集","速写本和铅笔","两三本叠放书籍","图书馆借阅书","膝上的合书"},
 "special_outfit":{"肤色全包舞蹈连体衣","黑色高领全包练功服","古典披布人体写生","长袖芭蕾练功服","单色瑜伽训练套装"},
 "special_prompt":{"脸颊和耳尖一起泛红","指尖轻沾石墨灰","一缕头发贴在脸颊","淡淡眼下阴影","嘴唇轻抿","露出一小截丝带书签","膝部保留结构辅助线","衣料在屈膝处自然堆叠"},
 "pose":{"抱书蹲在镜头前","半蹲转身回眸","单膝蹲下抱书","蹲姿侧身护书","坐地抱书膝盖前景","膝上放书回头","近镜蜷膝读书","起身一半回头","俯身捡书回头","背身蹲坐侧脸回看"},
 "camera":{"轻俯拍膝盖前景","肩后回眸近景","书本前景近景","镜头略高于眼睛","蹲姿广角近景","侧后方轻俯拍","膝盖高度平视","安静手持抓拍感"},
 "story":{"图书馆闭馆前的停顿","合上书后仍在发呆","读到一半听见名字","雨天书店门口","午后窗边做速写","借书时意外回眸","给书夹好书签","深夜画完最后一页","旧书中发现纸条","休息时把书抱在膝上"},
 "background":{"淡雾蓝马克笔底","淡鼠尾草绿马克笔底","淡灰紫马克笔底","淡米杏马克笔底","淡茶褐马克笔底","淡珊瑚粉马克笔底","淡黄土马克笔底","冷灰蓝马克笔底"},
 "accent":{"黑白 + 焦橙","黑白 + 森林绿","黑白 + 棕褐","黑白 + 灰青","黑白 + 赭金","黑白 + 酒红","黑白 + 珊瑚粉","藏蓝 + 淡粉双点缀"},
}
checks={"manifest exists":MANIFEST.exists()}
if MANIFEST.exists():
 d=json.loads(MANIFEST.read_text(encoding="utf8"));cur=d.get("curated_expansions",{})
 checks["curated expansion ledger exists"]=bool(cur)
 checks["at least 86 curated rows"]=sum(map(len,cur.values()))>=86
 for cat,labels in EXPECTED.items():
  union={x[0]:x[1] for x in d.get("union_pools",{}).get(cat,[])}
  checks[f"union labels:{cat}"]=labels.issubset(union)
  for sid in ("cold","sketch","graphic"):
   style={x[0]:x[1] for x in d.get("source_pools",{}).get(sid,{}).get(cat,[])}
   checks[f"style source labels:{sid}:{cat}"]=labels.issubset(style)
 # The named character may only be added as an unmistakably adult, covered reinterpretation.
 p={x[0]:x[1] for x in d.get("union_pools",{}).get("character_inspired",[])}.get("祢豆子（成年再演绎）","").lower()
 checks["adult Nezuko boundary"]=all(x in p for x in ["adult reinterpretation","age 20+","fully covered"])
 # Do not put the prompt's explicit anatomy/nudity fragments into the public option expansion.
 new_prompts="\n".join(x[1].lower() for rows in cur.values() for x in rows)
 banned=[r"\bpussy\b",r"\bvulva\b",r"\bgenitals?\b",r"no panties?",r"no cloth(?:e|es|s)",r"visible nipples?",r"spread(?:ing)? pussy"]
 checks["no explicit additions"]=not any(re.search(x,new_prompts) for x in banned)
 checks["wrong user trigger not added"]="jt_style1_v2" not in HTML
 checks["fixed production triggers intact"]=all(x in HTML for x in ["jt_style3_v2","jt_style1_v1","jt_style2_v1"])
for k,v in checks.items():print(k,v)
sys.exit(0 if checks and all(checks.values()) else 1)
