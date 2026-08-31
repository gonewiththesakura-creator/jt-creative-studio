from pathlib import Path
import copy, json, re, subprocess, tempfile

ROOT=Path(r"D:/LAN-Share/lora/_work/comfy_panel")
STATIC=ROOT/"static"
SRC=ROOT/"sources"
SRC.mkdir(exist_ok=True)
COLD_SRC=SRC/"cold_promptgen_source.html"
if not COLD_SRC.exists():
    COLD_SRC.write_bytes((STATIC/"promptgen.html").read_bytes())
GRAPHIC=Path(r"C:/Users/JT/AppData/Local/hermes/attachments/graphic_anime_style2_dual_mode_generator.html")
SKETCH=Path(r"C:/Users/JT/AppData/Local/hermes/attachments/sketch_anime_dual_mode_generator.html")

def js_config(path, start, end, names):
    text=path.read_text(encoding="utf-8")
    block=text[text.index(start):text.index(end,text.index(start))]
    expr=','.join(names)
    code=block+f"\nconsole.log(JSON.stringify({{{expr}}}));"
    tmp=SRC/(path.stem+"_extract.js")
    tmp.write_text(code,encoding="utf-8")
    r=subprocess.run(["node",str(tmp)],capture_output=True,text=True,encoding="utf-8")
    tmp.unlink(missing_ok=True)
    if r.returncode: raise RuntimeError(r.stderr)
    return json.loads(r.stdout)

cold=js_config(COLD_SRC,"const FIXED_HEAD","const DROPDOWN_KEYS",["FIXED_HEAD","FIXED_STYLE","NEGATIVE","POOLS","LABELS"])
sketch=js_config(SKETCH,"const DEFAULT_PREFIX","const ORDER",["DEFAULT_PREFIX","FIXED_HEAD","FIXED_STYLE","NEGATIVE","POOLS","LABELS"])
graphic=js_config(GRAPHIC,"const DEFAULT_PREFIX","const ORDER",["DEFAULT_PREFIX","FIXED_HEAD","FIXED_STYLE","NEGATIVE","POOLS","LABELS"])
# The attachment's jt_style2_v1 token does not match the trained delivery token.
graphic["FIXED_STYLE"]=re.sub(r"\bjt_style2_v1\s*,?\s*","",graphic["FIXED_STYLE"])

RAW_SOURCE_POOLS={
 "cold":copy.deepcopy(cold["POOLS"]),
 "sketch":copy.deepcopy(sketch["POOLS"]),
 "graphic":copy.deepcopy(graphic["POOLS"]),
}

ADULT_CHARACTERS=[
 ["无（原创人物）",""],
 ["芙莉莲（成年形态）","adult Frieren, recognizable elven mage heroine, very long silver-white hair, green eyes, pointed elf ears, age 20+ adult reinterpretation"],
 ["申鹤","adult Shenhe, recognizable elegant adeptus disciple, long white hair, pale cyan eyes, age 20+"],
 ["雷电影","adult Raiden Shogun, recognizable long dark-purple hair, violet eyes, composed ruler aura, age 20+"],
 ["八重神子","adult Yae Miko, recognizable long pink hair, shrine-maiden aura, age 20+"],
 ["2B","adult-coded 2B android, recognizable white bob hair, black visor and black combat dress"],
 ["纲手","adult Tsunade, recognizable blonde hair, forehead diamond mark, powerful mature woman"],
 ["18号","adult Android 18, recognizable blonde bob, pale-blue eyes, cool composed fighter"],
 ["布尔玛（成年）","adult Bulma, recognizable blue hair, genius scientist and inventor, age 20+"],
 ["Makima","adult Makima, recognizable auburn braided hair, golden ringed eyes, composed authority figure"],
 ["C.C.","adult C.C., recognizable long mint-green hair, golden eyes, mysterious elegant aura"],
 ["妮可·罗宾","adult Nico Robin, recognizable long black hair, mature elegant archaeologist"],
 ["娜美（成年）","adult Nami, recognizable long orange hair, confident navigator, age 20+"],
 ["博雅·汉库克","adult Boa Hancock, recognizable very long black hair, regal pirate-empress aura"],
]
for c in (cold,sketch,graphic):
    existing=c["POOLS"].get("character_inspired",[])
    merged=[list(x) for x in existing]
    seen={tuple(x) for x in merged}
    for item in ADULT_CHARACTERS:
        if tuple(item) not in seen:
            merged.append(list(item));seen.add(tuple(item))
    c["POOLS"]["character_inspired"]=merged

