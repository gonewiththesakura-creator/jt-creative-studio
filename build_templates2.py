"""Build API templates for all 6 Anima-family workflows + update panel config (9 workflows total)."""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
TPL = BASE / "templates"
EDITOR_DIR = pathlib.Path(r"D:/ComfyUI_Mie/ComfyUI/user/default/workflows/Anima_JT")

def load(p): return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

NEG = "different person, changed identity, wrong subject count, deformed face, malformed anatomy, extra fingers, extra limbs, blurry, low quality, text, watermark, signature, jpeg artifacts"
LLM = "qwen3:4b"; OLLAMA = "http://127.0.0.1:11434"
SEED_DEFAULT = 20260802

def llm_node(prompt, usage, trigger, backend="deepseek"):
    if backend == "deepseek":
        return {"class_type": "ChinesePromptToEnglishLLM", "inputs": {
            "中文需求": prompt, "用途": usage, "LoRA触发词": trigger,
            "模型": "deepseek-chat", "随机种子": SEED_DEFAULT,
            "Ollama地址": "http://127.0.0.1:11434",
            "API类型": "OpenAI兼容",
            "API地址": "https://api.deepseek.com/v1",
            "API密钥": ""}}
    return {"class_type": "ChinesePromptToEnglishLLM", "inputs": {
        "中文需求": prompt, "用途": usage, "LoRA触发词": trigger,
        "模型": LLM, "随机种子": SEED_DEFAULT, "Ollama地址": OLLAMA}}

