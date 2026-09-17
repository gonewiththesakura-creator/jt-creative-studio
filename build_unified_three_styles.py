from pathlib import Path
import base64, copy, json, re, subprocess, tempfile, hashlib

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/"static"
SRC=ROOT/"sources"
SRC.mkdir(exist_ok=True)
WORKBENCH_GLASS_CSS=(SRC/"workbench_glass.css").read_text(encoding="utf8")
COLD_SRC=SRC/"cold_promptgen_source.html"
if not COLD_SRC.exists():
    COLD_SRC.write_bytes((STATIC/"promptgen.html").read_bytes())
GRAPHIC=SRC/"graphic_promptgen_source.html"
SKETCH=SRC/"sketch_promptgen_source.html"
HANMANGA_PROFILE=SRC/"hanmanga_profile.source.json"
RETRO_MANGA_PROFILE=SRC/"retro_manga_luxury_profile.json"
STYLE221_PROFILE=SRC/"style221_profile.json"
STYLE222_PROFILE=SRC/"style222_profile.json"

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
hanmanga_source=json.loads(HANMANGA_PROFILE.read_text(encoding="utf-8"))
hanmanga=copy.deepcopy(hanmanga_source)
retro_source=json.loads(RETRO_MANGA_PROFILE.read_text(encoding="utf-8"))
style221_source=json.loads(STYLE221_PROFILE.read_text(encoding="utf-8"))
style222_source=json.loads(STYLE222_PROFILE.read_text(encoding="utf-8"))
# The supplied page intentionally used the sketch backend as a temporary shim.
# Production metadata is trusted here and on the server; the browser never
# chooses LoRA filenames or trigger tokens.
hanmanga["trigger"]="jt_liulistyle_v1"
hanmanga["lora1"]="08_liuli_style_v1_step600.safetensors"
hanmanga["lora2"]="08_liuli_style_v1_step600.safetensors"
hanmanga.pop("backendStyleId",None)
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

# New styles inherit the complete union first, then add their own vocabulary.
# This makes "only add, never remove" mechanically true for every category.
retro_pools={k:[list(x) for x in rows] for k,rows in UNION_POOLS.items()}
append_exact_pairs(retro_pools,retro_source["additions"])
retro=copy.deepcopy(retro_source)
retro.pop("additions",None)
retro["pools"]=retro_pools
retro["labels"]={**copy.deepcopy(sketch["LABELS"]),**retro.get("labels",{})}
def build_additive_profile(source):
    pools={k:[list(x) for x in rows] for k,rows in UNION_POOLS.items()}
    append_exact_pairs(pools,source.get("additions",{}))
    profile=copy.deepcopy(source)
    profile.pop("additions",None)
    profile["pools"]=pools
    profile["labels"]={**copy.deepcopy(sketch["LABELS"]),**profile.get("labels",{})}
    return profile
style221=build_additive_profile(style221_source)
style222=build_additive_profile(style222_source)

SOURCE_COUNTS={sid:{k:len(v) for k,v in pools.items()} for sid,pools in SOURCE_POOLS.items()}
manifest={
 "sources":{"cold":COLD_SRC.name,"sketch":SKETCH.name,"graphic":GRAPHIC.name},
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
  "styleVariantDefault":"character_bound",
  "styleVariants":[
   {"id":"character_bound","label":"人物+画风","note":"现有双 LoRA 兼容分支"},
   {"id":"style_only","label":"仅画风候选","note":"低角色泄漏候选，不加载旧版 04 画风 LoRA；不代表已完全去除人物偏置"}
  ],
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
 "original_sketch":{
  "name":"原始铅绘·原始选项池","short":"原始铅绘","trigger":"jt_style1_v1",
  "lora1":"01_style1_step900.safetensors","lora2":"01_style1_step900.safetensors",
  "prefix":sketch["DEFAULT_PREFIX"],"head":sketch["FIXED_HEAD"],"style":sketch["FIXED_STYLE"],"negative":sketch["NEGATIVE"],
  "pools":copy.deepcopy(RAW_SOURCE_POOLS["sketch"]),"labels":copy.deepcopy(sketch["LABELS"]),
  "originalOnly":[],"characterOnly":["character_inspired"],"multi":[],"defaultMode":"original",
 },
 "graphic":{
  "name":"古风·东方平面插画风","short":"古风","trigger":"jt_style2_v1",
  "lora1":"02_style2_step900.safetensors","lora2":"02_style2_step900.safetensors",
  "prefix":graphic["DEFAULT_PREFIX"],"head":graphic["FIXED_HEAD"],"style":graphic["FIXED_STYLE"],"negative":graphic["NEGATIVE"],"pools":graphic["POOLS"],"labels":graphic["LABELS"],
  "originalOnly":[],"characterOnly":["character_inspired"],
  "multi":["special_outfit","body_modifier","special_prompt","seductive_pose","special_pose"],
 },
 "original_graphic":{
  "name":"原始古风·原始选项池","short":"原始古风","trigger":"jt_style2_v1",
  "lora1":"02_style2_step900.safetensors","lora2":"02_style2_step900.safetensors",
  "prefix":graphic["DEFAULT_PREFIX"],"head":graphic["FIXED_HEAD"],"style":graphic["FIXED_STYLE"],"negative":graphic["NEGATIVE"],
  "pools":copy.deepcopy(RAW_SOURCE_POOLS["graphic"]),"labels":copy.deepcopy(graphic["LABELS"]),
  "originalOnly":[],"characterOnly":["character_inspired"],"multi":[],"defaultMode":"original",
 },
 "hanmanga":hanmanga,
 "nff":{
  "name":"NFF·半写实动漫画风","short":"NFF","trigger":"jt_nffstyle_v1",
  "lora1":"06_nff_style_v1_step2000.safetensors","lora2":"06_nff_style_v1_step2000.safetensors",
  "prefix":sketch["DEFAULT_PREFIX"],"head":sketch["FIXED_HEAD"],
  "style":"adult semi-realistic anime illustration, refined expressive face, polished delicate linework, soft cinematic light and shadow, nuanced skin and fabric rendering, mature elegant proportions, coherent detailed hands, premium character key visual, tasteful intimate atmosphere",
  "negative":"worst quality, low quality, lowres, blurry, child, underage, loli, young-looking character, chibi child proportions, bad anatomy, bad hands, malformed hands, extra fingers, missing fingers, fused fingers, extra limbs, distorted face, asymmetrical eyes, waxy skin, plastic skin, harsh overprocessing, photorealistic photography, 3d, cgi, text, watermark, logo, signature",
  "pools":copy.deepcopy(sketch["POOLS"]),"labels":copy.deepcopy(sketch["LABELS"]),
  "originalOnly":[],"characterOnly":["character_inspired"],
  "multi":["special_outfit","body_modifier","special_prompt","seductive_pose","special_pose"],
 },
 "retro_manga_luxury":retro,
 "style221":style221,
 "style222":style222,
}
STYLE_PREVIEWS={
 "cold":"style-cold.webp","sketch":"style-sketch.webp","original_sketch":"style-original-sketch.webp",
 "graphic":"style-graphic.webp","original_graphic":"style-original-graphic.webp",
 "hanmanga":"style-hanmanga.webp","nff":"style-nff.webp",
 "retro_manga_luxury":"style-retro-manga-luxury.webp",
}
def preview_url(filename):
    path=ROOT/"static"/"previews"/filename
    return "/static/previews/"+filename+"?v="+hashlib.sha256(path.read_bytes()).hexdigest()[:12]
def preview_data_uri(filename):
    path=ROOT/"static"/"previews"/filename
    return "data:image/webp;base64,"+base64.b64encode(path.read_bytes()).decode("ascii")
for style_id,filename in STYLE_PREVIEWS.items():
    profiles[style_id]["preview"]=preview_url(filename)
    profiles[style_id]["preview_thumb"]=preview_data_uri(filename.replace(".webp",".thumb.webp"))
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
for style_id,p in profiles.items():
    if not style_id.startswith("original_"):
        normalize_profile(p)

DRAWERS=[
 {"id":"character","title":"角色","keys":["character_inspired","hair","eyes","emotion","expression","interaction","species"]},
 {"id":"body","title":"身体","keys":["character","body_modifier","tattoo_color","special_prompt"]},
 {"id":"outfit","title":"服装","keys":["outfit","top","outerwear","bottoms","legwear","footwear","accessory","fashion_extra","special_outfit"]},
 {"id":"pose","title":"姿势与镜头","keys":["pose","seductive_pose","special_pose","view_direction","camera"]},
 {"id":"background","title":"背景与剧情","keys":["prop","holiday","story","theme","scene","background","accent"]},
]
browser_profiles=copy.deepcopy(profiles)
for browser_profile in browser_profiles.values():
    for private_key in ("lora1","lora2","strengths"):
        browser_profile.pop(private_key,None)
