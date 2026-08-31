from pathlib import Path
import re

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")
FILES = [ROOT / "promptgen.html", ROOT / "index.html"]

OUTFITS = [
("经典黑白女仆装","adult woman, classic black-and-white maid dress, maid apron, maid headdress, puff sleeves, fully clothed"),
("法式长裙女仆装","adult woman, elegant French maid-inspired ankle-length dress, lace apron, high collar, fully clothed"),
("维多利亚长袖女仆装","adult woman, Victorian maid uniform, long sleeves, high neckline, long skirt, lace apron"),
("和风女仆装","adult woman, wa maid outfit, kimono-inspired maid dress, obi belt, frilled apron"),
("哥特女仆装","adult woman, gothic maid dress, black lace, high collar, dark frilled apron"),
("咖啡厅短裙女仆装","adult woman, cafe maid uniform, knee-length skirt, frilled apron, ribbon necktie"),
("机能风女仆装","adult woman, techwear-inspired maid outfit, utility straps, structured apron, fully clothed"),
("旗袍女仆装","adult woman, qipao-inspired maid dress, high collar, side panels, frilled apron, tasteful"),
("猫耳女仆装","adult woman, cat-ear maid cosplay, maid headdress, bell ribbon, fully clothed"),
("兔耳女仆装","adult woman, bunny-ear maid cosplay, frilled maid dress, opaque tights, fully clothed"),
("经典白色护士装","adult woman, classic white nurse cosplay uniform, nurse cap, opaque stockings, fully clothed"),
("粉色护士装","adult woman, pink nurse cosplay dress, nurse cap, fitted but non-explicit"),
("黑色哥特护士装","adult woman, gothic black nurse cosplay, medical eyepatch, dark stockings, fully clothed"),
("未来机能护士装","adult woman, futuristic medical-uniform cosplay, white technical jacket, utility belt"),
("日式保健室老师风","adult woman, Japanese school nurse-inspired outfit, white coat over fitted blouse and pencil skirt"),
("成人水手服风穿搭","adult woman, adult sailor-inspired fashion outfit, sailor collar, pleated skirt, clearly adult cosplay"),
("成人JC风制服穿搭","adult woman age 20+, adult cosplay inspired by Japanese middle-school uniform design, modest sailor collar and knee-length pleated skirt, non-sexual"),
("成人JS风制服穿搭","adult woman age 20+, adult cosplay inspired by Japanese elementary uniform design, modest blazer and long skirt, non-sexual fashion recreation"),
("成人JK风西装制服","adult woman age 20+, adult JK-fashion cosplay, blazer, collared shirt, necktie, pleated skirt"),
("成人JK风针织背心制服","adult woman age 20+, adult JK-fashion cosplay, sweater vest, collared blouse, pleated skirt, knee socks"),
("女学院风连衣裙","adult woman, Japanese academy-inspired one-piece uniform dress, sailor collar, calf-length skirt"),
("旧式女学生袴装","adult woman, Taisho-era schoolgirl-inspired hakama outfit, kimono sleeves, boots"),
("经典藏蓝死库水","adult woman age 20+, classic navy school swimsuit cosplay, one-piece swimsuit, non-sexual athletic presentation"),
("新式竞赛死库水","adult woman age 20+, modern competition school swimsuit cosplay, streamlined one-piece, athletic presentation"),
("白色连体泳装","adult woman, white one-piece swimsuit, resort fashion editorial"),
("黑色高领连体泳装","adult woman, black high-neck one-piece swimsuit, sleek athletic styling"),
("荷叶边连体泳装","adult woman, frilled one-piece swimsuit, tasteful resort styling"),
("竞赛连体泳装","adult woman, competition swimsuit, athletic poolside presentation"),
("运动型两件式泳装","adult woman, sporty two-piece swimsuit, athletic beachwear"),
("挂脖比基尼","adult woman, halter bikini, tasteful resort fashion editorial"),
("高腰复古比基尼","adult woman, high-waisted retro bikini, tasteful pin-up inspired resort fashion"),
("荷叶边比基尼","adult woman, frilled bikini, tasteful beachwear styling"),
("侧系带比基尼","adult woman, side-tie bikini, non-explicit resort editorial"),
("长袖冲浪泳衣","adult woman, long-sleeve rash guard swimsuit, sporty surf styling"),
("潜水服","adult woman, fitted diving wetsuit, athletic underwater styling"),
("日式红白运动服","adult woman, Japanese red-and-white gym uniform, athletic t-shirt and bloomers-inspired sports shorts, non-sexual sports presentation"),
("日式蓝白运动服","adult woman, Japanese blue-and-white gym uniform, athletic t-shirt and modest sports shorts"),
("红色运动夹克套装","adult woman, red track suit, zip jacket and track pants, sporty styling"),
("蓝色运动夹克套装","adult woman, blue track suit, zip jacket and track pants, sporty styling"),
("排球运动服","adult woman, volleyball uniform, sleeveless jersey, athletic shorts, knee pads"),
("网球运动服","adult woman, tennis dress, visor, wristbands, athletic shoes"),
("羽毛球运动服","adult woman, badminton sportswear, polo shirt, pleated sport skirt, athletic shoes"),
("篮球运动服","adult woman, basketball jersey and athletic shorts, high-top sneakers"),
("足球运动服","adult woman, soccer jersey, athletic shorts, knee socks, cleats"),
("体操训练服","adult woman, gymnastics training leotard with warm-up jacket, athletic presentation"),
("啦啦队运动服","adult woman, cheerleader-inspired sports uniform, cropped athletic top and pleated sport skirt, adult performer"),
("赛车女郎风运动装","adult woman, race-queen inspired motorsport fashion, fitted sponsor jacket and shorts, non-explicit"),
("拳击训练服","adult woman, boxing training outfit, sports bra under open training jacket, boxing shorts and gloves"),
("瑜伽运动套装","adult woman, fitted yoga sportswear, long-sleeve crop top and high-waisted leggings"),
("芭蕾练功服","adult woman, ballet practice leotard, wrap skirt, tights, ballet shoes"),
("巫女服","adult woman, traditional shrine maiden outfit, white kosode and red hakama"),
("和服振袖","adult woman, elegant furisode kimono, obi, traditional hair ornament"),
("浴衣","adult woman, summer yukata, obi sash, geta sandals"),
("忍者装束","adult woman, stylized kunoichi-inspired ninja outfit, layered fabric, arm guards, non-explicit"),
("魔法少女战斗服","adult woman, mature magical-girl inspired battle costume, layered skirt, boots, ornate accessories"),
("修女服","adult woman, gothic nun-inspired fashion dress, veil, high collar, fully clothed"),
("女骑士铠甲","adult woman, female knight armor, breastplate, armored skirt panels, gauntlets"),
("精灵弓手装","adult woman, fantasy elf archer outfit, leather tunic, cloak, boots"),
("女牛仔装","adult woman, western cowgirl outfit, cowboy hat, fitted shirt, denim shorts or jeans, cowboy boots"),
("魅魔幻想礼服","adult woman, succubus-inspired fantasy dress, small horns, decorative wings, opaque bodice, non-explicit"),
("赛博朋克紧身战斗服","adult woman, cyberpunk fitted combat suit, armored panels, neon accents, fully covered"),
("机甲驾驶服","adult woman, futuristic pilot suit, technical seams, protective panels, fully covered"),
("洛丽塔洋装 · 成年穿搭","adult woman age 20+, gothic lolita fashion dress, layered frills, bonnet, fully clothed"),
("甜系洛丽塔洋装 · 成年穿搭","adult woman age 20+, sweet lolita fashion dress, pastel bows, layered petticoat, fully clothed"),
("旗袍","adult woman, fitted qipao dress, high collar, tasteful side slit"),
("肚皮舞舞台服","adult woman, belly-dance stage costume, embellished top with sheer layered skirt, tasteful performance styling"),
("偶像舞台服","adult woman, Japanese idol stage costume, layered skirt, decorative jacket, boots"),
("视觉系乐队服","adult woman, visual-kei stage outfit, gothic jacket, layered skirt, platform boots"),
("军装风礼服","adult woman, military-inspired formal dress, epaulettes, decorative cords, knee-high boots"),
("空姐风制服","adult woman, flight-attendant inspired uniform, fitted blazer, pencil skirt, neck scarf"),
]