def hd_branch(base_src):
    """Upscale branch nodes 13-19 wired from VAEDecode output base_src."""
    return {
        "13": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-ClearRealityV1.pth"}},
        "14": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": [base_src, 0]}},
        "15": {"class_type": "ImageScaleBy", "inputs": {"image": ["14", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
        "16": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "17": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["16", 0], "image": [base_src, 0]}},
        "18": {"class_type": "ImageScaleBy", "inputs": {"image": ["17", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
        "19": {"class_type": "easy imageIndexSwitch", "inputs": {"index": "{{HD}}", "image0": [base_src, 0], "image1": ["15", 0], "image2": ["18", 0]}},
    }

def anima_txt2img(spec):
    """Generic Anima txt2img template builder. LoRA names and trigger are placeholders."""
    t = {}
    t["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": spec["unet"], "weight_dtype": "default"}}
    prev = "1"
    for i, (lora, strength) in enumerate(spec["loras"]):
        nid = str(70 + i)
        t[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": lora, "strength_model": strength, "model": [prev, 0]}}
        prev = nid
    t["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": "Anima\\qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}}
    t["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": "Anima\\qwen_image_vae.safetensors"}}
    t["8"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": [prev, 0], "shift": 3.0}}
    t["21"] = llm_node("{{PROMPT}}", "Anima生图", "{{TRIGGER}}")
    t["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": ["21", 0], "clip": ["2", 0]}}
    t["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}}
    t["6"] = {"class_type": "EmptyLatentImage", "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}", "batch_size": "{{BATCH}}"}}
    t["9"] = {"class_type": "KSampler", "inputs": {"model": ["8", 0], "positive": ["4", 0], "negative": ["5", 0],
               "latent_image": ["6", 0], "seed": "{{SEED}}", "steps": spec["steps"], "cfg": spec["cfg"],
               "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    t["10"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}}
    t.update(hd_branch("10"))
    t["11"] = {"class_type": "SaveImage", "inputs": {"images": ["19", 0], "filename_prefix": "{{PREFIX}}"}}
    return t

# ---------- extract default prompts from editors ----------
def llm_default(fn):
    nodes = load(EDITOR_DIR / fn)["nodes"]
    for n in nodes:
        if n.get("type") == "ChinesePromptToEnglishLLM":
            return n["widgets_values"][0]

p01 = llm_default("01_Anima_Base_主生产_单LoRA.json")
p02 = llm_default("02_Anima_Base_人物加画风_漫画剧情.json")
p03 = llm_default("03_Anima_Aesthetic_角色特写立绘.json")
p04 = llm_default("04_Anima_Turbo_快速背景分镜.json")
p06 = llm_default("06_Qwen_可选二次身份修正.json")
p07 = llm_default("07_Anima_同构图保脸轻修_d020.json")

templates = {}
templates["anima01"] = anima_txt2img({
    "unet": "Anima\\anima-base-v1.0.safetensors",
    "loras": [("{{LORA1}}", 0.6)],
    "steps": 28, "cfg": 4.0})
templates["anima02"] = anima_txt2img({
    "unet": "Anima\\anima-base-v1.0.safetensors",
    "loras": [("{{LORA1}}", 0.7), ("{{LORA2}}", 0.6)],
    "steps": 28, "cfg": 4.0})
templates["anima03"] = anima_txt2img({
    "unet": "Anima\\anima-aesthetic-v1.1.safetensors",
    "loras": [("{{LORA1}}", 0.65)],
    "steps": 28, "cfg": 4.0})
templates["anima04"] = anima_txt2img({
    "unet": "Anima\\anima-turbo-v1.0.safetensors",
    "loras": [("{{LORA1}}", 0.6)],
    "steps": 10, "cfg": 1.0})

# ---------- 06 Qwen secondary identity correction (dual image) ----------
t06 = {
 "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2509_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
 "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
 "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
 "4": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
 "5": {"class_type": "LoadImage", "inputs": {"image": "char3_best_ref_NEW02.png"}},
 "6": {"class_type": "LoadImage", "inputs": {"image": "char3_best_ref_NEW02.png"}},
 "21": llm_node("{{PROMPT}}", "Qwen身份修正", ""),
 "7": {"class_type": "TextEncodeQwenImageEditPlusAdvance_lrzjason", "inputs": {
         "prompt": ["21", 0], "target_size": 1024, "target_vl_size": 384, "upscale_method": "lanczos",
         "crop_method": "disabled",
         "instruction": "只使用图2校正人物身份；保留图1的构图、服装、姿势、灯光和背景。只允许修改脸部、眼睛、神态、头发轮廓和花饰。",
         "clip": ["3", 0], "vae": ["4", 0], "vl_resize_image1": ["5", 0], "vl_resize_image2": ["6", 0]}},
 "8": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
 "9": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["7", 0], "negative": ["8", 0],
         "latent_image": ["7", 1], "seed": "{{SEED}}", "steps": 8, "cfg": 1.0,
         "sampler_name": "euler", "scheduler": "beta57", "denoise": 1.0}},
 "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["4", 0]}},
}
t06.update(hd_branch("10"))
t06["11"] = {"class_type": "SaveImage", "inputs": {"images": ["19", 0], "filename_prefix": "{{PREFIX}}"}}
templates["qwen06corr"] = t06

# ---------- 07 Anima img2img light retouch (denoise 0.20) ----------
t07 = {
 "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "Anima\\anima-base-v1.0.safetensors", "weight_dtype": "default"}},
 "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "{{LORA1}}", "strength_model": 0.55, "model": ["1", 0]}},
 "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["2", 0], "shift": 3.0}},
 "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": "Anima\\qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
 "5": {"class_type": "VAELoader", "inputs": {"vae_name": "Anima\\qwen_image_vae.safetensors"}},
 "6": {"class_type": "LoadImage", "inputs": {"image": "char3_best_ref_NEW02.png"}},
 "7": {"class_type": "ImageScale", "inputs": {"image": ["6", 0], "upscale_method": "lanczos", "width": 768, "height": 1024, "crop": "disabled"}},
 "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["5", 0]}},
 "21": llm_node("{{PROMPT}}", "Anima生图", "{{TRIGGER}}"),
 "9": {"class_type": "CLIPTextEncode", "inputs": {"text": ["21", 0], "clip": ["4", 0]}},
 "10": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["4", 0]}},
 "11": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["9", 0], "negative": ["10", 0],
         "latent_image": ["8", 0], "seed": "{{SEED}}", "steps": 24, "cfg": 4.0,
         "sampler_name": "euler", "scheduler": "simple", "denoise": 0.2}},
 "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["5", 0]}},
}
t07.update(hd_branch("12"))
t07["99"] = {"class_type": "SaveImage", "inputs": {"images": ["19", 0], "filename_prefix": "{{PREFIX}}"}}
templates["anima07"] = t07

# ---------- write templates ----------
for name, t in templates.items():
    bad = [ (nid, k, v[0]) for nid, node in t.items() for k, v in node.get("inputs", {}).items() if isinstance(v, list) and v[0] not in t ]
    out = TPL / f"{name}.json"
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: nodes={len(t)} broken={bad}")

# ---------- rebuild config with all 9 workflows ----------
old_cfg = load(BASE / "config.json")
old = {w["id"]: w for w in old_cfg["workflows"]}

def resize_cfg(prompt, speed, ref, desc, size_mode="native"):
    return {"size_mode": size_mode,
            "size_presets": [{"label": "默认 768×1024", "w": 768, "h": 1024},
                             {"label": "1:1 方图", "w": 1024, "h": 1024},
                             {"label": "3:4 竖图", "w": 768, "h": 1024},
                             {"label": "4:3 横图", "w": 1024, "h": 768},
                             {"label": "9:16 竖长图", "w": 768, "h": 1360},
                             {"label": "16:9 宽屏", "w": 1360, "h": 768}],
            "batch_mode": "sequential", "batch_max": 4,
            "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
            "speed": speed, "ref": ref, "desc": desc}

