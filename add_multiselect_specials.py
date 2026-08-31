from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")
FILES = [ROOT / "promptgen.html", ROOT / "index.html"]

SPECIAL_OUTFIT = '''  special_outfit: [
    ["无特殊服装","no additional special outfit layer"],
    ["黑色蕾丝吊带睡裙","adult woman wearing a black lace-trim satin slip dress, tasteful fashion editorial"],
    ["酒红色丝绒紧身连衣裙","adult woman wearing a fitted burgundy velvet dress, elegant body-contouring silhouette"],
    ["黑色高领无袖紧身衣","adult woman wearing a sleek black sleeveless turtleneck bodysuit, non-explicit fashion styling"],
    ["白衬衫 + 黑色蕾丝内搭","adult woman wearing an oversized white shirt over a black lace camisole"],
    ["露背缎面长裙","adult woman wearing a backless satin evening dress, elegant non-explicit styling"],
    ["单肩开衩礼服","adult woman wearing a one-shoulder dress with a tasteful side slit"],
    ["短款皮夹克 + 修身吊带裙","adult woman wearing a cropped leather jacket over a fitted slip dress"],
    ["宽松男友衬衫 + 短裤","adult woman wearing an oversized boyfriend shirt with fitted shorts"],
    ["黑色束腰上衣 + 高腰长裙","adult woman wearing a structured black corset-style top over a high-waisted long skirt, fully covered"],
    ["蕾丝边连体衣 + 西装外套","adult woman wearing a lace-trim fashion bodysuit under an oversized blazer, non-explicit"],
    ["高开衩针织长裙","adult woman wearing a fitted ribbed knit maxi dress with a high side slit"],
    ["露肩毛衣 + 过膝袜","adult woman wearing an off-shoulder oversized sweater with thigh-high socks"],
    ["挂脖短上衣 + 低腰阔腿裤","adult woman wearing a halter crop top with low-rise wide-leg trousers"],
    ["丝绸睡袍 + 吊带内搭","adult woman wearing a loosely wrapped silk robe over a satin camisole, tasteful boudoir fashion"],
    ["透明薄纱罩衫 + 不透明内搭","adult woman wearing a sheer mesh cover-up over an opaque fitted inner outfit"],
    ["漆皮短裙 + 长袖贴身上衣","adult woman wearing a glossy patent mini skirt with a fitted long-sleeve top"],
    ["镂空针织上衣 + 高腰短裤","adult woman wearing an open-knit top layered over an opaque camisole with high-waisted shorts"],
    ["抹胸礼服 + 长手套","adult woman wearing an elegant strapless evening dress with opera gloves"],
    ["不对称绑带上衣 + 铅笔裙","adult woman wearing an asymmetrical strappy fashion top with a fitted pencil skirt"],
    ["黑色连体泳装 + 轻薄衬衫","adult woman wearing a black one-piece swimsuit under a lightweight open shirt, resort editorial"]
  ],

'''

SPECIAL_POSE = '''  special_pose: [
    ["无特殊姿势叠加","no additional special pose modifier"],
    ["侧卧蜷腿，回头看镜头","lying on one side with knees softly bent, looking back toward viewer"],
    ["仰躺屈膝，双手放在头顶","lying on back with knees bent, both arms resting above head"],
    ["跪坐后仰，双手撑在身后","kneeling seated and leaning backward, both hands supporting the body behind"],
    ["伏在床沿，双腿自然后屈","lying prone near the edge of a bed, lower legs bent upward naturally"],
    ["坐地后撑，一腿屈起一腿伸直","sitting on the floor supported by hands behind, one knee raised and one leg extended"],
    ["背对镜头跪坐并回眸","kneeling with back toward camera, looking back over shoulder"],
    ["侧坐交叠双腿，身体向镜头前倾","sitting sideways with legs crossed, torso leaning gently toward the camera"],
    ["趴卧撑起上身，脚踝在后景交叠","lying prone while lifting upper body on forearms, ankles crossed in the background"],
    ["单膝跪在沙发上，另一腿落地","one knee resting on a sofa while the other leg remains on the floor"],
    ["斜躺沙发，腰背形成柔和曲线","reclining diagonally on a sofa, waist and back forming a soft curve"],
    ["坐在椅缘，双膝并拢偏向一侧","sitting on the edge of a chair, knees together and angled to one side"],
    ["双腿贴墙仰躺，俯视镜头","lying on back with legs resting upward against a wall, viewed from above"],
    ["半跪整理过膝袜，抬眼看镜头","half-kneeling while adjusting thigh-high socks, eyes lifted toward viewer"],
    ["俯身系鞋带，肩上回眸","bending forward to tie a shoe, looking back over shoulder"],
    ["坐在高处垂下一腿，另一腿屈起","sitting on a high surface with one leg dangling and the other bent"],
    ["四肢着地但保持时尚编辑构图","on hands and knees in a tasteful fashion-editorial pose, fully clothed, non-explicit"],
    ["弓背伸展，头微微后仰","arching the back in a gentle stretch, head tilted slightly backward"],
    ["双膝跪地，身体侧转，手扶大腿","kneeling on both knees, torso turned sideways, one hand resting on thigh"],
    ["一腿抬高靠在椅背，身体侧倾","one leg raised against the back of a chair, torso leaning sideways in an editorial pose"],
    ["盘腿坐下，身体前倾靠近镜头","sitting cross-legged and leaning forward toward the camera"]
  ],

'''