# Curated expansion distilled from the user's combined prompt.  Existing
# rows are not repeated here: closed book, looking back, the original crouch
# perspective, high-angle close-up, shy blush, absent-minded pause,
# blush-pink wash, navy accents, and curvy/hourglass figures already exist in
# the source union.  These rows add adjacent controls while preserving the
# three original vocabularies verbatim.
#
# Public-panel boundary: the supplied explicit anatomy/nudity fragments are
# intentionally not options.  Nezuko is a canon minor, so the only new named
# entry is an unmistakably age-20+ reinterpretation in her fully covered
# classic outfit; it cannot be combined with an explicit nude preset because
# this panel contains no such preset.
CURATED_EXPANSIONS={
 "character_inspired":[
  ["祢豆子（成年再演绎）","adult reinterpretation of Nezuko Kamado, clearly age 20+, recognizable adult Nezuko-inspired design, gentle protective demon heroine, long black hair with orange-red gradient, pink eyes, bamboo gag aesthetic, fully covered signature kimono styling, non-explicit"],
 ],
 "character":[
  ["温柔丰润沙漏型","clearly adult woman, soft full hourglass figure, balanced bust and hips, graceful mature presence"],
  ["高挑曲线模特型","clearly adult tall curvy woman, long legs, defined waist, elegant fashion-model proportions"],
  ["柔软梨形曲线","clearly adult woman, soft pear-shaped figure, narrower shoulders, fuller hips and thighs, natural proportions"],
  ["健美曲线型","clearly adult athletic-curvy woman, toned waist and legs, strong graceful silhouette"],
 ],
 "expression":[
  ["羞涩忍笑","shy restrained smile, slightly stronger blush, trying not to laugh"],
  ["被发现后的微惊","subtle startled expression after being noticed, softly widened eyes, restrained reaction"],
  ["害羞回避目光","shy expression, gaze briefly avoiding viewer, warm blush on cheeks"],
  ["若有所思微红","thoughtful distant expression with a faint blush, quiet introspective mood"],
  ["欲言又止","hesitant expression as if about to speak, softly parted lips, restrained emotion"],
  ["安静回神","quiet expression returning from a daydream, softened eyes, subtle awareness"],
  ["尴尬浅笑","small awkward smile, mild embarrassment, composed adult expression"],
  ["温柔疲倦","gentle tired expression, relaxed eyelids, faint warm smile"],
 ],
 "interaction":[
  ["抱书回眸","holding a closed book against chest while looking back over shoulder toward viewer"],
  ["翻书时抬眼","pausing while reading, eyes lifting from the open book toward viewer"],
  ["书签夹好后转头","turning toward viewer just after placing a bookmark inside the book"],
  ["听见呼唤后抱书转身","turning after hearing her name, holding a book close to body"],
  ["从肩后轻轻偷看","softly peeking toward viewer over one shoulder, restrained eye contact"],
  ["回头后移开视线","looking back briefly, then shifting gaze away with shy restraint"],
  ["低头抱书发呆","looking down while hugging a closed book, absent-minded pause"],
  ["递出合上的书","offering a closed book toward viewer with a gentle reserved gesture"],
 ],
 "prop":[
  ["硬壳素描本","holding a closed hardbound sketchbook"],
  ["旧精装书","holding an old clothbound hardcover book with worn edges"],
  ["夹着书签的书","holding a closed book with a ribbon bookmark visible"],
  ["小开本诗集","holding a small closed poetry book"],
  ["速写本和铅笔","holding a closed sketchbook with a graphite pencil tucked along its edge"],
  ["两三本叠放书籍","holding a small stack of two or three closed books"],
  ["图书馆借阅书","holding a plain closed library book without readable text"],
  ["膝上的合书","a closed book resting across the knees"],
 ],
 "special_outfit":[
  ["肤色全包舞蹈连体衣","clearly adult woman wearing an opaque skin-tone full-coverage long-sleeve dance unitard, anatomical figure-study styling, no nudity"],
  ["黑色高领全包练功服","clearly adult woman wearing an opaque black high-neck full-coverage practice bodysuit, non-explicit figure-study outfit"],
  ["古典披布人体写生","clearly adult woman fully wrapped in opaque classical drapery for an academic figure study, breasts and crotch covered"],
  ["长袖芭蕾练功服","clearly adult woman wearing a long-sleeve ballet practice leotard with opaque tights, fully covered"],
  ["单色瑜伽训练套装","clearly adult woman wearing an opaque monochrome long-sleeve yoga training set, fully covered"],
 ],
 "special_prompt":[
  ["脸颊和耳尖一起泛红","soft blush spreading across cheeks and ear tips, restrained adult expression"],
  ["指尖轻沾石墨灰","faint graphite smudges on fingertips from drawing"],
  ["一缕头发贴在脸颊","one loose hair strand resting against cheek"],
  ["淡淡眼下阴影","subtle tired shadow beneath eyes, soft hand-drawn shading"],
  ["嘴唇轻抿","lips pressed together gently, restrained expression"],
  ["露出一小截丝带书签","a short ribbon bookmark peeking from the closed book"],
  ["膝部保留结构辅助线","faint construction lines remaining around knees, intentional sketch-process detail"],
  ["衣料在屈膝处自然堆叠","natural fabric compression and folds around bent knees"],
 ],
 "pose":[
  ["抱书蹲在镜头前","clearly adult woman crouching close to camera while holding a closed book, knees forming foreground, balanced dramatic perspective"],
  ["半蹲转身回眸","clearly adult woman in a half-crouch, torso turning away, looking back over shoulder"],
  ["单膝蹲下抱书","clearly adult woman crouching on one knee, closed book held against chest, stable editorial pose"],
  ["蹲姿侧身护书","clearly adult woman crouching in side view, holding a book protectively near torso"],
  ["坐地抱书膝盖前景","clearly adult woman seated on floor hugging a closed book, bent knees creating foreground depth"],
  ["膝上放书回头","seated with a closed book resting on knees, torso turned to look back toward viewer"],
  ["近镜蜷膝读书","sitting close to camera with knees drawn up, quietly reading, compact foreshortened composition"],
  ["起身一半回头","halfway rising from a crouch, turning head back toward viewer, natural transitional pose"],
  ["俯身捡书回头","bending to pick up a fallen book while glancing back over shoulder, dynamic but non-explicit"],
  ["背身蹲坐侧脸回看","crouching with back three-quarter view, turning face toward viewer, fully clothed editorial pose"],
 ],
 "camera":[
  ["轻俯拍膝盖前景","slight high angle close shot, knees creating foreground, subtle balanced foreshortening"],
  ["肩后回眸近景","rear three-quarter close portrait, face viewed over shoulder, soft perspective compression"],
  ["书本前景近景","close portrait with a book entering foreground, face and hands kept readable"],
  ["镜头略高于眼睛","camera positioned just above eye level, gentle downward perspective"],
  ["蹲姿广角近景","mild wide-angle close shot of a crouching figure, knees enlarged naturally in foreground"],
  ["侧后方轻俯拍","slight high angle from rear three-quarter side, emphasizing shoulder turn and silhouette"],
  ["膝盖高度平视","camera at knee height, seated upper body receding gently into depth"],
  ["安静手持抓拍感","eye-level handheld snapshot feeling, subtle asymmetry, intimate sketchbook framing"],
 ],
 "story":[
  ["图书馆闭馆前的停顿","quiet pause just before the library closes, book held close, introspective mood"],
  ["合上书后仍在发呆","remaining lost in thought after closing a book, absent-minded stillness"],
  ["读到一半听见名字","hearing her name while halfway through reading, turning in a small surprised pause"],
  ["雨天书店门口","waiting outside a bookstore on a rainy day, holding a book beneath shelter"],
  ["午后窗边做速写","making a quiet afternoon sketch beside a window, pencil-and-paper mood"],
  ["借书时意外回眸","unexpectedly glancing back while borrowing a book, restrained narrative moment"],
  ["给书夹好书签","carefully placing a ribbon bookmark before closing the book"],
  ["深夜画完最后一页","finishing the last sketchbook page late at night, tired satisfied pause"],
  ["旧书中发现纸条","discovering a small note inside an old book, quietly surprised expression"],
  ["休息时把书抱在膝上","resting with a closed book held across knees, calm intimate character-study mood"],
 ],
 "background":[
  ["淡雾蓝马克笔底","very pale mist-blue marker wash behind character, sparse graphite hatch marks"],
  ["淡鼠尾草绿马克笔底","very pale sage-green marker wash behind character, sparse pencil hatching"],
  ["淡灰紫马克笔底","very pale gray-violet marker wash behind character, restrained graphite accents"],
  ["淡米杏马克笔底","very pale beige-apricot marker wash behind character, large white negative space"],
  ["淡茶褐马克笔底","very pale tea-brown marker wash behind character, subtle sketchbook warmth"],
  ["淡珊瑚粉马克笔底","very pale coral-pink marker wash behind character, sparse graphite edge marks"],
  ["淡黄土马克笔底","very pale ochre marker wash behind character, light pencil construction marks"],
  ["冷灰蓝马克笔底","very pale cool gray-blue marker wash behind character, loose graphite shadows"],
 ],
 "accent":[
  ["黑白 + 焦橙","mostly monochrome with restrained burnt-orange accents"],
  ["黑白 + 森林绿","mostly monochrome with muted forest-green accents"],
  ["黑白 + 棕褐","mostly monochrome with soft sepia-brown accents"],
  ["黑白 + 灰青","mostly monochrome with muted blue-green accents"],
  ["黑白 + 赭金","mostly monochrome with restrained ochre-gold accents"],
  ["黑白 + 酒红","mostly monochrome with muted burgundy accents"],
  ["黑白 + 珊瑚粉","mostly monochrome with pale coral-pink accents"],
  ["藏蓝 + 淡粉双点缀","mostly monochrome with muted navy-blue and pale blush-pink dual accents"],
 ],
}

