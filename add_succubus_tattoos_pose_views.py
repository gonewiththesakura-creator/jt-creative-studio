from pathlib import Path
import re

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/static")
FILES = [ROOT / "promptgen.html", ROOT / "index.html"]

VIEW_POOL = '''  view_direction: [
    ["无（不添加此部分）",""],
    ["正面正视","front view, facing viewer directly"],
    ["左侧视图","left side view, left profile"],
    ["右侧视图","right side view, right profile"],
    ["正侧面45度","front three-quarter view, 45-degree angle"],
    ["背面后视","back view, viewed from behind"],
    ["背面三分之四","rear three-quarter view, over-the-shoulder angle"],
    ["仰视","low-angle view, camera looking upward"],
    ["极低机位仰视","extreme low-angle view from near ground level"],
    ["俯视","high-angle view, camera looking downward"],
    ["正上方俯视","top-down overhead view"],
    ["平视","eye-level view, camera at subject eye height"],
    ["虫视角","worm's-eye view, dramatic upward perspective"],
    ["鸟瞰视角","bird's-eye view, distant overhead perspective"],
    ["肩后视角","over-the-shoulder view"],
    ["主观视角","first-person point of view, POV framing"],
    ["镜面反射视角","mirror reflection view, subject seen through a mirror"],
    ["荷兰角倾斜视角","dutch angle, tilted camera framing"]
  ],

'''

for path in FILES:
    s = path.read_text(encoding="utf-8")

    # Rename the requested lower-abdomen/lower-back succubus tattoos precisely.
    s = s.replace(
        '["魅魔风下腹魔纹","decorative succubus-inspired fantasy sigil tattoo on the lower abdomen, non-explicit"]',
        '["魅魔淫纹 · 小腹","succubus womb tattoo, symmetrical erotic fantasy crest tattooed on the lower abdomen, adult woman, non-explicit"]'
    )
    s = s.replace(
        '["后腰小型魔纹","small ornamental fantasy sigil tattoo on lower back"]',
        '["魅魔淫纹 · 后腰","succubus lower-back tattoo, symmetrical erotic fantasy crest tattooed above the hips, adult woman, non-explicit"]'
    )
    # Add a combined option if absent.
    marker = '  special_prompt: [\n'
    if "魅魔淫纹 · 小腹与后腰一组" not in s:
        insert_at = s.index(marker) + len(marker)
        s = s[:insert_at] + '    ["魅魔淫纹 · 小腹与后腰一组","matching succubus womb tattoo and symmetrical lower-back erotic fantasy crest, adult woman, non-explicit"],\n' + s[insert_at:]

    # Add requested floor pose to the multi-select special pose pool.
    marker = '  special_pose: [\n'
    if "趴地塌腰抬臀" not in s:
        insert_at = s.index(marker) + len(marker)
        s = s[:insert_at] + '    ["趴地塌腰抬臀","adult woman lying prone on the floor, chest lowered, waist deeply arched, hips raised, fully clothed, suggestive fashion pose, non-explicit"],\n' + s[insert_at:]

    # Add a dedicated mutually-exclusive view-direction pool before the existing camera pool.
    if "  view_direction: [" not in s:
        s = s.replace("  camera: [", VIEW_POOL + "  camera: [", 1)

    # Add UI label and prompt composition.
    s = s.replace(
        'pose:"姿势", camera:"视角 / 机位", scene:"场景", accent:"点缀色"',
        'pose:"姿势", view_direction:"镜头方向", camera:"视角 / 机位", scene:"场景", accent:"点缀色"',
        1,
    )
    s = s.replace(
        '${state.pose[1]},\n${promptFor("special_pose")},\n${state.camera[1]},',
        '${state.pose[1]},\n${promptFor("special_pose")},\n${state.view_direction[1]},\n${state.camera[1]},',
        1,
    )
    s = s.replace(
        '"special_prompt","pose","special_pose","camera"',
        '"special_prompt","pose","special_pose","view_direction","camera"',
        1,
    )

    path.write_text(s, encoding="utf-8")
    print("updated", path.name)