for path in FILES:
    s = path.read_text(encoding="utf-8")
    if "special_outfit:" not in s:
        s = s.replace("  fashion_extra: [", SPECIAL_OUTFIT + "  fashion_extra: [", 1)
    if "special_pose:" not in s:
        s = s.replace("  pose: [", SPECIAL_POSE + "  pose: [", 1)

    s = s.replace(
        'const DROPDOWN_KEYS = Object.keys(POOLS);',
        'const DROPDOWN_KEYS = Object.keys(POOLS);\nconst MULTI_KEYS = new Set(["special_outfit", "special_prompt", "special_pose"]);',
        1,
    )

    old = '''function randomize(force=false){
  Object.keys(POOLS).forEach(key=>{
    if(force || !locked[key] || !state[key]) state[key] = pick(POOLS[key]);
  });
  save();
  render();
}'''
    new = '''function randomize(force=false){
  Object.keys(POOLS).forEach(key=>{
    if(force || !locked[key] || !state[key]) {
      state[key] = MULTI_KEYS.has(key) ? [pick(POOLS[key])] : pick(POOLS[key]);
    }
  });
  save();
  render();
}

function selectedItems(key){
  const v = state[key];
  if(!v) return [];
  if(MULTI_KEYS.has(key)) {
    if(Array.isArray(v) && v.length && Array.isArray(v[0])) return v;
    if(Array.isArray(v) && typeof v[0] === "string") return [v];
    return [];
  }
  return [v];
}
function promptFor(key){ return selectedItems(key).map(item=>item[1]).filter(Boolean).join(", "); }
function labelFor(key){ return selectedItems(key).map(item=>item[0]).filter(Boolean).join(" + "); }'''
    if old not in s:
        raise RuntimeError(f"randomize block not found in {path}")
    s = s.replace(old, new, 1)

    replacements = {
        '${state.fashion_extra[1]},': '${state.fashion_extra[1]},\n${promptFor("special_outfit")},',
        '${state.special_prompt[1]},': '${promptFor("special_prompt")},',
        '${state.pose[1]},': '${state.pose[1]},\n${promptFor("special_pose")},',
        'fashion_extra:"额外配件", special_prompt:"特殊提示词",': 'fashion_extra:"额外配件", special_outfit:"特殊服装（可多选）", special_prompt:"特殊提示词（可多选）", special_pose:"特殊姿势（可多选）",',
        '"fashion_extra","special_prompt","pose"': '"fashion_extra","special_outfit","special_prompt","pose","special_pose"',
        '<div class="value">${state[key][0]}</div>`;': '<div class="value">${labelFor(key)}</div>`;',
    }
    for a,b in replacements.items():
        if a not in s:
            raise RuntimeError(f"replacement missing {a!r} in {path}")
        s = s.replace(a,b,1)

    old_select = '''    const currentIndex = Math.max(0, POOLS[key].findIndex(item => item[1] === state[key][1]));
    const wrap = document.createElement("div");
    wrap.className = "picker-wrap";
    const select = document.createElement("select");
    select.className = "picker";
    select.innerHTML = POOLS[key].map((item, idx) =>
      `<option value="${idx}" ${idx === currentIndex ? "selected" : ""}>${item[0]}</option>`
    ).join("");
    select.onchange = (e) => {
      state[key] = POOLS[key][Number(e.target.value)];
      save();
      render();
    };
    const note = document.createElement("div");
    note.className = "picker-note";
    note.textContent = "可直接下拉选择，也可以点 ↻ 单独随机，或点 🔒 锁定。";'''
    new_select = '''    const chosenPrompts = new Set(selectedItems(key).map(item=>item[1]));
    const currentIndex = Math.max(0, POOLS[key].findIndex(item => chosenPrompts.has(item[1])));
    const wrap = document.createElement("div");
    wrap.className = "picker-wrap";
    const select = document.createElement("select");
    select.className = "picker";
    if(MULTI_KEYS.has(key)) { select.multiple = true; select.size = 6; }
    select.innerHTML = POOLS[key].map((item, idx) =>
      `<option value="${idx}" ${chosenPrompts.has(item[1]) ? "selected" : ""}>${item[0]}</option>`
    ).join("");
    select.onchange = (e) => {
      if(MULTI_KEYS.has(key)) {
        const values = [...e.target.selectedOptions].map(o=>POOLS[key][Number(o.value)]);
        state[key] = values.length ? values : [POOLS[key][0]];
      } else {
        state[key] = POOLS[key][Number(e.target.value)];
      }
      save();
      render();
    };
    const note = document.createElement("div");
    note.className = "picker-note";
    note.textContent = MULTI_KEYS.has(key)
      ? "可多选：电脑按 Ctrl/Command 点击；手机直接点选多项。↻ 会重抽为一项，🔒 可锁定组合。"
      : "可直接下拉选择，也可以点 ↻ 单独随机，或点 🔒 锁定。";'''
    if old_select not in s:
        raise RuntimeError(f"select block missing in {path}")
    s = s.replace(old_select, new_select, 1)

    old_reroll = '''    div.querySelector(".reroll").onclick = ()=>{
      state[key] = pick(POOLS[key]);
      save();
      render();
    };'''
    new_reroll = '''    div.querySelector(".reroll").onclick = ()=>{
      const one = pick(POOLS[key]);
      state[key] = MULTI_KEYS.has(key) ? [one] : one;
      save();
      render();
    };'''
    if old_reroll not in s:
        raise RuntimeError(f"reroll block missing in {path}")
    s = s.replace(old_reroll,new_reroll,1)

    path.write_text(s,encoding="utf-8")
    print("updated",path)