DETAILS = [
("伸出舌头","tongue out, playful expression"),
("舌尖轻舔上唇","tongue lightly touching upper lip, playful non-explicit expression"),
("嘴角少量口水","small strand of drool at the corner of the mouth, dazed expression, non-explicit"),
("轻微喘息般张嘴","softly parted lips as if catching breath, non-explicit"),
("单眼黑色眼罩","black eyepatch over one eye"),
("医疗白色眼罩","white medical eyepatch over one eye"),
("红色心形眼罩","red heart-shaped eyepatch"),
("蕾丝眼罩","lace-trimmed eyepatch over one eye"),
("花朵装饰眼罩","flower-decorated eyepatch"),
("机械金属眼罩","metal mechanical eyepatch"),
("黑色蒙眼布","black blindfold covering both eyes, fashion editorial"),
("半透明蕾丝蒙眼","semi-sheer lace blindfold, tasteful fashion accessory"),
("魅魔风下腹魔纹","decorative succubus-inspired fantasy sigil tattoo on the lower abdomen, non-explicit"),
("锁骨恶魔翅膀纹身","small demonic-wing tattoo near the collarbone"),
("大腿外侧魔法纹章","ornamental fantasy magic sigil tattoo on outer thigh"),
("后腰小型魔纹","small ornamental fantasy sigil tattoo on lower back"),
("单手OK手势放在眼前","ok sign over eye, playful hand gesture"),
("双手OK手势","double ok sign, playful hand gesture"),
("手在嘴边做OK框","one hand making an ok-sign frame beside the mouth, playful non-explicit gesture"),
("腋下附近比耶","v sign held near raised armpit, playful fashion pose"),
("手指在眼旁比耶","v over eye, playful pose"),
("双手在脸旁比耶","double v signs beside face"),
("手指轻拉下眼睑","finger gently pulling down lower eyelid, teasing expression"),
("一只手捂嘴轻笑","one hand covering mouth, restrained amused expression"),
("手背贴额头","back of hand resting against forehead, dramatic pose"),
("双手在头顶比爱心","arms forming a heart above head"),
("单手托胸下方但保持遮挡","one hand supporting below the bust through clothing, fully covered, fashion pose"),
("抬起手臂展示腋下线条","one arm raised, presenting armpit in a tasteful fashion pose"),
("咬住手套指尖","gently biting the fingertip of a glove, theatrical non-explicit gesture"),
("嘴里叼着发圈","holding a hair tie between lips while tying hair"),
]

