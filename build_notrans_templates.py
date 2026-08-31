"""为带翻译LLM的工作流生成 _notrans 直接版模板，并给 config 加 translate_default。"""
import json, copy
from pathlib import Path

BASE = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
TPL = BASE / "templates"
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

LLM_CLASS = "ChinesePromptToEnglishLLM"

def make_notrans(tpl):
    """移除 LLM 节点，把正向 CLIPTextEncode 改成直接文本。"""
    t = copy.deepcopy(tpl)
    # 找 LLM 节点 id
    llm_id = None
    for nid, node in t.items():
        if node.get("class_type") == LLM_CLASS:
            llm_id = nid
            break
    if llm_id is None:
        return None
    # 找引用 LLM 输出的节点（可能是 CLIPTextEncode.text 或 Qwen编码器.prompt 等）
    target_id = None
    target_field = None
    for nid, node in t.items():
        for fld, val in (node.get("inputs", {}) or {}).items():
            if isinstance(val, list) and len(val) == 2 and str(val[0]) == llm_id:
                target_id = nid
                target_field = fld
                break
        if target_id:
            break
    if target_id is None:
        return None
    # 移除 LLM 节点
    del t[llm_id]
    # 正向 prompt/text 改直接
    t[target_id]["inputs"][target_field] = "{{TRIGGER}}, {{PROMPT}}"
    return t

# 需要生成 _notrans 的：模板里含 LLM 节点的
generated = []
for w in CFG["workflows"]:
    tpl_path = TPL / w["template"]
    if not tpl_path.exists():
        continue
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    has_llm = any(n.get("class_type") == LLM_CLASS for n in tpl.values())
    if not has_llm:
        continue
    nt = make_notrans(tpl)
    if nt is None:
        print(f"  跳过 {w['id']}: 找不到 LLM/正向节点")
        continue
    # 无 trigger 的：直接 {{PROMPT}}
    if not w.get("trigger_default"):
        for nid, node in nt.items():
            for fld, val in (node.get("inputs", {}) or {}).items():
                if val == "{{TRIGGER}}, {{PROMPT}}":
                    node["inputs"][fld] = "{{PROMPT}}"
                    break
    stem = w["template"].replace(".json", "")
    out = TPL / f"{stem}_notrans.json"
    out.write_text(json.dumps(nt, ensure_ascii=False, indent=1), encoding="utf-8")
    # 写 translate_default
    w["translate_default"] = True
    generated.append((w["id"], out.name, bool(w.get("trigger_default"))))
    print(f"  生成 {out.name} (trigger={bool(w.get('trigger_default'))})")

# 其余工作流 translate_default = False
for w in CFG["workflows"]:
    if "translate_default" not in w:
        w["translate_default"] = False

(BASE / "config.json").write_text(json.dumps(CFG, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n共生成 {len(generated)} 个 _notrans 模板")
print("config.json 已更新 translate_default")