def append_exact_pairs(pools, additions):
    for key,rows in additions.items():
        dst=pools.setdefault(key,[])
        seen={tuple(x) for x in dst}
        for row in rows:
            pair=tuple(row)
            if pair not in seen:
                dst.append(list(row));seen.add(pair)

for c in (cold,sketch,graphic): append_exact_pairs(c["POOLS"],CURATED_EXPANSIONS)

# Additive-only pool policy: every style receives the union of all categories
# and all options from all three source generators. Options are deduplicated by
# their English prompt, never deleted. Style-specific rendering is still
# controlled by each style's FIXED_STYLE + LoRA/trigger mapping.
SOURCE_POOLS={"cold":cold["POOLS"],"sketch":sketch["POOLS"],"graphic":graphic["POOLS"]}
UNION_POOLS={}
for source_pools in SOURCE_POOLS.values():
    for key,items in source_pools.items():
        dst=UNION_POOLS.setdefault(key,[])
        seen={tuple(x) for x in dst}
        for item in items:
            pair=tuple(item)
            if pair not in seen:
                dst.append(list(item));seen.add(pair)
# Every category has an explicit no-op first row.
for key,items in UNION_POOLS.items():
    if not any(x[1]=="" for x in items): items.insert(0,["无（不添加）",""])
for c in (cold,sketch,graphic): c["POOLS"]={k:[list(x) for x in v] for k,v in UNION_POOLS.items()}