POSES = [
("鸭子坐 / W坐姿","wariza, w-sitting, knees bent inward with feet beside the hips"),
("正座","seiza, formal kneeling posture, sitting on heels"),
("侧坐鸭子腿","side-sitting with both folded legs angled to one side"),
("女牛仔式坐姿 · 非性行为","cowgirl-inspired seated straddle pose on a chair, fully clothed, fashion editorial, non-sexual"),
("反向女牛仔式椅子坐姿 · 非性行为","reverse straddle sitting on a chair facing the chair back, fully clothed, non-sexual editorial pose"),
("跨坐椅背","straddling a chair backwards, arms resting on the chair back, fully clothed"),
("Jack-O挑战式拉伸 · 穿着完整","jack-o challenge inspired deep forward stretch, hips raised, fully clothed athletic flexibility pose"),
("猫伸懒腰姿势","cat-like stretching pose on hands and knees, arched back, fully clothed"),
("跪趴前伸","kneeling with upper body stretched forward and arms extended, yoga-like pose"),
("婴儿式瑜伽姿势","child's-pose yoga stretch, hips toward heels, arms extended, adult woman"),
("眼镜蛇式抬起上身","cobra yoga pose, lying prone and lifting upper body with arms"),
("桥式抬腰","bridge pose, lying on back with knees bent and hips raised, athletic yoga pose"),
("单腿鸽子式","pigeon yoga pose with one leg folded forward and the other extended back"),
("一字马侧面构图","side split, athletic flexibility pose, fully clothed"),
("竖叉伸展","front split, athletic flexibility pose, fully clothed"),
("抱膝蹲坐","squatting while hugging knees, compact pose"),
("亚洲蹲回头","deep squat, heels down, looking back toward viewer"),
("单膝跪地抬头","one-knee kneeling pose, looking upward"),
("双膝跪地双手举高","kneeling on both knees with both arms raised overhead"),
("仰躺双腿抬起交叉","lying on back with legs raised and crossed at the ankles, fully clothed"),
("侧卧抬起一条腿","lying on one side with one leg raised, athletic editorial pose"),
("趴卧双脚在身后交叉","lying on stomach with feet crossed behind, chin resting on hands"),
("靠墙抬起一腿","leaning against a wall with one leg bent and raised"),
("坐在地上双腿打开成V形","sitting on floor with legs extended in a wide V, athletic stretch, fully clothed"),
("桌面边缘跨坐","sitting astride the edge of a bench, fully clothed, fashion editorial"),
("跪在沙发上前倾","kneeling on a sofa and leaning forward on the backrest, fully clothed"),
("背对镜头弯腰整理鞋子","back facing camera, bending forward to adjust footwear, fully clothed"),
("一手扶墙身体扭转","one hand against a wall, torso twisting into an S-curve"),
("双臂举起绑头发","both arms raised while tying hair, presenting armpits naturally"),
("双手在背后交握前倾","hands clasped behind back while leaning forward toward viewer"),
("蹲坐并用手指比OK遮一只眼","squatting with ok sign over one eye, playful pose"),
("坐姿张嘴手在嘴边比OK","seated pose, softly open mouth, ok sign beside the mouth, playful non-explicit gesture"),
]