new_workflows = [
 {**{"id": "anima01", "name": "Anima Base · 主生产（单LoRA）",
     "prompt_default": p01, "needs_ollama": True,
     "loras": [{"key": "LORA1", "label": "画风 LoRA", "default": "Anima_JT\\02_style2_step900.safetensors", "strength": 0.6}],
     "trigger_default": "jt_softpaint_v1"},
  **resize_cfg(p01, "约1-2分钟/张", "无（纯文字生成）", "2号画风LoRA jt_softpaint_v1 · 28步 · 漫画剧情")},
 {**{"id": "anima02", "name": "Anima Base · 人物加画风（漫画剧情）",
     "prompt_default": p02, "needs_ollama": True,
     "loras": [{"key": "LORA1", "label": "人物 LoRA", "default": "Anima_JT\\03_char3_FAILED_IDENTITY_step1100.safetensors", "strength": 0.7},
               {"key": "LORA2", "label": "画风 LoRA", "default": "Anima_JT\\04_style3_step800.safetensors", "strength": 0.6}],
     "trigger_default": "jt_char3_v1, jt_style3_v1"},
  **resize_cfg(p02, "约2-4分钟/张", "无（纯文字生成）", "人物LoRA(旧失败权重)+3号画风 jt_char3_v1, jt_style3_v1 · 28步")},
 {**{"id": "anima03", "name": "Anima Aesthetic · 角色特写立绘",
     "prompt_default": p03, "needs_ollama": True,
     "loras": [{"key": "LORA1", "label": "人物 LoRA", "default": "Anima_JT\\03_char3_FAILED_IDENTITY_step1100.safetensors", "strength": 0.65}],
     "trigger_default": "jt_char3_v1"},
  **resize_cfg(p03, "约1-2分钟/张", "无（纯文字生成）", "Aesthetic底模+人物LoRA jt_char3_v1 · 28步")},
 {**{"id": "anima04", "name": "Anima Turbo · 快速背景分镜",
     "prompt_default": p04, "needs_ollama": True,
     "loras": [{"key": "LORA1", "label": "画风 LoRA", "default": "Anima_JT\\04_style3_step800.safetensors", "strength": 0.6}],
     "trigger_default": "jt_style3_v1"},
  **resize_cfg(p04, "约15-30秒/张", "无（纯文字生成）", "Turbo底模10步CFG1 + 3号画风 jt_style3_v1 · 最快")},
 {**{"id": "qwen06corr", "name": "Qwen · 可选二次身份修正",
     "prompt_default": p06, "needs_ollama": True},
  "size_mode": "fixed", "size_presets": [], "batch_mode": "sequential", "batch_max": 1,
  "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
  "speed": "约1-2分钟/张", "ref": "图1成片+图2身份参考（固定 input/char3_best_ref_NEW02.png）",
  "desc": "用图2校正图1身份；保留构图服装姿势背景。输入图固定，需先替换 input 同名图"},
 {**{"id": "anima07", "name": "Anima · 同构图保脸轻修 d0.20",
     "prompt_default": p07, "needs_ollama": True,
     "loras": [{"key": "LORA1", "label": "画风 LoRA", "default": "Anima_JT\\04_style3_step800.safetensors", "strength": 0.55}],
     "trigger_default": "jt_style3_v1"},
  "size_mode": "fixed", "size_presets": [], "batch_mode": "sequential", "batch_max": 1,
  "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
  "speed": "约30-60秒/张", "ref": "输入图固定（input/char3_best_ref_NEW02.png）",
  "desc": "img2img denoise 0.20 保脸轻修 + 3号画风 jt_style3_v1；输入图固定，需先替换 input 同名图"},
]

# fix stray quotes in desc strings above (accidental trailing quote chars)
for w in new_workflows:
    w["desc"] = w["desc"].rstrip('"').strip('"')
    if "desc" in w and w["desc"].startswith('"'):
        w["desc"] = w["desc"][1:]

workflows = []
for wid in ["qwen2509", "qwen2511", "flux4b"]:
    w = dict(old[wid])
    w.setdefault("needs_ollama", False)
    workflows.append(w)
workflows += new_workflows

config = {"workflows": workflows, "default_prompt_reset": True}
(BASE / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
print("config.json updated with", len(workflows), "workflows")
for w in workflows:
    print(" -", w["id"], "|", w["name"], "| ollama:", w.get("needs_ollama", False), "| size:", w["size_mode"])