SOURCE_COUNTS={sid:{k:len(v) for k,v in pools.items()} for sid,pools in SOURCE_POOLS.items()}
manifest={
 "sources":{"cold":str(COLD_SRC),"sketch":str(SKETCH),"graphic":str(GRAPHIC)},
 "source_counts":SOURCE_COUNTS,
 "source_pools":SOURCE_POOLS,
 "raw_source_pools":RAW_SOURCE_POOLS,
 "curated_expansions":CURATED_EXPANSIONS,
 "union_counts":{k:len(v) for k,v in UNION_POOLS.items()},
 "union_pools":UNION_POOLS,
}
(SRC/"pool_union_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

profiles={
 "cold":{
  "name":"冷脸萌·低饱和细线稿","short":"冷脸萌","trigger":"jt_style3_v2",
  "lora1":"05_style3_v2_step1600.safetensors","lora2":"04_style3_step800.safetensors",
  "prefix":"","head":cold["FIXED_HEAD"],"style":cold["FIXED_STYLE"],"negative":cold["NEGATIVE"],"pools":cold["POOLS"],"labels":cold["LABELS"],
  "originalOnly":[],
  "characterOnly":["character_inspired"],
  "multi":["special_outfit","body_modifier","special_prompt","seductive_pose","special_pose"],
 },
 "sketch":{
  "name":"铅绘·铅笔淡彩手绘风","short":"铅绘","trigger":"jt_style1_v1",
  "lora1":"01_style1_step900.safetensors","lora2":"01_style1_step900.safetensors",
  "prefix":sketch["DEFAULT_PREFIX"],"head":sketch["FIXED_HEAD"],"style":sketch["FIXED_STYLE"],"negative":sketch["NEGATIVE"],"pools":sketch["POOLS"],"labels":sketch["LABELS"],
  "originalOnly":[],"characterOnly":["character_inspired"],
  "multi":["special_outfit","body_modifier","special_prompt","seductive_pose","special_pose"],
  "defaultMode":"character",
  "defaultSelections":{
   "character_inspired":"祢豆子（成年再演绎）",
   "character":"丰满优雅型",
   "expression":"害羞微红",
   "interaction":"回头看镜头",
   "prop":"书本",
   "pose":"蹲姿贴近镜头",
   "camera":"轻微俯拍近景",
   "story":"发呆的空白瞬间",
   "background":"淡粉色马克笔底",
   "accent":"黑白 + 藏蓝"
  },
 },
 "graphic":{
  "name":"古风·东方平面插画风","short":"古风","trigger":"jt_style2_v1",
  "lora1":"02_style2_step900.safetensors","lora2":"02_style2_step900.safetensors",
  "prefix":graphic["DEFAULT_PREFIX"],"head":graphic["FIXED_HEAD"],"style":graphic["FIXED_STYLE"],"negative":graphic["NEGATIVE"],"pools":graphic["POOLS"],"labels":graphic["LABELS"],
  "originalOnly":[],"characterOnly":["character_inspired"],
  "multi":["special_outfit","body_modifier","special_prompt","seductive_pose","special_pose"],
 },
}
# Every option defaults to no contribution. Also remove age-ambiguous prompt wording.
def normalize_profile(p):
    for key,arr in list(p["pools"].items()):
        cleaned=[]
        for label,prompt in arr:
            # Preserve source options verbatim. Safety is supplied by the fixed
            # adult-only head and negative prompt, not by deleting/rewriting the
            # user's original option rows.
            cleaned.append([label,prompt])
        if not any(x[1]=="" for x in cleaned): cleaned.insert(0,["无（不添加）",""])
        p["pools"][key]=cleaned
    p["labels"]["character_inspired"]="角色"
for p in profiles.values(): normalize_profile(p)

DRAWERS=[
 {"id":"character","title":"角色","keys":["character_inspired","hair","eyes","emotion","expression","interaction","species"]},
 {"id":"body","title":"身体","keys":["character","body_modifier","tattoo_color","special_prompt"]},
 {"id":"outfit","title":"服装","keys":["outfit","top","outerwear","bottoms","legwear","footwear","accessory","fashion_extra","special_outfit"]},
 {"id":"pose","title":"姿势与镜头","keys":["pose","seductive_pose","special_pose","view_direction","camera"]},
 {"id":"background","title":"背景与剧情","keys":["prop","holiday","story","theme","scene","background","accent"]},
]
DATA=json.dumps(profiles,ensure_ascii=False,separators=(",",":"))
DRAWS=json.dumps(DRAWERS,ensure_ascii=False,separators=(",",":"))
html=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JT 三画风 RunningHub 控制面板</title><style>
:root{--bg:#f4f7f8;--card:#fff;--ink:#2f3b40;--muted:#82949c;--line:#e1eaed;--accent:#769fb2;--accent2:#eaf3f6;--shadow:0 12px 34px rgba(67,89,99,.08)}*{box-sizing:border-box}body{margin:0;background:linear-gradient(#f9fbfc,var(--bg));font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink)}button,input,select{font:inherit}.wrap{width:min(1100px,calc(100% - 24px));margin:auto;padding:22px 0 80px}.hero h1{margin:0;font-size:clamp(28px,4vw,40px)}.panel,.drawer{background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}.switch{padding:14px;margin:12px 0;display:flex;gap:8px;flex-wrap:wrap}.switch button,.switch .original-link{border:1px solid var(--line);background:#fff;border-radius:13px;padding:10px 14px;color:#667c86;font-weight:800;cursor:pointer;text-decoration:none}.switch button.active{background:var(--accent);color:#fff;border-color:transparent}.switch .original-link{background:#f0f6f8;color:#557888}.note{width:100%;font-size:12px;color:var(--muted);line-height:1.6}.drawer{margin:10px 0;overflow:hidden}.drawer-head{width:100%;border:0;background:#fff;padding:16px 18px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;font-weight:850;color:#566c76}.drawer-body{display:none;padding:0 14px 14px}.drawer.open .drawer-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.item{border:1px solid var(--line);border-radius:15px;padding:12px;background:#fbfdfe}.item-head{display:flex;justify-content:space-between;align-items:center;gap:8px}.item-name{font-size:12px;color:#8b9da5;font-weight:800}.item-actions{display:flex;gap:5px}.item-actions button{border:0;border-radius:9px;width:31px;height:31px;background:#edf4f7;color:#668b9b;cursor:pointer}.picker-wrap{display:block;margin-top:9px}.picker{width:100%;border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff}.actions{display:flex;gap:10px;margin:14px 0}.primary{flex:1;border:0;border-radius:18px;padding:16px;background:linear-gradient(135deg,#86b3c6,#6f9eb2);color:#fff;font-weight:850;cursor:pointer}.settings{padding:15px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.settings label{font-size:11px;color:var(--muted);font-weight:800}.settings input,.settings select{width:100%;margin-top:5px;border:1px solid var(--line);border-radius:10px;padding:9px}.prompt{margin-top:14px;overflow:hidden}.prompt-head{padding:14px 16px;display:flex;justify-content:space-between;align-items:center}.prompt-body{display:none}.prompt.open .prompt-body{display:block}.prompt textarea{width:100%;min-height:300px;border:0;border-top:1px solid var(--line);padding:15px;font:12px/1.6 monospace}.result img,.job img{width:100%;max-height:640px;object-fit:contain;border-radius:12px;background:#f4f4f4}.dl{display:block;width:100%;border:0;text-align:center;margin-top:7px;padding:10px;border-radius:10px;background:#edf4f7;color:#5f8290;font-weight:750;text-decoration:none;cursor:pointer}.floating{position:fixed;right:14px;z-index:50;border:1px solid var(--line);border-radius:16px;padding:10px 13px;background:#fff;box-shadow:var(--shadow);cursor:pointer}.history{bottom:18px}.favorites{bottom:66px}.overlay{display:none;position:fixed;inset:0;z-index:80;background:rgba(244,247,248,.98);overflow:auto;padding:15px}.overlay.open{display:block}.overlay-inner{max-width:680px;margin:auto}.overlay-head{display:flex;justify-content:space-between;align-items:center}.job{border:1px solid var(--line);background:#fff;border-radius:15px;padding:12px;margin:10px 0}.close{border:0;background:none;font-size:25px;cursor:pointer}.status{font-size:13px;color:#607985;font-weight:750;margin:10px 0}@media(max-width:700px){.drawer.open .drawer-body{grid-template-columns:1fr}.settings{grid-template-columns:1fr 1fr}.wrap{padding-top:14px}.floating{position:static;display:inline-block;margin:8px 4px 0 0}.favorites,.history{bottom:auto;right:auto}}
</style></head><body><main class="wrap"><section class="hero"><h1>三画风生图</h1></section>
<section class="panel switch" id="styleSwitch"><button data-style="cold">冷脸萌</button><button data-style="sketch">铅绘</button><button data-style="graphic">古风</button><a class="original-link" href="/original-sketch">原始铅绘 ↗</a><a class="original-link" href="/original-graphic">原始古风 ↗</a></section>
<section class="panel switch" id="modeSwitch"><button data-mode="original">原创人物</button><button data-mode="character">角色模式</button></section>
<div id="drawers"></div><div class="actions"><button class="primary" id="randomAll">随机当前可用选项</button><button class="primary" id="clearAll">全部设为无</button></div>
<section class="panel settings"><label>宽<input id="genW" type="number" value="768" min="256" max="2048" step="16"></label><label>高<input id="genH" type="number" value="1024" min="256" max="2048" step="16"></label><label>批量<input id="genBatch" type="number" value="1" min="1" max="4"><span id="batchNote" style="display:none"></span></label><label>高清<select id="genHd"><option value="0">关闭</option><option value="1">ClearReality 2×</option><option value="2">UltraSharp 2×</option></select></label><label>种子模式<select id="seedMode"><option value="random">每次随机</option><option value="fixed">固定</option></select></label><label>种子值<input id="genSeed" type="number" min="1" max="9007199254740991" step="1"></label><label id="sketchProcessRow" style="display:none">铅绘分步<select id="sketchProcess"><option value="off">关闭（普通出图）</option><option value="3">3步：轮廓→黑白完成→淡彩</option><option value="4">4步：轮廓→成型→黑白完成→淡彩</option></select></label></section>
<section class="panel switch" id="promptModePanel"><b style="width:100%">提示词输入</b><label><input type="radio" name="promptModeRadio" value="options" checked> 选项组合</label><label><input type="radio" name="promptModeRadio" value="manual"> 手动提示词</label><select id="promptMode" style="display:none"><option value="options">选项组合</option><option value="manual">手动提示词</option></select></section>
<section class="panel prompt" id="manualPromptPanel" style="display:none"><div class="prompt-head"><b>手动正向提示词</b></div><textarea id="manualPositive" placeholder="输入正向提示词；不用重复写画风触发词"></textarea><div class="prompt-head"><b>手动负向提示词</b></div><textarea id="manualNegative" placeholder="输入负向提示词"></textarea></section>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px"><button class="primary" id="genCloudBtn">☁ 云端生图</button><button class="primary" id="genLocalBtn" style="background:linear-gradient(135deg,#668e86,#456e68)">🖥 本地ComfyUI生图</button></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px"><section class="panel" data-backend="cloud" style="padding:12px"><b>云端结果</b><div class="status" id="genCloudStatus"></div><div class="result" id="genCloudResult"></div></section><section class="panel" data-backend="local" style="padding:12px"><b>本地结果</b><div class="status" id="genLocalStatus"></div><div class="result" id="genLocalResult"></div></section></div>
<section class="panel prompt" id="promptPanel"><div class="prompt-head"><b>详细提示词</b><div><button class="dl" id="copyPrompt" style="display:inline-block;width:auto">复制</button><button class="dl" id="promptToggle" style="display:inline-block;width:auto">展开</button></div></div><div class="prompt-body"><textarea id="promptText"></textarea></div></section></main>
<button class="floating favorites" id="favOpen">♥ 收藏</button><button class="floating history" id="histOpen">📁 历史</button><div class="overlay" id="histOverlay"><div class="overlay-inner"><div class="overlay-head"><h2>历史记录</h2><button class="close">×</button></div><div id="histList"></div></div></div><div class="overlay" id="favOverlay"><div class="overlay-inner"><div class="overlay-head"><h2>我的收藏</h2><button class="close">×</button></div><div id="favList"></div></div></div>
<script>const STYLE_CONFIGS=__DATA__;const DRAWERS=__DRAWERS__;
const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d};
let currentStyle='sketch',currentMode='character',stateByStyle={},lockedByStyle={},openDrawers=new Set(),genRunning={cloud:false,local:false};
function newRandomSeed(){return Math.floor(Math.random()*9007199254740990)+1}
const cfg=()=>STYLE_CONFIGS[currentStyle], pools=()=>cfg().pools, state=()=>stateByStyle[currentStyle], locks=()=>lockedByStyle[currentStyle];
const isMulti=k=>(cfg().multi||[]).includes(k);
function prepareStyle(id){if(!stateByStyle[id]){stateByStyle[id]={};lockedByStyle[id]={};const defaults=STYLE_CONFIGS[id].defaultSelections||{};Object.entries(STYLE_CONFIGS[id].pools).forEach(([k,a])=>{const z=a.find(x=>!x[1])||a[0];const label=defaults[k];const hit=label?a.find(x=>x[0]===label):null;stateByStyle[id][k]=(STYLE_CONFIGS[id].multi||[]).includes(k)?[hit||z]:(hit||z)})}}
function selectedItems(k){const v=state()[k];if(isMulti(k))return Array.isArray(v?.[0])?v:(v?[v]:[]);return v?[v]:[]}function selected(k){return selectedItems(k)[0]||["无（不添加)",""]}function enabled(k){if(cfg().characterOnly.includes(k))return currentMode==='character';if(cfg().originalOnly.includes(k))return currentMode==='original';return true}function activeKeys(){return Object.keys(pools()).filter(enabled)}
function label(k){return cfg().labels[k]||({character_inspired:'选择角色',character:'身材 / 体型',body_modifier:'身材细节',tattoo_color:'纹样颜色',special_prompt:'额外细节',emotion:'情绪',expression:'表情',interaction:'视线 / 互动',background:'背景',scene:'场景',special_outfit:'特殊服装',seductive_pose:'诱惑姿势',special_pose:'特殊姿势',view_direction:'视线方向',fashion_extra:'额外配件'}[k]||k)}
function setNone(){activeKeys().forEach(k=>{const z=pools()[k].find(x=>!x[1])||pools()[k][0];state()[k]=isMulti(k)?[z]:z});render()}
function randomAll(){activeKeys().forEach(k=>{if(locks()[k])return;const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||pools()[k][0];state()[k]=isMulti(k)?[v]:v});render()}
function buildCorePrompt(){const parts=[cfg().prefix,cfg().head];activeKeys().forEach(k=>selectedItems(k).forEach(v=>{if(v[1])parts.push(v[1])}));parts.push(cfg().style);return parts.filter(Boolean).join(',\n\n')}
function buildPrompt(){return[cfg().trigger,buildCorePrompt()].filter(Boolean).join(',\n\n')}
function buildAll(){return buildPrompt()+'\n\nNegative prompt:\n'+cfg().negative}
function drawerFor(k){return DRAWERS.find(d=>d.keys.includes(k))?.id}
function render(){prepareStyle(currentStyle);document.querySelectorAll('[data-style]').forEach(b=>b.classList.toggle('active',b.dataset.style===currentStyle));document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===currentMode));document.getElementById('sketchProcessRow').style.display=currentStyle==='sketch'?'block':'none';const root=document.getElementById('drawers');root.innerHTML='';DRAWERS.forEach(d=>{const keys=d.keys.filter(k=>pools()[k]&&enabled(k));if(!keys.length)return;const box=document.createElement('section');box.className='drawer'+(openDrawers.has(d.id)?' open':'');box.dataset.drawer=d.id;box.innerHTML=`<button class="drawer-head"><span>${d.title}</span><span>⌄</span></button><div class="drawer-body"></div>`;box.querySelector('.drawer-head').onclick=()=>{openDrawers.has(d.id)?openDrawers.delete(d.id):openDrawers.add(d.id);render()};const body=box.querySelector('.drawer-body');keys.forEach(k=>{const chosen=new Set(selectedItems(k).map(x=>x[1]));const card=document.createElement('article');card.className='item';card.innerHTML=`<div class="item-head"><span class="item-name">${label(k)}</span><span class="item-actions"><button class="reroll">↻</button><button class="lock">${locks()[k]?'🔒':'🔓'}</button></span></div><div class="picker-wrap"><select class="picker" ${isMulti(k)?'multiple size="4"':''}>${pools()[k].map((x,i)=>`<option value="${i}" ${chosen.has(x[1])?'selected':''}>${x[0]}</option>`).join('')}</select></div>`;card.querySelector('.reroll').onclick=()=>{const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||selected(k);state()[k]=isMulti(k)?[v]:v;render()};card.querySelector('.lock').onclick=()=>{locks()[k]=!locks()[k];render()};card.querySelector('select').onchange=e=>{if(isMulti(k)){const v=[...e.target.selectedOptions].map(o=>pools()[k][+o.value]);state()[k]=v.length?v:[pools()[k].find(x=>!x[1])||pools()[k][0]]}else state()[k]=pools()[k][+e.target.value];render()};body.appendChild(card)});root.appendChild(box)});document.getElementById('promptText').value=buildAll()}
function snapshotSelections(){return{style:currentStyle,mode:currentMode,state:JSON.parse(JSON.stringify(state())),locked:JSON.parse(JSON.stringify(locks())),width:+genW.value,height:+genH.value,batch:+genBatch.value,hd:+genHd.value,sequence_mode:currentStyle==='sketch'?sketchProcess.value:'off',prompt_mode:promptMode.value,manual_positive:manualPositive.value,manual_negative:manualNegative.value,seed:+genSeed.value,seed_mode:seedMode.value}}
function applySnapshot(snapshot){if(!snapshot?.state)return;currentStyle=snapshot.style||'cold';currentMode=snapshot.mode||'original';prepareStyle(currentStyle);stateByStyle[currentStyle]={};Object.keys(pools()).forEach(k=>{const old=snapshot.state[k];const vals=isMulti(k)?(Array.isArray(old?.[0])?old:(old?[old]:[])):(old?[old]:[]);const hit=vals.map(v=>pools()[k].find(x=>v&&(x[1]===v[1]||x[0]===v[0]))).filter(Boolean);const z=pools()[k].find(x=>!x[1])||pools()[k][0];stateByStyle[currentStyle][k]=isMulti(k)?(hit.length?hit:[z]):(hit[0]||z)});lockedByStyle[currentStyle]=snapshot.locked||{};genW.value=snapshot.width||768;genH.value=snapshot.height||1024;genBatch.value=snapshot.batch||1;genHd.value=snapshot.hd||0;sketchProcess.value=snapshot.sequence_mode==='sketch3'?'3':(snapshot.sequence_mode==='sketch4'?'4':'off');promptMode.value=snapshot.prompt_mode||'options';manualPositive.value=snapshot.manual_positive||'';manualNegative.value=snapshot.manual_negative||'';genSeed.value=snapshot.seed||newRandomSeed();seedMode.value=snapshot.seed_mode||'fixed';openDrawers=new Set(Object.keys(state()).filter(k=>selectedItems(k).some(x=>x[1])).map(drawerFor).filter(Boolean));updatePromptModeUI();updateBatchSemantics();render();window.scrollTo({top:0,behavior:'smooth'})}
function updatePromptModeUI(){manualPromptPanel.style.display=promptMode.value==='manual'?'block':'none';document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.checked=x.value===promptMode.value)}
function updateBatchSemantics(){const staged=currentStyle==='sketch'&&sketchProcess.value!=='off';genBatch.disabled=staged;if(staged)genBatch.value=1;batchNote.textContent=''}
function addResult(j,container){container.innerHTML='';(j.images||[]).forEach((im,i)=>{const w=document.createElement('div');w.className='job';w.innerHTML=`${im.stage_label?`<b>${im.stage_label}</b>`:''}<div class="note">${j.generation_backend==='local'?'本地':'云端'} · 种子：${j.seed??j.sequence_seed??'未知'} · ${j.prompt_mode==='manual'?'手动Prompt':'选项组合'}</div><img src="${im.preview_url||im.url}"><button class="dl fav">♥ 收藏图片、提示词和种子</button><a class="dl" target="_blank" href="${im.url}">⬇ 下载原图</a>`;w.querySelector('.fav').onclick=async e=>{e.target.disabled=true;e.target.textContent='收藏中…';try{await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.id,image_index:i})});e.target.textContent='✓ 已收藏'}catch(x){e.target.disabled=false;e.target.textContent='收藏失败：'+x.message}};container.appendChild(w)})}
async function generate(backend){if(genRunning[backend])return;genRunning[backend]=true;const button=backend==='local'?genLocalBtn:genCloudBtn;const status=backend==='local'?genLocalStatus:genCloudStatus;const result=backend==='local'?genLocalResult:genCloudResult;button.disabled=true;status.textContent='正在提交…';result.innerHTML='';try{const sequence_mode=currentStyle==='sketch'?(sketchProcess.value==='3'?'sketch3':(sketchProcess.value==='4'?'sketch4':'off')):'off';if(seedMode.value==='random')genSeed.value=newRandomSeed();const seed=+genSeed.value;const positive=promptMode.value==='manual'?manualPositive.value.trim():buildCorePrompt();const negative=promptMode.value==='manual'?manualNegative.value.trim():cfg().negative;if(!positive)throw new Error('正向提示词不能为空');const body={workflow:'anima02',prompt:positive,negative_prompt:negative,prompt_mode:promptMode.value,width:+genW.value,height:+genH.value,batch:+genBatch.value,hd:+genHd.value,seed:seed,seed_mode:seedMode.value,style_id:currentStyle,mode:currentMode,sequence_mode,generation_backend:backend,selection_snapshot:{...snapshotSelections(),generation_backend:backend}};const r=await api('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});while(1){await new Promise(x=>setTimeout(x,3000));const j=await api('/api/job/'+r.job_id);const stage=(j.stage_status||[]).find(x=>x.status==='RUNNING');status.textContent=(stage?.stage_label||j.provider_status||j.status)+' '+(j.progress_pct||0)+'%';if(j.status==='done'){status.textContent='✓ 完成（'+j.elapsed+'秒，种子 '+j.seed+'）';addResult(j,result);break}if(j.status==='error')throw new Error(j.error||'生成失败')}}catch(e){status.textContent='✗ '+e.message}finally{genRunning[backend]=false;button.disabled=false}}
async function history(){histList.innerHTML='加载中…';const a=await api('/api/jobs');histList.innerHTML='';a.slice(0,10).forEach(j=>{const d=document.createElement('div');d.className='job';d.innerHTML=`<b>${STYLE_CONFIGS[j.style_id]?.short||'历史'} · ${j.generation_backend==='local'?'本地':'云端'} · ${j.mode==='character'?'角色':'原创'}</b><div class="note">${j.status} · ${j.width}×${j.height} · ${j.batch}张 · 种子 ${j.seed??j.sequence_seed??'未知'} · ${j.elapsed||''}秒</div><button class="dl">查看图片</button>`;d.querySelector('button').onclick=()=>addResult(j,d);histList.appendChild(d)})}
async function favorites(){favList.innerHTML='加载中…';const a=await api('/api/favorites');favList.innerHTML='';a.forEach(f=>{const d=document.createElement('div');d.className='job';d.innerHTML=`<div class="note">种子：${f.seed??f.selection_snapshot?.seed??'未知'} · ${f.prompt_mode==='manual'?'手动Prompt':'选项组合'}</div><img src="${f.preview_url||f.image_url}"><button class="dl apply">↺ 套用提示词、选项和种子</button><button class="dl copy">复制完整提示词</button><a class="dl" href="${f.image_url}" target="_blank">⬇ 下载收藏原图</a>`;d.querySelector('.apply').onclick=()=>{applySnapshot(f.selection_snapshot);favOverlay.classList.remove('open')};d.querySelector('.copy').onclick=()=>navigator.clipboard.writeText(f.prompt||'');favList.appendChild(d)})}
document.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>{currentStyle=b.dataset.style;currentMode=cfg().defaultMode||'original';prepareStyle(currentStyle);openDrawers.clear();updateBatchSemantics();render()});document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{currentMode=b.dataset.mode;openDrawers.clear();render()});document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.onchange=()=>{promptMode.value=x.value;updatePromptModeUI()});seedMode.onchange=()=>{if(seedMode.value==='random')genSeed.value=newRandomSeed()};sketchProcess.onchange=updateBatchSemantics;document.getElementById('randomAll').onclick=randomAll;document.getElementById('clearAll').onclick=setNone;genCloudBtn.onclick=()=>generate('cloud');genLocalBtn.onclick=()=>generate('local');document.getElementById('copyPrompt').onclick=()=>navigator.clipboard.writeText(buildAll());document.getElementById('promptToggle').onclick=()=>promptPanel.classList.toggle('open');document.getElementById('histOpen').onclick=()=>{histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.classList.add('open');favorites()};document.querySelectorAll('.overlay .close').forEach(b=>b.onclick=()=>b.closest('.overlay').classList.remove('open'));genSeed.value=newRandomSeed();prepareStyle('sketch');updatePromptModeUI();updateBatchSemantics();render();</script></body></html>'''
html=html.replace('__DATA__',DATA).replace('__DRAWERS__',DRAWS)
for p in (STATIC/"promptgen.html",STATIC/"index.html"): p.write_text(html,encoding="utf-8")
print(json.dumps({k:{"pools":len(v["pools"]),"trigger":v["trigger"],"lora1":v["lora1"],"lora2":v["lora2"]} for k,v in profiles.items()},ensure_ascii=False,indent=2))
