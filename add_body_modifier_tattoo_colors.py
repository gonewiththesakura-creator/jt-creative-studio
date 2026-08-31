from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")
FILES = [ROOT / "promptgen.html", ROOT / "index.html"]

BODY_POOL = '''  body_modifier: [
    ["无（不添加此部分）",""],
    ["娇小纤细","petite slender adult body, delicate narrow frame"],
    ["高挑纤细","tall slender adult body, long elegant proportions"],
    ["标准匀称","balanced adult body proportions, naturally proportioned figure"],
    ["微肉柔软","soft slightly chubby adult body, gentle natural curves"],
    ["丰满曲线","full curvy adult figure, defined waist and hips"],
    ["健美紧致","toned athletic adult body, firm natural musculature"],
    ["肌肉感明显","muscular adult woman, defined arms, abdomen and thighs"],
    ["沙漏型身材","hourglass adult figure, defined waist, balanced bust and hips"],
    ["梨形身材","pear-shaped adult figure, narrower shoulders and fuller hips"],
    ["倒三角身材","inverted-triangle adult figure, broader shoulders and narrower hips"],
    ["直筒型身材","straight rectangular adult body shape, subtle waist definition"],
    ["小胸","small bust, adult woman, natural proportions"],
    ["中等胸型","medium bust, adult woman, natural proportions"],
    ["丰满胸型","full bust, adult woman, tasteful non-explicit proportions"],
    ["自然下垂胸型","natural softly lowered bust shape through clothing, adult woman, non-explicit"],
    ["窄肩","narrow delicate shoulders"],
    ["宽肩","broad athletic shoulders"],
    ["细腰","slim defined waist"],
    ["自然腰线","soft natural waistline"],
    ["宽胯","wide hips, adult woman, natural skeletal proportions"],
    ["窄胯","narrow hips, adult woman"],
    ["圆润臀型","rounded hips and glute silhouette through clothing, adult woman, non-explicit"],
    ["小巧臀型","compact subtle hip and glute silhouette, adult woman"],
    ["丰满臀型","full hip and glute silhouette through clothing, adult woman, tasteful non-explicit"],
    ["修长腿型","long slender legs"],
    ["匀称腿型","balanced naturally proportioned legs"],
    ["健美腿型","toned athletic legs, defined thighs and calves"],
    ["丰满大腿","full soft thighs, adult woman, natural proportions"],
    ["纤细大腿","slender thighs, adult woman"],
    ["小腿线条明显","defined calf muscles"],
    ["微微隆起的小腹","subtly rounded soft lower belly, relaxed natural abdomen"],
    ["平坦小腹","flat relaxed abdomen"],
    ["柔软小腹褶皱","subtle natural belly folds from bending or sitting, adult woman"],
    ["马甲线","subtle abdominal definition, light athletic ab lines"],
    ["明显腹肌","defined athletic abdominal muscles"],
    ["短躯干","short torso, adult body proportions"],
    ["修长躯干","long elegant torso, adult body proportions"],
    ["纤细手臂","slender delicate arms"],
    ["健美手臂","toned athletic arms"],
    ["骨感锁骨","prominent delicate collarbones"],
    ["柔和锁骨","soft subtle collarbone definition"],
    ["圆脸身材搭配","soft round adult face paired with a naturally curved body"],
    ["小头身比例","small head with tall fashion-model body proportions, adult woman"],
    ["七头身比例","seven-head-tall balanced anime adult proportions"],
    ["八头身模特比例","eight-head-tall fashion model proportions, adult woman"]
  ],

'''

TATTOO_COLOR_POOL = '''  tattoo_color: [
    ["无（不添加此部分）",""],
    ["黑色淫纹","black ink succubus tattoo"],
    ["深红色淫纹","deep crimson succubus tattoo"],
    ["鲜红色淫纹","bright red succubus tattoo"],
    ["暗紫色淫纹","dark violet succubus tattoo"],
    ["亮紫色淫纹","luminous purple succubus tattoo"],
    ["粉紫色淫纹","pink-violet succubus tattoo"],
    ["玫红色淫纹","magenta succubus tattoo"],
    ["蓝紫色淫纹","indigo-violet succubus tattoo"],
    ["深蓝色淫纹","deep blue succubus tattoo"],
    ["冰蓝色淫纹","icy cyan-blue succubus tattoo"],
    ["青绿色淫纹","teal succubus tattoo"],
    ["翠绿色淫纹","emerald green succubus tattoo"],
    ["金色淫纹","metallic gold succubus tattoo"],
    ["玫瑰金淫纹","rose-gold succubus tattoo"],
    ["银白色淫纹","silver-white succubus tattoo"],
    ["纯白色淫纹","pure white succubus tattoo"],
    ["荧光粉淫纹","neon pink glowing succubus tattoo"],
    ["荧光紫淫纹","neon purple glowing succubus tattoo"],
    ["荧光蓝淫纹","neon blue glowing succubus tattoo"],
    ["紫红渐变淫纹","purple-to-crimson gradient succubus tattoo"],
    ["蓝紫渐变淫纹","blue-to-violet gradient succubus tattoo"],
    ["黑红双色淫纹","black-and-red two-tone succubus tattoo"],
    ["金红双色淫纹","gold-and-crimson two-tone succubus tattoo"],
    ["微微发光的淫纹","softly glowing succubus tattoo, subtle magical light"],
    ["强烈发光的淫纹","brightly glowing succubus tattoo, vivid magical light"]
  ],

'''

for path in FILES:
    s = path.read_text(encoding="utf-8")
    if "  body_modifier: [" not in s:
        s = s.replace("  special_prompt: [", BODY_POOL + "  special_prompt: [", 1)
    if "  tattoo_color: [" not in s:
        s = s.replace("  special_prompt: [", TATTOO_COLOR_POOL + "  special_prompt: [", 1)

    s = s.replace(
        'fashion_extra:"额外配件", special_outfit:"特殊服装（可多选）", special_prompt:"特殊提示词（可多选）", special_pose:"特殊姿势（可多选）",',
        'fashion_extra:"额外配件", special_outfit:"特殊服装（可多选）", body_modifier:"身材修改器（可多选）", tattoo_color:"淫纹颜色", special_prompt:"特殊提示词（可多选）", special_pose:"特殊姿势（可多选）",',
        1,
    )
    s = s.replace(
        'const MULTI_KEYS = new Set(["special_outfit", "special_prompt", "special_pose"]);',
        'const MULTI_KEYS = new Set(["special_outfit", "body_modifier", "special_prompt", "special_pose"]);',
        1,
    )
    s = s.replace(
        '${promptFor("special_outfit")},\n${promptFor("special_prompt")},',
        '${promptFor("special_outfit")},\n${promptFor("body_modifier")},\n${state.tattoo_color[1]},\n${promptFor("special_prompt")},',
        1,
    )
    s = s.replace(
        '"fashion_extra","special_outfit","special_prompt","pose"',
        '"fashion_extra","special_outfit","body_modifier","tattoo_color","special_prompt","pose"',
        1,
    )

    path.write_text(s, encoding="utf-8")
    print("updated", path.name)