DATA=json.dumps(browser_profiles,ensure_ascii=False,separators=(",",":"))
STYLE_DATA_BYTES=DATA.encode("utf-8")
STYLE_DATA_HASH=hashlib.sha256(STYLE_DATA_BYTES).hexdigest()[:12]
STYLE_DATA_NAME=f"style-configs.{STYLE_DATA_HASH}.json"
STYLE_CONFIG_URL=f"/static/{STYLE_DATA_NAME}"
STYLE_BOOT={
    style_id:{key:profile.get(key) for key in ("short","preview","preview_thumb","defaultMode")}
    for style_id,profile in browser_profiles.items()
}
BOOT_DATA=json.dumps(STYLE_BOOT,ensure_ascii=False,separators=(",",":"))
DRAWS=json.dumps(DRAWERS,ensure_ascii=False,separators=(",",":"))
WORKBENCH_CSS=r'''
:root{--brand:#536cff;--brand-dark:#4057e8;--canvas:#f6f7fb;--surface:#ffffff;--surface-soft:#fafbfe;--text:#20222a;--muted:#8b8f9a;--border:#e7e9f0;--success:#2f8f74;--shadow:0 14px 40px rgba(36,42,68,.08)}
html{background:var(--canvas)}body{background:var(--canvas);color:var(--text);height:100vh;overflow:hidden}.app-shell{height:100vh;overflow:hidden}.topbar{height:68px;display:flex;align-items:center;gap:28px;padding:0 28px;background:rgba(255,255,255,.96);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:70;backdrop-filter:blur(14px)}.brand{display:flex;align-items:center;gap:10px;color:var(--text);font-weight:900;text-decoration:none;white-space:nowrap}.brand-mark{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;background:var(--brand);color:#fff;font-size:13px;letter-spacing:.04em;box-shadow:0 8px 18px rgba(83,108,255,.24)}.topnav{display:flex;align-items:center;gap:6px;min-width:0;overflow-x:auto;scrollbar-width:none}.topnav-link{height:38px;display:flex;align-items:center;padding:0 13px;border-radius:10px;color:#707482;text-decoration:none;font-size:13px;font-weight:760;white-space:nowrap}.topnav-link:hover{background:#f2f4fa;color:var(--text)}.topnav-link.active{background:#eef1ff;color:var(--brand)}.topbar-tools{margin-left:auto;display:flex;align-items:center;gap:8px}.topbar-action{height:38px;border:1px solid var(--border);border-radius:11px;background:#fff;padding:0 13px;color:#565b69;font-size:13px;font-weight:760;cursor:pointer}.topbar-action:hover{border-color:#cfd4e5;background:#fafbfe}.connection-dot{width:8px;height:8px;border-radius:50%;background:#43b891;box-shadow:0 0 0 4px rgba(67,184,145,.12)}
.studio-grid{display:grid;grid-template-columns:minmax(360px,460px) minmax(0,1fr);gap:22px;max-width:1540px;height:calc(100vh - 68px);margin:0 auto;padding:22px 24px 20px;min-height:0}.creation-pane,.preview-pane{min-width:0;min-height:0}.creation-pane{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--border);border-radius:22px;box-shadow:var(--shadow);overflow:hidden}.creation-scroll{flex:1;min-height:0;overflow:auto;padding:22px;scrollbar-width:thin}.creation-footer{padding:12px 22px 18px;border-top:1px solid var(--border);background:#fff}.pane-heading{display:flex;align-items:end;justify-content:space-between;gap:12px;margin-bottom:18px}.pane-heading h1{font-size:22px;line-height:1.2;margin:0}.eyebrow{font-size:10px;letter-spacing:.14em;color:var(--brand);font-weight:900}.section-label{display:block;margin:15px 2px 8px;color:#6e7380;font-size:11px;font-weight:850;letter-spacing:.04em}.switch{margin:0 0 10px;padding:4px;background:#f5f6fa;border:0;border-radius:13px;box-shadow:none;gap:4px}#styleSwitch{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}.switch button,.switch .original-link{flex:1;justify-content:center;text-align:center;min-height:42px;border:0;border-radius:10px;background:transparent;color:#6f7480;padding:10px;font-size:13px}.switch button.active{background:#fff;color:var(--text);box-shadow:0 3px 12px rgba(35,40,60,.08)}.switch .original-link{display:none}.actions{margin:10px 0;gap:8px}.actions .primary{min-height:44px;padding:11px 12px;border-radius:11px;background:#f3f5fa;color:#5e6472;font-size:12px;box-shadow:none}.drawer{border:1px solid var(--border);border-radius:14px;box-shadow:none;margin:8px 0;background:#fff}.drawer-head{padding:14px 15px;color:#3c414d;font-size:13px}.drawer.open .drawer-head{color:var(--brand);background:#fafbff}.drawer-body{padding:0 10px 10px}.drawer.open .drawer-body{gap:8px}.item{border:0;border-radius:10px;background:var(--surface-soft);padding:10px}.item-name{font-size:11px;color:#747988}.item-actions button{width:29px;height:29px;border-radius:8px;background:#edf0f7;color:#697082}.picker{min-height:40px;border-color:#e1e4ed;border-radius:9px;padding:8px 10px;color:#343844}.settings{padding:12px;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;background:var(--surface-soft);border:1px solid var(--border);border-radius:14px;box-shadow:none}.settings label{font-size:10px;color:#7d8290}.settings input,.settings select{padding:9px 10px;border-color:#e0e3eb;background:#fff}.prompt{border:1px solid var(--border);border-radius:14px;box-shadow:none;background:#fff}.prompt-head{padding:12px 14px}.prompt textarea{min-height:150px;font-size:11px;background:#fbfcfe}.prompt.open .prompt-body{display:block}.prompt-actions-inline{display:flex;gap:5px}.dl{border-radius:9px;background:#f0f2f8;color:#5d6474}.generation-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:12px}.primary.generate{min-height:48px;border-radius:12px;background:var(--brand);box-shadow:0 9px 20px rgba(83,108,255,.22)}.primary.generate:hover{background:var(--brand-dark)}.primary.generate.local{background:#fff;color:#426d63;border:1px solid #cfe2dc;box-shadow:none}.primary.generate.local:hover{background:#f1f8f6}.primary.generate.api{background:#fff;color:#8a5a22;border:1px solid #e4cda8;box-shadow:none}.primary.generate.api:hover{background:#fff8ee}.api-settings{margin-top:9px;border:1px solid var(--border);border-radius:12px;background:#fff}.api-settings summary{min-height:44px;display:flex;align-items:center;padding:0 12px;cursor:pointer;color:#6e7380;font-size:11px;font-weight:850}.api-settings .settings{border:0;border-top:1px solid var(--border);border-radius:0;background:#fff}.api-note{padding:0 12px 12px;color:var(--muted);font-size:11px;line-height:1.6}
.preview-pane{display:flex;flex-direction:column;gap:12px}.preview-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:2px 4px}.preview-header h2{font-size:18px;margin:0}.result-tabs{display:flex;gap:4px;padding:4px;background:#eceef4;border-radius:11px}.result-tab{border:0;background:transparent;color:#747986;border-radius:8px;padding:7px 12px;font-size:12px;font-weight:800;cursor:pointer}.result-tab.active{background:#fff;color:var(--text);box-shadow:0 2px 8px rgba(40,44,64,.08)}.preview-stage{position:relative;flex:1;min-height:620px;border:1px solid var(--border);border-radius:22px;background:linear-gradient(145deg,#fbfbfd,#f0f2f7);box-shadow:var(--shadow);overflow:hidden;padding:18px}.preview-stage.has-results{overflow:auto}.preview-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#a1a5af;pointer-events:none;padding:18px}.preview-empty.hidden{display:none}.preview-example{display:block;width:100%;height:100%;max-width:100%;max-height:calc(100vh - 150px);object-fit:contain;border-radius:16px}.preview-caption{position:absolute;left:30px;bottom:28px;padding:7px 11px;border-radius:9px;background:rgba(255,255,255,.9);color:#555b68;font-size:12px;font-weight:800;box-shadow:0 5px 18px rgba(25,30,48,.12)}.result-panel{display:none;min-height:100%}.result-panel.active{display:block}.status{margin:0 0 10px;color:#666c79}.result{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.job{margin:0;border:1px solid var(--border);box-shadow:none}.result img,.job img{max-height:720px;background:#f3f4f7}
.media-gallery{display:grid;grid-template-rows:minmax(320px,1fr) auto;gap:10px;min-height:100%}.gallery-main{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:320px}.gallery-main img{display:block;max-width:100%;max-height:62vh;object-fit:contain;border-radius:14px;background:#f3f4f7}.gallery-meta{width:100%;margin-bottom:8px}.gallery-actions{width:100%;display:grid;grid-template-columns:1fr 1fr;gap:8px}.gallery-strip{display:grid;grid-template-columns:44px minmax(0,1fr) 44px;gap:8px;align-items:center}.gallery-thumbs{display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;padding:2px}.gallery-thumb{flex:0 0 72px;height:68px;padding:3px;border:1px solid var(--border);border-radius:9px;background:#fff;scroll-snap-align:center}.gallery-thumb.active{border:2px solid var(--brand)}.gallery-thumb img{width:100%;height:100%;object-fit:cover;border-radius:6px}.gallery-prev,.gallery-next{min-height:44px;border:1px solid var(--border);border-radius:9px;background:#fff}
.api-drawer-open{width:100%;min-height:40px;margin-top:8px;border:1px solid #e4cda8;border-radius:10px;background:#fff8ee;color:#8a5a22;font-weight:850}.api-drawer-backdrop{position:fixed;inset:0;z-index:108;background:rgba(24,27,36,.28);opacity:0;pointer-events:none;transition:opacity .2s}.api-drawer{position:fixed;z-index:109;top:0;right:0;width:min(390px,calc(100vw - 20px));height:100vh;padding:22px;background:#fff;box-shadow:-18px 0 48px rgba(24,27,36,.18);transform:translateX(105%);transition:transform .24s;overflow-y:auto}.api-drawer.open{transform:none}.api-drawer.open+.api-drawer-backdrop{opacity:1;pointer-events:auto}.api-drawer-head{display:flex;align-items:center;justify-content:space-between}.api-drawer-head h2{margin:3px 0 0}.api-drawer-head button{width:44px;height:44px;border:0;border-radius:10px;background:#f1f3f8;font-size:22px}.api-drawer .settings{grid-template-columns:1fr;margin:16px 0}.api-ratio-field{min-width:0;margin:0;padding:0;border:0}.api-ratio-field legend{margin-bottom:7px;color:#7d8290;font-size:10px;font-weight:800}.api-ratio-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}.api-ratio-option{position:relative;height:58px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;border:1px solid #e0e3eb;border-radius:7px;background:#fff;color:#777c88;font-size:10px;font-weight:800;cursor:pointer}.api-ratio-option input{position:absolute;opacity:0;pointer-events:none}.api-ratio-option:has(input:checked){border-color:#8a5a22;background:#fff8ee;color:#704719;box-shadow:inset 0 0 0 1px #8a5a22}.api-ratio-shape{display:block;border:1.5px solid currentColor;border-radius:1px}.api-ratio-shape.square{width:18px;height:18px}.api-ratio-shape.portrait{width:13px;height:19px}.api-ratio-shape.landscape{width:20px;height:14px}.api-ratio-shape.tall{width:11px;height:20px}.api-ratio-shape.wide{width:21px;height:12px}.api-size-note{font-size:11px;color:var(--muted);line-height:1.6}.api-drawer .primary{width:100%}.library-overlay{display:none;position:fixed;inset:0;z-index:100;background:rgba(25,28,38,.28);padding:74px 20px 20px}.library-overlay.open{display:flex;justify-content:flex-end}.library-panel{width:min(460px,100%);height:100%;display:flex;flex-direction:column;overflow:hidden;isolation:isolate;background:#fff;border-radius:20px;box-shadow:0 22px 60px rgba(25,29,46,.2)}.library-header{position:relative;z-index:2;flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;padding:18px;border-bottom:1px solid var(--border);background:#fff}.library-header h2{margin:0;font-size:18px}.library-scroll{position:relative;z-index:1;flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:0 18px 18px;background:#fff}.library-scroll .job{overflow:hidden}.library-scroll .job img{position:static;display:block;max-width:100%}.close{width:36px;height:36px;border-radius:10px;background:#f1f3f8}.note{font-size:11px;color:var(--muted)}
.liquid-button{--liquid-color:#536cff;--liquid-progress:0%;--liquid-level:calc(100% - var(--liquid-progress));position:relative;isolation:isolate;overflow:hidden;contain:paint;border:1px solid transparent;background:#fff;color:#4057e8;box-shadow:inset 0 1px 0 rgba(255,255,255,.8);transition:border-color 180ms cubic-bezier(.25,1,.5,1),box-shadow 240ms cubic-bezier(.25,1,.5,1),transform 120ms cubic-bezier(.25,1,.5,1)}.primary.generate.liquid-button{background:#fff;color:#4057e8}.primary.generate.liquid-button.local{background:#fff;color:#2f7866}.liquid-button:active{transform:translateY(1px)}.liquid-button.cloud{border-color:#aeb9ff}.liquid-button.local{--liquid-color:#3c9b82;color:#2f7866;border-color:#a3d0c5}.liquid-fill{position:absolute;z-index:1;inset:-1px;background:color-mix(in srgb,var(--liquid-color) 78%,#667085);transform:translate3d(0,var(--liquid-level),0);will-change:transform;pointer-events:none}.liquid-meniscus{position:absolute;left:-2%;right:-2%;top:-1px;height:2px;border-radius:50%;background:color-mix(in srgb,var(--liquid-color) 72%,white);box-shadow:none;animation:liquid-meniscus 7.2s cubic-bezier(.65,0,.35,1) infinite alternate}.liquid-specular{position:absolute;top:12%;left:-22%;width:42%;height:76%;background:linear-gradient(105deg,transparent,rgba(255,255,255,.2),transparent);filter:blur(2px);opacity:.18;animation:liquid-specular 8.4s cubic-bezier(.65,0,.35,1) infinite alternate}.liquid-label{position:absolute;z-index:3;inset:0;display:flex;align-items:center;justify-content:center;gap:8px;pointer-events:none}.liquid-label-base{color:inherit}.liquid-label-fill{color:#fff;clip-path:inset(var(--liquid-level) 0 0 0);text-shadow:0 1px 1px rgba(22,30,56,.2)}.liquid-button.is-loading{border-color:color-mix(in srgb,var(--liquid-color) 52%,white);box-shadow:inset 0 1px 0 rgba(255,255,255,.55)}@keyframes liquid-meniscus{from{transform:translate3d(-1.8%,0,0) scaleX(1.01)}to{transform:translate3d(1.8%,1px,0) scaleX(.985)}}@keyframes liquid-specular{from{transform:translate3d(-3%,0,0) rotate(-2deg)}to{transform:translate3d(10%,4%,0) rotate(3deg)}}
@media(max-width:1020px){.studio-grid{grid-template-columns:minmax(330px,410px) minmax(0,1fr);padding:16px}.topbar{padding:0 16px;gap:14px}.brand span:last-child{display:none}}
@media(max-width:820px){body{height:auto;overflow:auto}.app-shell{height:auto;overflow:visible}.topbar{height:auto;min-height:60px;flex-wrap:wrap;padding:10px 12px}.brand span:last-child{display:inline}.topnav{order:3;width:100%;overflow-x:auto;padding-bottom:2px}.topbar-tools{margin-left:auto}.topbar-action{min-width:44px;min-height:44px;padding:0 10px}.studio-grid{grid-template-columns:1fr;height:auto;padding:12px;min-height:auto}.creation-scroll{height:auto;overflow:visible;padding:16px}.creation-scroll{padding-bottom:calc(220px + env(safe-area-inset-bottom))}.creation-footer{position:fixed;left:12px;right:12px;bottom:calc(8px + env(safe-area-inset-bottom));z-index:88;padding:12px 16px 16px;border:1px solid var(--border);border-radius:16px;box-shadow:0 14px 40px rgba(29,35,60,.18);background:rgba(255,255,255,.96);backdrop-filter:blur(16px)}.drawer-head{min-height:48px}.item-actions button{width:44px;height:44px}.switch button,.switch label,.dl,.settings input,.settings select,.result-tab{min-height:44px}.switch label{display:flex;align-items:center;gap:6px;padding:8px}.preview-stage{min-height:460px}.generation-actions{grid-template-columns:1fr}.library-overlay{padding:62px 8px 8px}.library-panel{border-radius:16px}.result{grid-template-columns:1fr}}
@media(max-width:480px){.topbar-tools .connection-dot{display:none}.topbar-action{min-width:52px;padding:0 9px;font-size:11px}.generation-actions{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.primary.generate{font-size:11px}.settings{grid-template-columns:1fr 1fr}.preview-stage{min-height:390px;padding:10px}.result-tabs{width:100%}.result-tab{flex:1}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}.liquid-fill{will-change:auto}.liquid-meniscus,.liquid-specular{animation:none!important}}
.api-progress{--api-progress-color:#b7792e;margin:12px 0;padding:12px;border:1px solid #ead9bd;border-radius:8px;background:#fffaf2;color:#4f4234}.api-progress[hidden]{display:none}.api-progress-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:9px}.api-progress-head strong{min-width:0;font-size:12px}.api-progress-elapsed{flex:0 0 auto;color:#76695b;font-size:11px;font-variant-numeric:tabular-nums}.api-progress-track{--api-stage-width:18%;position:relative;height:8px;overflow:hidden;border-radius:4px;background:#eee8df}.api-progress-fill{position:absolute;inset:0 auto 0 0;width:var(--api-stage-width);overflow:hidden;border-radius:4px;background:var(--api-progress-color);transition:width .25s ease}.api-progress.is-running .api-progress-fill::after,.api-progress.is-recovering .api-progress-fill::after{content:"";position:absolute;top:0;bottom:0;left:0;width:24%;background:rgba(255,255,255,.55);animation:api-progress-scan 1.35s linear infinite}.api-progress-note{margin-top:8px;color:#76695b;font-size:11px;line-height:1.55}.api-progress.is-done{--api-progress-color:#2f8f74;border-color:#c9e3da;background:#f5fbf9}.api-progress.is-error{--api-progress-color:#c65353;border-color:#edcccc;background:#fff7f7}.api-progress.is-cancelled{--api-progress-color:#7b808b;border-color:#d9dce2;background:#f8f9fb}.api-progress.is-recovering{--api-progress-color:#607d9a;border-color:#d4dce5;background:#f7f9fc}@keyframes api-progress-scan{from{transform:translateX(-120%)}to{transform:translateX(420%)}}@media(prefers-reduced-motion:reduce){.api-progress-fill{transition:none}.api-progress-fill::after{animation:none!important}}
'''
WORKBENCH_CSS=re.sub(r'\.api-drawer-backdrop\{.*?\.api-drawer \.primary\{[^}]*\}','',WORKBENCH_CSS)
WORKBENCH_CSS=re.sub(r'\.creation-scroll\{padding-bottom:calc\(220px \+ env\(safe-area-inset-bottom\)\)\}\.creation-footer\{position:fixed;.*?backdrop-filter:blur\(16px\)\}','',WORKBENCH_CSS)
API_POPOVER_CSS=r'''
.creation-footer{position:relative}.api-popover-anchor{position:relative}.api-drawer-open{min-height:44px}.api-popover{position:absolute;z-index:90;inset-inline:0;bottom:calc(100% + 8px);display:block;max-height:var(--api-popover-max-height,min(70vh,680px));overflow:auto;padding:18px;background:#fff;border:1px solid var(--border);border-radius:14px;box-shadow:0 18px 48px rgba(24,27,36,.16);opacity:0;transform:translateY(12px);transition:opacity .2s ease,transform .2s ease}.api-popover[hidden]{display:none}.api-popover.open{opacity:1;transform:translateY(0)}.api-popover-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.api-popover-head h2{margin:3px 0 0}.api-popover-head button{width:44px;height:44px;border:0;border-radius:10px;background:#f1f3f8;font-size:22px}.api-popover .settings{grid-template-columns:1fr;margin:16px 0}.api-popover .primary{width:100%}.api-ratio-field{min-width:0;margin:0;padding:0;border:0}.api-ratio-field legend{margin-bottom:7px;color:#7d8290;font-size:10px;font-weight:800}.api-ratio-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}.api-ratio-option{position:relative;height:58px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;border:1px solid #e0e3eb;border-radius:7px;background:#fff;color:#777c88;font-size:10px;font-weight:800;cursor:pointer}.api-ratio-option input{position:absolute;opacity:0;pointer-events:none}.api-ratio-option:has(input:checked){border-color:#8a5a22;background:#fff8ee;color:#704719;box-shadow:inset 0 0 0 1px #8a5a22}.api-ratio-shape{display:block;border:1.5px solid currentColor;border-radius:1px}.api-ratio-shape.square{width:18px;height:18px}.api-ratio-shape.portrait{width:13px;height:19px}.api-ratio-shape.landscape{width:20px;height:14px}.api-ratio-shape.tall{width:11px;height:20px}.api-ratio-shape.wide{width:21px;height:12px}.api-size-note{font-size:11px;color:var(--muted);line-height:1.6}@media(max-width:820px){.creation-scroll{padding:14px}.creation-footer{position:static;left:auto;right:auto;bottom:auto;z-index:auto;margin:0;padding:12px 16px 16px;border:0;border-top:1px solid var(--border);border-radius:0;box-shadow:none;background:#fff;backdrop-filter:none}.api-popover{padding:16px}.settings input,.settings select{font-size:16px}}@media(prefers-reduced-motion:reduce){.api-popover{transition:none}}
'''
API_POPOVER_BOOT=r'''
const apiPopoverAnchor=apiDrawerOpen.closest('.api-popover-anchor');apiDrawerOpen.after(apiDrawer);function refreshApiPopoverBounds(){const anchorRect=apiPopoverAnchor.getBoundingClientRect(),paneRect=document.querySelector('.creation-pane').getBoundingClientRect();const visibleTop=Math.max(8,paneRect.top+8);apiDrawer.style.setProperty('--api-popover-max-height',Math.max(0,Math.floor(anchorRect.top-visibleTop-8))+'px')}const setApiPopover=open=>{if(open){apiDrawer.hidden=false;apiDrawer.inert=false;apiDrawer.setAttribute('aria-hidden','false');apiDrawerOpen.setAttribute('aria-expanded','true');refreshApiPopoverBounds();requestAnimationFrame(()=>{apiDrawer.classList.add('open');apiModel.focus({preventScroll:true})});return}apiDrawer.classList.remove('open');apiDrawer.inert=true;apiDrawer.setAttribute('aria-hidden','true');apiDrawerOpen.setAttribute('aria-expanded','false');setTimeout(()=>{if(!apiDrawer.classList.contains('open'))apiDrawer.hidden=true},200);apiDrawerOpen.focus({preventScroll:true})};apiDrawerOpen.onclick=()=>setApiPopover(apiDrawer.hidden);apiDrawerClose.onclick=()=>setApiPopover(false);addEventListener('keydown',event=>{if(event.key==='Escape'&&!apiDrawer.hidden)setApiPopover(false)});addEventListener('resize',refreshApiPopoverBounds);addEventListener('scroll',refreshApiPopoverBounds,{passive:true});document.addEventListener('pointerdown',event=>{if(!apiDrawer.hidden&&!apiDrawer.contains(event.target)&&!apiDrawerOpen.contains(event.target))setApiPopover(false)});
'''
html=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="canonical" href="/"><script>if(location.pathname==='/promptgen')history.replaceState(null,'','/'+location.search+location.hash)</script><title>JT 灵感工作台</title><style>
:root{--bg:#f4f7f8;--card:#fff;--ink:#2f3b40;--muted:#82949c;--line:#e1eaed;--accent:#769fb2;--accent2:#eaf3f6;--shadow:0 12px 34px rgba(67,89,99,.08)}*{box-sizing:border-box}body{margin:0;background:linear-gradient(#f9fbfc,var(--bg));font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink)}button,input,select{font:inherit}.wrap{width:min(1100px,calc(100% - 24px));margin:auto;padding:22px 0 80px}.hero h1{margin:0;font-size:clamp(28px,4vw,40px)}.panel,.drawer{background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}.switch{padding:14px;margin:12px 0;display:flex;gap:8px;flex-wrap:wrap}.switch button,.switch .original-link{border:1px solid var(--line);background:#fff;border-radius:13px;padding:10px 14px;color:#667c86;font-weight:800;cursor:pointer;text-decoration:none}.switch button.active{background:var(--accent);color:#fff;border-color:transparent}.switch .original-link{background:#f0f6f8;color:#557888}.note{width:100%;font-size:12px;color:var(--muted);line-height:1.6}.drawer{margin:10px 0;overflow:hidden}.drawer-head{width:100%;border:0;background:#fff;padding:16px 18px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;font-weight:850;color:#566c76}.drawer-body{display:none;padding:0 14px 14px}.drawer.open .drawer-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.item{border:1px solid var(--line);border-radius:15px;padding:12px;background:#fbfdfe}.item-head{display:flex;justify-content:space-between;align-items:center;gap:8px}.item-name{font-size:12px;color:#8b9da5;font-weight:800}.item-actions{display:flex;gap:5px}.item-actions button{border:0;border-radius:9px;width:31px;height:31px;background:#edf4f7;color:#668b9b;cursor:pointer}.picker-wrap{display:block;margin-top:9px}.picker{width:100%;border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff}.actions{display:flex;gap:10px;margin:14px 0}.primary{flex:1;border:0;border-radius:18px;padding:16px;background:linear-gradient(135deg,#86b3c6,#6f9eb2);color:#fff;font-weight:850;cursor:pointer}.settings{padding:15px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.settings label{font-size:11px;color:var(--muted);font-weight:800}.settings input,.settings select{width:100%;margin-top:5px;border:1px solid var(--line);border-radius:10px;padding:9px}.prompt{margin-top:14px;overflow:hidden}.prompt-head{padding:14px 16px;display:flex;justify-content:space-between;align-items:center}.prompt-body{display:none}.prompt.open .prompt-body{display:block}.prompt textarea{width:100%;min-height:300px;border:0;border-top:1px solid var(--line);padding:15px;font:12px/1.6 monospace}.result img,.job img{width:100%;max-height:640px;object-fit:contain;border-radius:12px;background:#f4f4f4}.dl{display:block;width:100%;border:0;text-align:center;margin-top:7px;padding:10px;border-radius:10px;background:#edf4f7;color:#5f8290;font-weight:750;text-decoration:none;cursor:pointer}.floating{position:fixed;right:14px;z-index:50;border:1px solid var(--line);border-radius:16px;padding:10px 13px;background:#fff;box-shadow:var(--shadow);cursor:pointer}.history{bottom:18px}.favorites{bottom:66px}.overlay{display:none;position:fixed;inset:0;z-index:80;background:rgba(244,247,248,.98);overflow:auto;padding:15px}.overlay.open{display:block}.overlay-inner{max-width:680px;margin:auto}.overlay-head{display:flex;justify-content:space-between;align-items:center}.job{border:1px solid var(--line);background:#fff;border-radius:15px;padding:12px;margin:10px 0}.close{border:0;background:none;font-size:25px;cursor:pointer}.status{font-size:13px;color:#607985;font-weight:750;margin:10px 0}@media(max-width:700px){.drawer.open .drawer-body{grid-template-columns:1fr}.settings{grid-template-columns:1fr 1fr}.wrap{padding-top:14px}.floating{position:static;display:inline-block;margin:8px 4px 0 0}.favorites,.history{bottom:auto;right:auto}}
__WORKBENCH_CSS__
</style></head><body><div class="app-shell">
<header class="topbar"><a class="brand" href="/"><span class="brand-mark">JT</span><span>JT 灵感工作台</span></a><nav class="topnav"><a class="topnav-link active" href="/">创作台</a><a class="topnav-link" href="/realism">真人化</a><a class="topnav-link" href="/video">视频</a></nav><div class="topbar-tools"><span class="connection-dot" title="服务在线"></span><button class="topbar-action" id="favOpen">♥ 收藏</button><button class="topbar-action" id="histOpen">⌛ 历史</button></div></header>
<main class="studio-grid">
<aside class="creation-pane"><div class="creation-scroll"><div class="pane-heading"><div><span class="eyebrow">AI CREATION</span><h1>创作设置</h1></div></div>
<span class="section-label">画风</span><section class="switch" id="styleSwitch"><button data-style="cold">冷脸萌</button><button data-style="sketch">铅绘</button><button data-style="original_sketch">原始铅绘</button><button data-style="graphic">古风</button><button data-style="original_graphic">原始古风</button><button data-style="hanmanga">古漫</button><button data-style="nff">NFF</button><button data-style="retro_manga_luxury">复古日漫</button><button data-style="style221">板绘</button><button data-style="style222">铜版</button></section>
<div id="coldVariantSwitch"><span class="section-label">冷脸萌分支</span><section class="switch"><button data-style-variant="character_bound">人物+画风</button><button data-style-variant="style_only">仅画风候选</button></section><div class="note" id="coldVariantNote">现有双 LoRA 兼容分支</div></div>
<span class="section-label">人物模式</span><section class="switch" id="modeSwitch"><button data-mode="original">原创人物</button><button data-mode="character">角色模式</button></section>
<div id="drawers"></div><div class="actions"><button class="primary" id="randomAll">随机选项</button><button class="primary" id="clearAll">全部清空</button></div>
<span class="section-label">提示词</span><section class="switch" id="promptModePanel"><label><input type="radio" name="promptModeRadio" value="options" checked> 选项组合</label><label><input type="radio" name="promptModeRadio" value="manual"> 手动提示词</label><select id="promptMode" style="display:none"><option value="options">选项组合</option><option value="manual">手动提示词</option></select></section><button class="dl" id="importGeneratedPrompt" type="button">导入并编辑</button>
<section class="prompt" id="manualPromptPanel" style="display:none"><div class="prompt-head"><b>正向提示词</b></div><textarea id="manualPositive" placeholder="描述你想生成的画面…"></textarea><div class="prompt-head"><b>负向提示词</b></div><textarea id="manualNegative" placeholder="输入不希望出现的内容…"></textarea></section>
<section class="prompt" id="promptPanel"><div class="prompt-head"><b>详细提示词</b><div class="prompt-actions-inline"><button class="dl" id="copyPrompt">复制</button><button class="dl" id="promptToggle">展开</button></div></div><div class="prompt-body"><textarea id="promptText"></textarea></div></section>
<span class="section-label">生成参数</span><section class="settings"><label>宽<input id="genW" type="number" value="768" min="256" max="2048" step="16"></label><label>高<input id="genH" type="number" value="1024" min="256" max="2048" step="16"></label><label>批量<input id="genBatch" type="number" value="1" min="1" max="4"><span id="batchNote" style="display:none"></span></label><label>高清<select id="genHd"><option value="0">关闭</option><option value="1">ClearReality 2×</option><option value="2">UltraSharp 2×</option></select></label><label>种子模式<select id="seedMode"><option value="random">每次随机</option><option value="fixed">固定</option></select></label><label>种子值<input id="genSeed" type="number" min="1" max="9007199254740991" step="1"></label></section>
</div><div class="creation-footer"><div class="generation-actions"><button class="primary generate liquid-button cloud" id="genCloudBtn"><span class="liquid-fill" aria-hidden="true"><span class="liquid-meniscus"></span><span class="liquid-specular"></span></span><span class="liquid-label liquid-label-base">☁ 云端</span><span class="liquid-label liquid-label-fill" aria-hidden="true">☁ 云端</span></button><button class="primary generate liquid-button local" id="genLocalBtn"><span class="liquid-fill" aria-hidden="true"><span class="liquid-meniscus"></span><span class="liquid-specular"></span></span><span class="liquid-label liquid-label-base">本地</span><span class="liquid-label liquid-label-fill" aria-hidden="true">本地</span></button></div><button class="api-drawer-open" id="apiDrawerOpen" type="button">API生图</button></div></aside>
<section class="preview-pane"><div class="preview-header"><h2>创作预览</h2><div class="result-tabs"><button class="result-tab active" data-result-tab="cloud">云端结果</button><button class="result-tab" data-result-tab="local">本地结果</button><button class="result-tab" data-result-tab="api">API结果</button></div></div><div class="preview-stage"><div class="preview-empty" id="previewEmpty"><img class="preview-example" id="stylePreview" alt="当前画风效果预览"><span class="preview-caption" id="stylePreviewCaption"></span></div><section class="result-panel active" data-result-panel="cloud"><div class="status" id="genCloudStatus"></div><div class="result" id="genCloudResult"></div></section><section class="result-panel" data-result-panel="local"><div class="status" id="genLocalStatus"></div><div class="result" id="genLocalResult"></div></section><section class="result-panel" data-result-panel="api"><div class="status" id="genApiStatus"></div><div class="result" id="genApiResult"></div></section></div></section>
</main>
<aside class="api-drawer" id="apiDrawer" aria-hidden="true"><div class="api-drawer-head"><div><span class="eyebrow">IMAGE API</span><h2>API专属生图</h2></div><button id="apiDrawerClose" type="button" aria-label="关闭API设置">×</button></div><p class="api-note">使用当前提示词生成。API每次生成1张，高清不适用，API结果不受Seed控制；质量是请求偏好，上游可能覆盖质量，结果会显示实际值。</p><section class="settings"><label>模型<select id="apiModel"><option value="gpt-image-2.5-flare" selected>GPT Image 2.5 Flare</option><option value="gpt-image-2.5-sunburst">GPT Image 2.5 Sunburst</option><option value="gpt-image-2">GPT Image 2</option></select></label><fieldset class="api-ratio-field"><legend>比例</legend><div class="api-ratio-grid"><label class="api-ratio-option"><input type="radio" name="apiRatio" value="1:1"><span class="api-ratio-shape square"></span><span>1:1</span></label><label class="api-ratio-option"><input type="radio" name="apiRatio" value="2:3"><span class="api-ratio-shape portrait"></span><span>2:3</span></label><label class="api-ratio-option"><input type="radio" name="apiRatio" value="3:2"><span class="api-ratio-shape landscape"></span><span>3:2</span></label><label class="api-ratio-option"><input type="radio" name="apiRatio" value="9:16" checked><span class="api-ratio-shape tall"></span><span>9:16</span></label><label class="api-ratio-option"><input type="radio" name="apiRatio" value="16:9"><span class="api-ratio-shape wide"></span><span>16:9</span></label></div></fieldset><label>质量<select id="apiQuality"></select></label><label>画布适配<select id="apiFit"><option value="cover">铺满裁切</option><option value="contain">完整留白</option></select></label><div class="api-size-note">只需选择构图比例；服务端会按对应画布生成并校正最终图片。</div></section><button class="primary generate api" id="genApiBtn" type="button">使用当前提示词 · 开始API生图</button><div class="status" id="apiDrawerStatus"></div></aside><div class="api-drawer-backdrop" id="apiDrawerBackdrop"></div>
<div class="library-overlay" id="histOverlay"><div class="library-panel"><div class="library-header"><h2>历史记录</h2><button class="close">×</button></div><div class="library-scroll"><div id="histList"></div></div></div></div><div class="library-overlay" id="favOverlay"><div class="library-panel"><div class="library-header"><h2>我的收藏</h2><button class="close">×</button></div><div class="library-scroll"><div id="favList"></div></div></div></div>
</div>
<script>const STYLE_CONFIGS={};const STYLE_BOOT=__BOOT_DATA__;const STYLE_CONFIG_URL="__STYLE_CONFIG_URL__";const DRAWERS=__DRAWERS__;
const api=async(path,opt={})=>{const r=await fetch(path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok){const e=new Error(d.error||('HTTP '+r.status));e.status=r.status;e.code=d.code;e.data=d;throw e}return d};
const CREATOR_ROUTES=['/','/realism','/video'];
function scheduleRoutePrefetch(){const connection=navigator.connection||{};if(connection.saveData||/2g/.test(connection.effectiveType||''))return;const loaded=new Set();const load=href=>{if(!CREATOR_ROUTES.includes(href)||href===location.pathname||loaded.has(href))return;loaded.add(href);const link=document.createElement('link');link.rel='prefetch';link.as='document';link.href=href;document.head.appendChild(link)};document.querySelectorAll('.topnav-link').forEach(a=>{const href=a.getAttribute('href');a.addEventListener('pointerenter',()=>load(href),{once:true});a.addEventListener('focus',()=>load(href),{once:true})});const idle=()=>CREATOR_ROUTES.filter(x=>x!==location.pathname).slice(0,2).forEach(load);'requestIdleCallback'in window?requestIdleCallback(idle,{timeout:2500}):setTimeout(idle,1800)}
const activeJobKey=backend=>'jt-active-main-'+backend;function rememberActiveJob(backend,jobId){sessionStorage.setItem(activeJobKey(backend),jobId)}function forgetActiveJob(backend){sessionStorage.removeItem(activeJobKey(backend))}
const pendingCreatorKey=backend=>'jt-pending-main-'+backend;function creatorFingerprint(candidate){const normalized=JSON.parse(JSON.stringify(candidate));if(normalized.seed_mode==='random'){normalized.seed='random';if(normalized.selection_snapshot)normalized.selection_snapshot.seed='random'}return JSON.stringify(normalized)}function pendingCreatorRequest(backend,candidate){const now=Date.now(),fingerprint=creatorFingerprint(candidate);try{const saved=JSON.parse(localStorage.getItem(pendingCreatorKey(backend))||'null');if(saved?.id&&saved?.body&&saved.fingerprint===fingerprint&&now-saved.created<30*60*1000)return saved}catch{}const request={id:backend+'-'+now+'-'+Math.random().toString(36).slice(2),body:candidate,fingerprint,created:now};localStorage.setItem(pendingCreatorKey(backend),JSON.stringify(request));return request}function forgetPendingCreator(backend){localStorage.removeItem(pendingCreatorKey(backend))}
let currentStyle='sketch',currentMode='character',styleVariantByStyle={cold:'character_bound'},stateByStyle={},lockedByStyle={},openDrawers=new Set(),genRunning={cloud:false,local:false,api:false};
let styleDataReady=false,styleDataPromise=null;
function bootCfg(){return STYLE_BOOT[currentStyle]||STYLE_BOOT.sketch||Object.values(STYLE_BOOT)[0]||{}}
function renderBootPreview(){const boot=bootCfg(),url=boot.preview||'',thumb=boot.preview_thumb||url;document.querySelectorAll('[data-style]').forEach(button=>button.classList.toggle('active',button.dataset.style===currentStyle));if(!thumb){stylePreview.removeAttribute('src');stylePreview.alt='';stylePreviewCaption.textContent=(boot.short||'当前画风')+' · 暂无通过质量审核的预览';previewEmpty.classList.remove('hidden');return}stylePreview.src=thumb;stylePreview.alt=(boot.short||'当前画风')+'效果预览';stylePreviewCaption.textContent=(boot.short||'当前画风')+' · 效果预览';previewEmpty.classList.remove('hidden')}
function setStyleControlsReady(ready){document.querySelectorAll('[data-style],[data-style-variant],[data-mode],#randomAll,#clearAll,#copyPrompt,#genCloudBtn,#genLocalBtn,#genApiBtn,#importGeneratedPrompt').forEach(control=>control.disabled=!ready)}
function scheduleStylePreviewPreload(){const idle=()=>preloadStylePreviews();'requestIdleCallback'in window?requestIdleCallback(idle,{timeout:2500}):setTimeout(idle,1800)}
async function loadStyleConfigs(){if(styleDataReady)return STYLE_CONFIGS;if(styleDataPromise)return styleDataPromise;styleDataPromise=fetch(STYLE_CONFIG_URL,{cache:'force-cache'}).then(async response=>{if(!response.ok)throw new Error('HTTP '+response.status);const data=await response.json();if(!data||typeof data!=='object'||!Object.keys(STYLE_BOOT).every(id=>data[id]&&data[id].pools))throw new Error('样式数据格式无效');Object.assign(STYLE_CONFIGS,data);styleDataReady=true;setStyleControlsReady(true);if(!STYLE_CONFIGS[currentStyle])currentStyle='sketch';currentMode=cfg().defaultMode||currentMode;prepareStyle(currentStyle);updatePromptModeUI();updateBatchSemantics();render();scheduleStylePreviewPreload();return STYLE_CONFIGS}).catch(error=>{styleDataPromise=null;const text=document.createElement('span'),retry=document.createElement('button');text.textContent='样式数据加载失败。';retry.type='button';retry.className='dl';retry.textContent='重试加载';retry.onclick=()=>loadStyleConfigs().catch(()=>{});genCloudStatus.replaceChildren(text,retry);throw error});return styleDataPromise}
const API_QUALITIES={'gpt-image-2.5-flare':['low','medium','high','xhigh','max','auto'],'gpt-image-2.5-sunburst':['low','medium','high','xhigh','max','auto'],'gpt-image-2':['low','medium','high','auto']};
function defaultApiSettings(){const models=[...apiModel.options].map(option=>option.value),fits=[...apiFit.options].map(option=>option.value),ratios=[...document.querySelectorAll('input[name="apiRatio"]')].map(input=>input.value),api_model=apiModel.querySelector('option[selected]')?.value||models[0],api_fit=apiFit.querySelector('option[selected]')?.value||fits[0],api_ratio=document.querySelector('input[name="apiRatio"][checked]')?.value||ratios[0];return{api_model:API_QUALITIES[api_model]?api_model:(models.find(model=>API_QUALITIES[model])||''),api_quality:'low',api_fit:fits.includes(api_fit)?api_fit:(fits[0]||''),api_ratio:ratios.includes(api_ratio)?api_ratio:(ratios[0]||'')}}
function normalizeApiSettings(snapshot={}){const defaults=defaultApiSettings(),models=[...apiModel.options].map(option=>option.value),fits=[...apiFit.options].map(option=>option.value),ratios=[...document.querySelectorAll('input[name="apiRatio"]')].map(input=>input.value),api_model=models.includes(snapshot.api_model)&&API_QUALITIES[snapshot.api_model]?snapshot.api_model:defaults.api_model,qualities=API_QUALITIES[api_model]||[],api_quality=qualities.includes(snapshot.api_quality)?snapshot.api_quality:(qualities.includes(defaults.api_quality)?defaults.api_quality:qualities[0]);return{api_model,api_quality,api_fit:fits.includes(snapshot.api_fit)?snapshot.api_fit:defaults.api_fit,api_ratio:ratios.includes(snapshot.api_ratio)?snapshot.api_ratio:defaults.api_ratio}}
function selectedApiRatio(){return document.querySelector('input[name="apiRatio"]:checked')?.value||defaultApiSettings().api_ratio}
function updateApiQualityOptions(preferred=apiQuality.value||defaultApiSettings().api_quality){const allowed=API_QUALITIES[apiModel.value]||[],fallback=defaultApiSettings().api_quality;apiQuality.innerHTML=allowed.map(value=>`<option value="${value}">${value}</option>`).join('');apiQuality.value=allowed.includes(preferred)?preferred:(allowed.includes(fallback)?fallback:allowed[0])}
function backendUi(backend){return backend==='local'?{button:genLocalBtn,status:genLocalStatus,result:genLocalResult,label:'本地'}:backend==='api'?{button:genApiBtn,status:genApiStatus,result:genApiResult,label:'API'}:{button:genCloudBtn,status:genCloudStatus,result:genCloudResult,label:'云端'}}
function newRandomSeed(){return Math.floor(Math.random()*9007199254740990)+1}
const cfg=()=>STYLE_CONFIGS[currentStyle], pools=()=>cfg().pools, state=()=>stateByStyle[currentStyle], locks=()=>lockedByStyle[currentStyle];
function currentStyleVariant(){return currentStyle==='cold'?(styleVariantByStyle.cold||'character_bound'):'default'}
function setStyleVariant(value){if(currentStyle!=='cold')return;const valid=(cfg().styleVariants||[]).some(item=>item.id===value);styleVariantByStyle.cold=valid?value:(cfg().styleVariantDefault||'character_bound');updateColdVariantUI()}
function updateColdVariantUI(){const visible=currentStyle==='cold';coldVariantSwitch.style.display=visible?'block':'none';if(!visible)return;const value=currentStyleVariant(),meta=(cfg().styleVariants||[]).find(item=>item.id===value);coldVariantSwitch.querySelectorAll('[data-style-variant]').forEach(button=>button.classList.toggle('active',button.dataset.styleVariant===value));coldVariantNote.textContent=meta?.note||'低泄漏画风候选'}
const isMulti=k=>(cfg().multi||[]).includes(k);
function prepareStyle(id){if(!stateByStyle[id]){stateByStyle[id]={};lockedByStyle[id]={};const defaults=STYLE_CONFIGS[id].defaultSelections||{};Object.entries(STYLE_CONFIGS[id].pools).forEach(([k,a])=>{const z=a.find(x=>!x[1])||a[0];const label=defaults[k];const hit=label?a.find(x=>x[0]===label):null;stateByStyle[id][k]=(STYLE_CONFIGS[id].multi||[]).includes(k)?[hit||z]:(hit||z)})}}
function selectedItems(k){const v=state()[k];if(isMulti(k))return Array.isArray(v?.[0])?v:(v?[v]:[]);return v?[v]:[]}function selected(k){return selectedItems(k)[0]||["无（不添加)",""]}function enabled(k){if(cfg().characterOnly.includes(k))return currentMode==='character';if(cfg().originalOnly.includes(k))return currentMode==='original';return true}function activeKeys(){return Object.keys(pools()).filter(enabled)}
function label(k){return cfg().labels[k]||({character_inspired:'选择角色',character:'身材 / 体型',body_modifier:'身材细节',tattoo_color:'纹样颜色',special_prompt:'额外细节',emotion:'情绪',expression:'表情',interaction:'视线 / 互动',background:'背景',scene:'场景',special_outfit:'特殊服装',seductive_pose:'诱惑姿势',special_pose:'特殊姿势',view_direction:'视线方向',fashion_extra:'额外配件'}[k]||k)}
function setNone(){activeKeys().forEach(k=>{const z=pools()[k].find(x=>!x[1])||pools()[k][0];state()[k]=isMulti(k)?[z]:z});render()}
function randomAll(){const sparse=new Set(cfg().sparseRandomKeys||[]);if(sparse.size){activeKeys().forEach(k=>{if(locks()[k])return;const z=pools()[k].find(x=>!x[1])||pools()[k][0];state()[k]=isMulti(k)?[z]:z})}activeKeys().forEach(k=>{if(locks()[k]||(sparse.size&&!sparse.has(k)))return;const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||pools()[k][0];state()[k]=isMulti(k)?[v]:v});render()}
function buildCorePrompt(){const parts=[cfg().prefix,cfg().head,cfg().style];activeKeys().forEach(k=>selectedItems(k).forEach(v=>{if(v[1])parts.push(v[1])}));return parts.filter(Boolean).join(',\n\n')}
function buildPrompt(){return[cfg().trigger,buildCorePrompt()].filter(Boolean).join(',\n\n')}
function buildAll(){return buildPrompt()+'\n\nNegative prompt:\n'+cfg().negative}
function importGeneratedPromptToManual(){manualPositive.value=buildCorePrompt();manualNegative.value=cfg().negative;promptMode.value='manual';updatePromptModeUI();manualPositive.focus()}
function drawerFor(k){return DRAWERS.find(d=>d.keys.includes(k))?.id}
function setResultTab(backend){document.querySelectorAll('[data-result-tab]').forEach(x=>x.classList.toggle('active',x.dataset.resultTab===backend));document.querySelectorAll('[data-result-panel]').forEach(x=>x.classList.toggle('active',x.dataset.resultPanel===backend))}
function hasVisibleResults(){return Boolean(genCloudResult.children.length||genLocalResult.children.length||genApiResult.children.length)}
const stylePreviewCache=new Map();function preloadStyleImage(url){if(!url)return Promise.resolve('');if(stylePreviewCache.has(url))return stylePreviewCache.get(url);const promise=new Promise(resolve=>{const image=new Image();image.decoding='async';image.onload=()=>resolve(url);image.onerror=()=>resolve('');image.src=url});stylePreviewCache.set(url,promise);return promise}async function preloadStylePreviews(){if(!styleDataReady)return;await Promise.all(Object.values(STYLE_CONFIGS).map(style=>preloadStyleImage(style.preview_thumb||style.preview||'')))}async function loadFullStylePreview(id,url){const loaded=await preloadStyleImage(url);if(loaded&&currentStyle===id&&!hasVisibleResults())stylePreview.src=loaded}function updateStylePreview(){if(hasVisibleResults()){previewEmpty.classList.add('hidden');return}const id=currentStyle,url=cfg().preview||'',thumb=cfg().preview_thumb||url;if(!thumb){stylePreview.removeAttribute('src');stylePreview.alt='';stylePreviewCaption.textContent=cfg().short+' · 暂无通过质量审核的预览';previewEmpty.classList.remove('hidden');return}stylePreview.src=thumb;stylePreview.alt=cfg().short+'效果预览';stylePreviewCaption.textContent=cfg().short+' · 效果预览';previewEmpty.classList.remove('hidden');loadFullStylePreview(id,url)}
const LIQUID_POLL_INTERVAL=800,LIQUID_MIN_DURATION=260,LIQUID_MAX_DURATION=1800,LIQUID_REDUCED_MOTION=matchMedia('(prefers-reduced-motion: reduce)').matches,liquidMotionState=new WeakMap();
const API_PROGRESS_TERMINAL=new Set(['done','error','cancelled','canceled']);let apiProgressSnapshot=null,apiProgressStartedAt=0,apiProgressTimer=0,apiProgressOverride={};
function installApiProgress(){const markup='<div class="api-progress-head"><strong data-api-progress-stage>准备提交</strong><span class="api-progress-elapsed" data-api-progress-elapsed>已等待 0秒</span></div><div class="api-progress-track" data-api-progress-track role="progressbar" aria-valuemin="1" aria-valuemax="4" aria-valuenow="1" aria-valuetext="准备提交"><span class="api-progress-fill"></span></div><div class="api-progress-note" data-api-progress-note>进度按服务端已确认阶段显示。</div>',targets=[[document.querySelector('[data-result-panel="api"]'),document.getElementById('genApiResult'),'polite'],[document.getElementById('apiDrawer'),document.getElementById('apiDrawerStatus'),'off']];targets.forEach(([host,before,live])=>{if(!host||!before)return;const view=document.createElement('section');view.className='api-progress';view.dataset.apiProgress='';view.hidden=true;view.setAttribute('aria-live',live);view.setAttribute('aria-atomic','true');view.innerHTML=markup;host.insertBefore(view,before)})}
function isApiCancelled(job){return ['cancelled','canceled'].includes(String(job?.status||'').toLowerCase())}
function isTerminalJob(job){return API_PROGRESS_TERMINAL.has(String(job?.status||'').toLowerCase())}
function formatApiElapsed(startedAt){const seconds=Math.max(0,Math.floor((Date.now()-startedAt)/1000));return seconds<60?seconds+'秒':Math.floor(seconds/60)+'分'+String(seconds%60).padStart(2,'0')+'秒'}
function describeApiProgress(job,override={}){const status=String(job?.status||'running').toLowerCase(),provider=String(job?.provider_status||'').toUpperCase(),processing=provider==='API_PROCESSING_RESULT'||provider==='API_FITTING_RESULT'||provider==='API_VALIDATING_RESULT',started=Boolean(job?.provider_started)||provider==='API_GENERATING'||processing||provider==='API_DONE'||provider==='API_ERROR',step=processing?3:(started?2:1),task=job?.id?'任务号 '+job.id+' · ':'';if(status==='done'||provider==='API_DONE')return{step:4,tone:'done',label:'图片已生成 · 阶段 4/4',note:task+'服务端已完成生成和文件保存。'};if(isApiCancelled(job))return{step,tone:'cancelled',label:'任务已取消',note:task+'服务端已确认任务取消。'};if(status==='error'||provider==='API_ERROR')return{step,tone:'error',label:'生成失败',note:task+(override.message||'任务已停止，请按页面错误信息处理。')};if(status==='recovering'||override.uncertain)return{step,tone:'recovering',label:'正在确认任务状态',note:task+(override.message||'不会重复提交；这里只继续确认原任务状态。')};if(provider==='API_PROCESSING_RESULT'||provider==='API_VALIDATING_RESULT')return{step:3,tone:'running',label:'正在解析生成结果 · 阶段 3/4',note:task+'上游生成已经返回，服务端正在校验和解析图片。'};if(provider==='API_FITTING_RESULT')return{step:3,tone:'running',label:'正在适配目标画布 · 阶段 3/4',note:task+'正在按所选比例完成最终画布并保存图片。'};if(provider==='API_GENERATING')return{step:2,tone:'running',label:'图像模型生成中 · 阶段 2/4',note:task+(override.restored?'已恢复任务跟踪；':'')+'上游不提供实时百分比，这里仅显示已确认阶段，不估算剩余时间。'};return{step:1,tone:'running',label:'提交与受理 · 阶段 1/4',note:task+'正在提交请求并等待图像模型开始处理。'}}
function renderApiProgress(job=apiProgressSnapshot,override={}){if(!job)return;apiProgressSnapshot={...(apiProgressSnapshot||{}),...job};apiProgressOverride=override;const state=describeApiProgress(apiProgressSnapshot,override),startedAt=Number(apiProgressSnapshot.created)*1000||apiProgressStartedAt||Date.now(),width=state.step===4?'100%':state.step===3?'78%':state.step===2?'48%':'14%';document.querySelectorAll('[data-api-progress]').forEach(view=>{view.hidden=false;view.className='api-progress is-'+state.tone;view.querySelector('[data-api-progress-stage]').textContent=state.label;view.querySelector('[data-api-progress-elapsed]').textContent='已等待 '+formatApiElapsed(startedAt);view.querySelector('[data-api-progress-note]').textContent=state.note;const track=view.querySelector('[data-api-progress-track]');track.style.setProperty('--api-stage-width',width);track.setAttribute('aria-valuenow',String(state.step));track.setAttribute('aria-valuetext',state.label+(state.tone==='running'&&state.step===2?'，无实时百分比':''))})}
function startApiProgress(job,override={}){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressSnapshot={...job};apiProgressStartedAt=Number(job?.created)*1000||Date.now();renderApiProgress(apiProgressSnapshot,override);if(!isTerminalJob(apiProgressSnapshot))apiProgressTimer=setInterval(()=>renderApiProgress(apiProgressSnapshot,apiProgressOverride),1000)}
function finishApiProgress(job,override={}){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressTimer=0;renderApiProgress(job,override)}
function pauseApiProgress(message){if(apiProgressTimer)clearInterval(apiProgressTimer);apiProgressTimer=0;renderApiProgress(apiProgressSnapshot||{generation_backend:'api',status:'recovering'},{uncertain:true,message})}
function creatorPhaseText(job){if(job?.generation_backend==='api')return describeApiProgress(job).label.replace(/ · 阶段 \d\/4$/,'');const stage=(job?.stage_status||[]).find(item=>item.status==='RUNNING');return job?.provider_status==='RESULT_TRANSFERRING'||job?.provider_status==='RESULT_DOWNLOADING'?'正在取回结果 '+(job.transfer_index||0)+'/'+(job.transfer_total||0):(stage?.stage_label||job?.provider_status||job?.status||'正在处理')}
function paintLiquid(button,value){const pct=Math.max(0,Math.min(100,value));button.style.setProperty('--liquid-progress',pct.toFixed(2)+'%')}
function renderLiquidFrame(button,now){const state=liquidMotionState.get(button);if(!state)return;const elapsed=Math.max(0,now-state.started),t=Math.min(1,elapsed/state.duration),smooth=t*t*(3-2*t);state.display=Math.min(state.target,state.from+(state.target-state.from)*smooth);paintLiquid(button,state.display);if(t<1&&state.display<state.target)state.raf=requestAnimationFrame(ts=>renderLiquidFrame(button,ts));else{state.display=state.target;state.raf=0;paintLiquid(button,state.display);button.dispatchEvent(new CustomEvent('liquidsettled',{detail:{progress:state.display}}))}}
function setLiquidProgress(button,progress,immediate=false){const target=Math.max(0,Math.min(100,Number(progress)||0));let state=liquidMotionState.get(button);if(!state){state={display:0,target:0,from:0,started:0,duration:LIQUID_MIN_DURATION,raf:0};liquidMotionState.set(button,state)}if(state.raf)cancelAnimationFrame(state.raf);state.target=Math.max(state.display,target);button.dataset.progressTarget=state.target.toFixed(2);state.from=state.display;const distance=Math.abs(target-state.display);state.duration=Math.min(LIQUID_MAX_DURATION,Math.max(LIQUID_MIN_DURATION,distance*28));state.started=performance.now();if(immediate||LIQUID_REDUCED_MOTION){state.display=state.target;state.raf=0;paintLiquid(button,state.display);return}state.raf=requestAnimationFrame(ts=>renderLiquidFrame(button,ts))}
function waitLiquidSettled(button,target,timeout=LIQUID_MAX_DURATION+500){const state=liquidMotionState.get(button);if(!state||state.display>=target-.05)return Promise.resolve();return new Promise(resolve=>{let done=false;const finish=()=>{if(done)return;done=true;button.removeEventListener('liquidsettled',onSettle);resolve()};const onSettle=e=>{if(e.detail.progress>=target-.05)finish()};button.addEventListener('liquidsettled',onSettle);setTimeout(finish,timeout)})}
function setLiquidLoading(button,loading){button.classList.toggle('is-loading',loading);button.setAttribute('aria-busy',loading?'true':'false');if(!loading){const state=liquidMotionState.get(button);if(state?.raf)cancelAnimationFrame(state.raf);liquidMotionState.delete(button);paintLiquid(button,0);button.dataset.progressTarget='0'}}
async function pollJobResilient(jobId,onUpdate,maxConsecutive=6){let retry=0;while(1){await new Promise(x=>setTimeout(x,LIQUID_POLL_INTERVAL));try{const j=await api('/api/job/'+jobId);retry=0;onUpdate(j,false,0);if(j.generation_backend==='api'){isTerminalJob(j)?finishApiProgress(j):renderApiProgress(j)}if(isTerminalJob(j))return j}catch(e){retry++;onUpdate(null,true,retry);if(apiProgressSnapshot?.id===jobId)renderApiProgress(apiProgressSnapshot,{uncertain:true,message:'面板连接暂时中断，正在重试（'+retry+'/'+maxConsecutive+'）。不会重复提交。'});if(retry>=maxConsecutive){const uncertain=new Error('连续'+retry+'次轮询失败：'+e.message);uncertain.jobStateUncertain=true;throw uncertain}}}}
async function submitGenerateResilient(body){let last;for(let retry=0;retry<2;retry++){try{return await api('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}catch(e){last=e;if(e.status>=400&&e.status<500)throw e;if(retry===0)await new Promise(x=>setTimeout(x,1600))}}throw last}
function render(){prepareStyle(currentStyle);document.querySelectorAll('[data-style]').forEach(b=>b.classList.toggle('active',b.dataset.style===currentStyle));document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===currentMode));updateColdVariantUI();const root=document.getElementById('drawers');root.innerHTML='';DRAWERS.forEach(d=>{const keys=d.keys.filter(k=>pools()[k]&&enabled(k));if(!keys.length)return;const box=document.createElement('section');box.className='drawer'+(openDrawers.has(d.id)?' open':'');box.dataset.drawer=d.id;box.innerHTML=`<button class="drawer-head"><span>${d.title}</span><span>⌄</span></button><div class="drawer-body"></div>`;box.querySelector('.drawer-head').onclick=()=>{openDrawers.has(d.id)?openDrawers.delete(d.id):openDrawers.add(d.id);render()};const body=box.querySelector('.drawer-body');keys.forEach(k=>{const chosen=new Set(selectedItems(k).map(x=>x[1]));const card=document.createElement('article');card.className='item';card.innerHTML=`<div class="item-head"><span class="item-name">${label(k)}</span><span class="item-actions"><button class="reroll">↻</button><button class="lock">${locks()[k]?'🔒':'🔓'}</button></span></div><div class="picker-wrap"><select class="picker" ${isMulti(k)?'multiple size="4"':''}>${pools()[k].map((x,i)=>`<option value="${i}" ${chosen.has(x[1])?'selected':''}>${x[0]}</option>`).join('')}</select></div>`;card.querySelector('.reroll').onclick=()=>{const a=pools()[k].filter(x=>x[1]);const v=a[Math.floor(Math.random()*a.length)]||selected(k);state()[k]=isMulti(k)?[v]:v;render()};card.querySelector('.lock').onclick=()=>{locks()[k]=!locks()[k];render()};card.querySelector('select').onchange=e=>{if(isMulti(k)){const v=[...e.target.selectedOptions].map(o=>pools()[k][+o.value]);state()[k]=v.length?v:[pools()[k].find(x=>!x[1])||pools()[k][0]]}else state()[k]=pools()[k][+e.target.value];render()};body.appendChild(card)});root.appendChild(box)});document.getElementById('promptText').value=buildAll();updateStylePreview()}
function snapshotSelections(){const api=normalizeApiSettings({api_model:apiModel.value,api_quality:apiQuality.value,api_fit:apiFit.value,api_ratio:selectedApiRatio()});return{style:currentStyle,style_variant:currentStyleVariant(),mode:currentMode,state:JSON.parse(JSON.stringify(state())),locked:JSON.parse(JSON.stringify(locks())),width:+genW.value,height:+genH.value,batch:+genBatch.value,hd:+genHd.value,sequence_mode:'off',prompt_mode:promptMode.value,manual_positive:manualPositive.value,manual_negative:manualNegative.value,seed:+genSeed.value,seed_mode:seedMode.value,...api}}
function applySnapshot(snapshot){if(!snapshot?.state)return;const api=normalizeApiSettings(snapshot);currentStyle=STYLE_CONFIGS[snapshot.style]?snapshot.style:'cold';currentMode=snapshot.mode||'original';setStyleVariant(snapshot.style_variant||'character_bound');prepareStyle(currentStyle);stateByStyle[currentStyle]={};Object.keys(pools()).forEach(k=>{const old=snapshot.state[k];const vals=isMulti(k)?(Array.isArray(old?.[0])?old:(old?[old]:[])):(old?[old]:[]);const hit=vals.map(v=>pools()[k].find(x=>v&&(x[1]===v[1]||x[0]===v[0]))).filter(Boolean);const z=pools()[k].find(x=>!x[1])||pools()[k][0];stateByStyle[currentStyle][k]=isMulti(k)?(hit.length?hit:[z]):(hit[0]||z)});lockedByStyle[currentStyle]=snapshot.locked||{};genW.value=snapshot.width||768;genH.value=snapshot.height||1024;genBatch.value=snapshot.batch||1;genHd.value=snapshot.hd||0;promptMode.value=snapshot.prompt_mode||'options';manualPositive.value=snapshot.manual_positive||'';manualNegative.value=snapshot.manual_negative||'';genSeed.value=snapshot.seed||newRandomSeed();seedMode.value=snapshot.seed_mode||'fixed';apiModel.value=api.api_model;updateApiQualityOptions(api.api_quality);apiFit.value=api.api_fit;document.querySelectorAll('input[name="apiRatio"]').forEach(input=>input.checked=input.value===api.api_ratio);openDrawers=new Set(Object.keys(state()).filter(k=>selectedItems(k).some(x=>x[1])).map(drawerFor).filter(Boolean));updatePromptModeUI();updateBatchSemantics();render();window.scrollTo({top:0,behavior:'smooth'})}
function updatePromptModeUI(){manualPromptPanel.style.display=promptMode.value==='manual'?'block':'none';document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.checked=x.value===promptMode.value)}
function updateBatchSemantics(){genBatch.disabled=false;batchNote.textContent=''}
function creatorCoinText(j){if(j.generation_backend==='local'||j.generation_backend==='api')return'RH币：不适用';if(j.rh_coins!==null&&j.rh_coins!==undefined&&j.rh_coins!=='')return'RH币：'+String(j.rh_coins);return(j.status==='done'||j.status==='error')?'RH币：未返回':'RH币：统计中'}
function addResult(j,container){container.replaceChildren();const images=j.images||[];if(!images.length)return;previewEmpty.classList.add('hidden');document.querySelector('.preview-stage').classList.add('has-results');setResultTab(j.generation_backend||'cloud');const gallery=document.createElement('section'),main=document.createElement('div'),strip=document.createElement('div'),thumbs=document.createElement('div'),prev=document.createElement('button'),next=document.createElement('button');gallery.className='media-gallery';main.className='gallery-main';strip.className='gallery-strip';thumbs.className='gallery-thumbs';prev.className='gallery-prev';next.className='gallery-next';prev.textContent='←';next.textContent='→';let selected=0;const show=index=>{selected=(index+images.length)%images.length;main.replaceChildren();const im=images[selected],meta=document.createElement('div'),img=document.createElement('img'),actions=document.createElement('div'),fav=document.createElement('button'),download=document.createElement('a'),ui=backendUi(j.generation_backend),seedText=j.seed_supported===false?'Seed：不适用':'种子：'+(j.seed??j.sequence_seed??'未知'),requested=j.generation_backend==='api'?('比例 '+(j.api_ratio||'未知')+' · 请求质量 '+(j.api_quality||'未知')):'',actual=j.generation_backend==='api'?('上游实际 '+[j.api_upstream_model,j.api_upstream_quality,j.api_upstream_size].filter(Boolean).join(' · ')):'';meta.className='gallery-meta note';meta.textContent=[im.stage_label||('结果 '+(selected+1)),ui.label,creatorCoinText(j),seedText,requested,actual].filter(Boolean).join(' · ');img.loading='lazy';img.decoding='async';img.src=im.preview_url||im.url;actions.className='gallery-actions';fav.className='dl';fav.textContent='♥ 收藏图片和提示词';fav.onclick=async()=>{fav.disabled=true;try{await api('/api/favorites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:j.id,image_index:selected})});fav.textContent='✓ 已收藏'}catch(e){fav.disabled=false;fav.textContent='收藏失败：'+e.message}};download.className='dl';download.target='_blank';download.rel='noopener noreferrer';download.href=im.url;download.textContent='⬇ 下载原图';actions.append(fav,download);main.append(meta,img,actions);[...thumbs.children].forEach((b,i)=>b.classList.toggle('active',i===selected))};images.forEach((im,i)=>{const b=document.createElement('button'),img=document.createElement('img');b.type='button';b.className='gallery-thumb';img.src=im.preview_url||im.url;img.alt='结果 '+(i+1);b.appendChild(img);b.onclick=()=>show(i);thumbs.appendChild(b)});prev.onclick=()=>show(selected-1);next.onclick=()=>show(selected+1);prev.disabled=next.disabled=images.length<2;strip.append(prev,thumbs,next);gallery.append(main,strip);container.appendChild(gallery);show(0)}
async function resumeActiveJob(backend){
const jobId=sessionStorage.getItem(activeJobKey(backend));if(!jobId)return;const {button,status,result}=backendUi(backend);if(backend==='api'){setResultTab('api');startApiProgress({id:jobId,generation_backend:'api',status:'recovering',created:Date.now()/1000},{uncertain:true,message:'正在读取原任务状态，不会重复提交。'})}
try{let j=await api('/api/job/'+jobId);if(backend==='api')startApiProgress(j,{restored:true});if(j.status==='done'){forgetActiveJob(backend);addResult(j,result);status.textContent='✓ 已恢复完成任务（'+j.elapsed+'秒）';return}if(j.status==='error'){forgetActiveJob(backend);status.textContent='✗ '+(j.error||'任务失败');return}if(isApiCancelled(j)){forgetActiveJob(backend);status.textContent='任务已取消';return}genRunning[backend]=true;button.disabled=true;setLiquidLoading(button,true);setLiquidProgress(button,Number(j.progress_pct)||0);status.textContent='正在恢复任务';j=await pollJobResilient(jobId,(next,broken,retry)=>{if(broken){status.textContent='轮询连接暂时中断，正在重试（'+retry+'/6）';return}setLiquidProgress(button,Number(next.progress_pct)||0);status.textContent=creatorPhaseText(next)});forgetActiveJob(backend);if(j.status==='done'){setLiquidProgress(button,100);addResult(j,result);await waitLiquidSettled(button,100);status.textContent='✓ 完成（'+j.elapsed+'秒）'}else if(isApiCancelled(j))status.textContent='任务已取消';else status.textContent='✗ '+(j.error||'任务失败')}catch(e){if(backend==='api')pauseApiProgress('自动查询暂时中断；任务号已保留，刷新页面会继续恢复。');status.textContent='任务恢复暂时失败：'+e.message}finally{genRunning[backend]=false;setLiquidLoading(button,false);button.disabled=false}}
async function resumeActiveJobs(){await Promise.all(['cloud','local','api'].map(resumeActiveJob))}
async function generate(backend){
if(genRunning[backend])return;genRunning[backend]=true;const {button,status,result}=backendUi(backend);let lastProgress=0,terminal=false,accepted=false;button.disabled=true;setLiquidLoading(button,true);setLiquidProgress(button,3);status.textContent='正在提交…';result.innerHTML='';if(backend==='api'){setResultTab('api');startApiProgress({generation_backend:'api',status:'running',provider_status:'SUBMITTING',created:Date.now()/1000})}
try{
const sequence_mode='off';if(seedMode.value==='random')genSeed.value=newRandomSeed();const seed=+genSeed.value;const positive=promptMode.value==='manual'?manualPositive.value.trim():buildCorePrompt();const negative=promptMode.value==='manual'?manualNegative.value.trim():cfg().negative;if(!positive)throw new Error('正向提示词不能为空');
const candidate={workflow:'anima02',prompt:positive,negative_prompt:negative,prompt_mode:promptMode.value,width:+genW.value,height:+genH.value,batch:backend==='api'?1:+genBatch.value,hd:backend==='api'?0:+genHd.value,seed:seed,seed_mode:seedMode.value,style_id:currentStyle,style_variant:currentStyleVariant(),mode:currentMode,sequence_mode,generation_backend:backend,api_model:apiModel.value,api_quality:apiQuality.value,api_fit:apiFit.value,selection_snapshot:{...snapshotSelections(),generation_backend:backend}};
if(backend==='api'){delete candidate.width;delete candidate.height;candidate.api_ratio=selectedApiRatio();candidate.selection_snapshot.api_ratio=candidate.api_ratio}
const pending=pendingCreatorRequest(backend,candidate),body={...pending.body,client_request_id:pending.id};const r=await submitGenerateResilient(body);accepted=true;forgetPendingCreator(backend);rememberActiveJob(backend,r.job_id);if(backend==='api')renderApiProgress({id:r.job_id,generation_backend:'api',status:'running',provider_status:'SUBMITTING'});
const j=await pollJobResilient(r.job_id,(next,broken,retry)=>{if(broken){status.textContent='轮询连接暂时中断，正在重试（'+retry+'/6）';return}lastProgress=Math.max(lastProgress,Number(next.progress_pct)||0);setLiquidProgress(button,lastProgress);status.textContent=creatorPhaseText(next)});terminal=true;forgetActiveJob(backend);if(isApiCancelled(j)){status.textContent='任务已取消';return}if(j.status==='error')throw new Error(j.error||'生成失败');setLiquidProgress(button,100);addResult(j,result);await waitLiquidSettled(button,100);status.textContent='✓ 完成（'+j.elapsed+'秒'+(j.api_prompt_compacted?'，已为Sub2API稳定性压缩提示词':'')+(j.seed_supported===false?'，Seed不适用':'，种子 '+j.seed)+'）';await new Promise(x=>setTimeout(x,420))
}catch(e){if(e.status>=400&&e.status<500)forgetPendingCreator(backend);if(backend==='api'&&!terminal){if(e.jobStateUncertain&&accepted){pauseApiProgress('自动查询暂时中断；任务号已保留，刷新页面会继续恢复。');status.textContent='任务状态暂时无法确认；刷新页面将继续查询原任务'}else{finishApiProgress({...(apiProgressSnapshot||{}),generation_backend:'api',status:'error',provider_status:'API_ERROR'},{message:e.message});status.textContent='✗ '+e.message}}else status.textContent='✗ '+e.message;if(terminal)forgetActiveJob(backend)}finally{genRunning[backend]=false;setLiquidLoading(button,false);button.disabled=false}}
async function history(){histList.textContent='加载中…';try{const a=await api('/api/jobs?scope=creator');histList.replaceChildren();a.slice(0,10).forEach(j=>{const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div'),view=document.createElement('button');d.className='job';note.className='note';view.className='dl';const variant=j.style_id==='cold'?(j.style_variant==='style_only'?'仅画风候选':'人物+画风'):'';const backend=backendUi(j.generation_backend).label;title.textContent=(STYLE_CONFIGS[j.style_id]?.short||'历史')+(variant?' · '+variant:'')+' · '+backend+' · '+(j.mode==='character'?'角色':'原创');note.textContent=j.status+' · '+creatorCoinText(j)+' · '+j.width+'×'+j.height+' · '+j.batch+'张 · 种子 '+(j.seed??j.sequence_seed??'未知')+' · '+(j.elapsed||'')+'秒';view.textContent='查看图片';view.onclick=()=>addResult(j,d);d.append(title,note,view);histList.appendChild(d)})}catch(e){const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div');d.className='job';note.className='note';title.textContent='历史加载失败';note.textContent=e.message;d.append(title,note);histList.replaceChildren(d)}}
async function favorites(){favList.textContent='加载中…';try{const a=await api('/api/favorites');favList.replaceChildren();a.forEach(f=>{const d=document.createElement('div'),note=document.createElement('div'),img=document.createElement('img'),apply=document.createElement('button'),copy=document.createElement('button'),download=document.createElement('a');d.className='job';note.className='note';note.textContent='种子：'+(f.seed??f.selection_snapshot?.seed??'未知')+' · '+(f.prompt_mode==='manual'?'手动Prompt':'选项组合');img.src=f.preview_url||f.image_url;img.alt='收藏结果';apply.className='dl apply';apply.textContent='↺ 套用提示词、选项和种子';copy.className='dl copy';copy.textContent='复制完整提示词';download.className='dl';download.href=f.image_url;download.target='_blank';download.rel='noopener noreferrer';download.textContent='⬇ 下载收藏原图';apply.onclick=()=>{applySnapshot(f.selection_snapshot);favOverlay.classList.remove('open')};copy.onclick=()=>navigator.clipboard.writeText(f.prompt||'');d.append(note,img,apply,copy,download);favList.appendChild(d)})}catch(e){const d=document.createElement('div'),title=document.createElement('b'),note=document.createElement('div');d.className='job';note.className='note';title.textContent='收藏加载失败';note.textContent=e.message;d.append(title,note);favList.replaceChildren(d)}}
document.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;currentStyle=b.dataset.style;currentMode=cfg().defaultMode||'original';prepareStyle(currentStyle);openDrawers.clear();updateBatchSemantics();render()});document.querySelectorAll('[data-style-variant]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;setStyleVariant(b.dataset.styleVariant);render()});document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{if(!styleDataReady)return;currentMode=b.dataset.mode;openDrawers.clear();render()});document.querySelectorAll('input[name="promptModeRadio"]').forEach(x=>x.onchange=()=>{promptMode.value=x.value;updatePromptModeUI()});importGeneratedPrompt.onclick=importGeneratedPromptToManual;document.querySelectorAll('[data-result-tab]').forEach(x=>x.onclick=()=>setResultTab(x.dataset.resultTab));seedMode.onchange=()=>{if(seedMode.value==='random')genSeed.value=newRandomSeed()};apiModel.onchange=()=>updateApiQualityOptions();const setApiDrawer=open=>{apiDrawer.classList.toggle('open',open);apiDrawer.setAttribute('aria-hidden',open?'false':'true')};apiDrawerOpen.onclick=()=>setApiDrawer(true);apiDrawerClose.onclick=()=>setApiDrawer(false);apiDrawerBackdrop.onclick=()=>setApiDrawer(false);new MutationObserver(()=>apiDrawerStatus.textContent=genApiStatus.textContent).observe(genApiStatus,{childList:true,characterData:true,subtree:true});addEventListener('keydown',event=>{if(event.key==='Escape')setApiDrawer(false)});document.getElementById('randomAll').onclick=randomAll;document.getElementById('clearAll').onclick=setNone;genCloudBtn.onclick=()=>generate('cloud');genLocalBtn.onclick=()=>generate('local');genApiBtn.onclick=()=>generate('api');document.getElementById('copyPrompt').onclick=()=>navigator.clipboard.writeText(buildAll());document.getElementById('promptToggle').onclick=()=>promptPanel.classList.toggle('open');document.getElementById('histOpen').onclick=()=>{histOverlay.querySelector('.library-scroll').scrollTop=0;histOverlay.classList.add('open');history()};document.getElementById('favOpen').onclick=()=>{favOverlay.querySelector('.library-scroll').scrollTop=0;favOverlay.classList.add('open');favorites()};document.querySelectorAll('.library-overlay .close').forEach(b=>b.onclick=()=>b.closest('.library-overlay').classList.remove('open'));document.querySelectorAll('.library-overlay').forEach(x=>x.onclick=e=>{if(e.target===x)x.classList.remove('open')});const styleParam=new URLSearchParams(location.search).get('style');if(styleParam&&STYLE_BOOT[styleParam])currentStyle=styleParam;genSeed.value=newRandomSeed();updateApiQualityOptions();setResultTab('cloud');setStyleControlsReady(false);renderBootPreview();installApiProgress();scheduleRoutePrefetch();loadStyleConfigs().then(()=>resumeActiveJobs()).catch(()=>{});</script></body></html>'''
html=html.replace('__WORKBENCH_CSS__',WORKBENCH_CSS+API_POPOVER_CSS+WORKBENCH_GLASS_CSS).replace('__BOOT_DATA__',BOOT_DATA).replace('__STYLE_CONFIG_URL__',STYLE_CONFIG_URL).replace('__DRAWERS__',DRAWS)
html=html.replace('<div class="app-shell">','<div class="app-background" aria-hidden="true"></div><div class="app-shell">')
html=html.replace('<button class="api-drawer-open" id="apiDrawerOpen" type="button">API生图</button>','<div class="api-popover-anchor"><button class="api-drawer-open" id="apiDrawerOpen" type="button" aria-expanded="false" aria-controls="apiDrawer">API生图</button></div>')
html=html.replace('<aside class="api-drawer" id="apiDrawer" aria-hidden="true">','<aside class="api-popover" id="apiDrawer" hidden inert aria-hidden="true" aria-labelledby="apiDrawerTitle">')
html=html.replace('<div class="api-drawer-head"><div><span class="eyebrow">IMAGE API</span><h2>API专属生图</h2></div>','<div class="api-popover-head"><div><span class="eyebrow">IMAGE API</span><h2 id="apiDrawerTitle">API专属生图</h2></div>')
html=html.replace('</aside><div class="api-drawer-backdrop" id="apiDrawerBackdrop"></div>','</aside>')
html=re.sub(r"const setApiDrawer=open=>\{.*?apiDrawerBackdrop\.onclick=\(\)=>setApiDrawer\(false\);",'',html)
html=html.replace("addEventListener('keydown',event=>{if(event.key==='Escape')setApiDrawer(false)});",'')
html=html.replace('</script></body></html>',API_POPOVER_BOOT+'</script></body></html>')
for stale in STATIC.glob("style-configs.*.json"):
    if stale.name!=STYLE_DATA_NAME:
        stale.unlink()
(STATIC/STYLE_DATA_NAME).write_bytes(STYLE_DATA_BYTES)
for p in (STATIC/"promptgen.html",STATIC/"index.html"): p.write_text(html,encoding="utf-8")
print(json.dumps({k:{"pools":len(v["pools"]),"trigger":v["trigger"],"lora1":v["lora1"],"lora2":v["lora2"]} for k,v in profiles.items()},ensure_ascii=False,indent=2))