def append_items(text, key, items):
    pat = re.compile(rf"(  {re.escape(key)}: \[\n)(.*?)(\n  \],)", re.S)
    m = pat.search(text)
    if not m:
        raise RuntimeError(f"pool not found: {key}")
    body = m.group(2)
    existing = set(re.findall(r'^    \["([^"]+)"', body, re.M))
    additions = []
    for label, prompt in items:
        if label not in existing:
            additions.append(f'    ["{label}","{prompt}"]')
    if not additions:
        return text, 0
    body = body.rstrip()
    if not body.endswith(','):
        body += ','
    body += "\n" + ",\n".join(additions)
    return text[:m.start()] + m.group(1) + body + m.group(3) + text[m.end():], len(additions)

for path in FILES:
    s = path.read_text(encoding="utf-8")
    # Strong adult-only invariant because this expanded wardrobe includes school-inspired cosplay.
    s = s.replace("1girl, solo, young adult woman,", "1girl, solo, clearly adult woman, age 20+,", 1)
    s = s.replace("round eyes, wide open eyes, huge sparkling eyes,", "round eyes, wide open eyes, huge sparkling eyes,\nchild, teen, teenage, underage, loli, elementary school student, middle school student,", 1)
    s, a = append_items(s, "special_outfit", OUTFITS)
    s, b = append_items(s, "special_prompt", DETAILS)
    s, c = append_items(s, "special_pose", POSES)
    path.write_text(s, encoding="utf-8")
    print(path.name, "outfits+", a, "details+", b, "poses+", c)
