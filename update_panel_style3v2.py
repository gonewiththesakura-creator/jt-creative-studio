"""更新控制面板：1) 3号画风 LoRA 切到 jt_style3_v2；2) 新增 anima08 无LoRA无翻译工作流。"""
import json, pathlib

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
TPL = BASE / "templates"
CFG = BASE / "config.json"

NEG = "different person, changed identity, wrong subject count, deformed face, malformed anatomy, extra fingers, extra limbs, blurry, low quality, text, watermark, signature, jpeg artifacts"

# ---------- 1) 生成 anima08 模板（无 LoRA、无 LLM 翻译） ----------
def hd_branch(base_src):
    return {
        "13": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-ClearRealityV1.pth"}},
        "14": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": [base_src, 0]}},
        "15": {"class_type": "ImageScaleBy", "inputs": {"image": ["14", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
        "16": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "17": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["16", 0], "image": [base_src, 0]}},
        "18": {"class_type": "ImageScaleBy", "inputs": {"image": ["17", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
        "19": {"class_type": "easy imageIndexSwitch", "inputs": {"index": "{{HD}}", "image0": [base_src, 0], "image1": ["15", 0], "image2": ["18", 0]}},
    }

t08 = {}
t08["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "Anima\\anima-base-v1.0.safetensors", "weight_dtype": "default"}}
t08["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": "Anima\\qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}}
t08["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": "Anima\\qwen_image_vae.safetensors"}}
t08["8"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}}
t08["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "{{PROMPT}}", "clip": ["2", 0]}}  # 直接输入，无 LLM
t08["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}}
t08["6"] = {"class_type": "EmptyLatentImage", "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}", "batch_size": "{{BATCH}}"}}
t08["9"] = {"class_type": "KSampler", "inputs": {"model": ["8", 0], "positive": ["4", 0], "negative": ["5", 0],
           "latent_image": ["6", 0], "seed": "{{SEED}}", "steps": 28, "cfg": 4.0,
           "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
t08["10"] = {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}}
t08.update(hd_branch("10"))
t08["11"] = {"class_type": "SaveImage", "inputs": {"images": ["19", 0], "filename_prefix": "{{PREFIX}}"}}

bad = [(nid, k, v[0]) for nid, node in t08.items() for k, v in node.get("inputs", {}).items() if isinstance(v, list) and v[0] not in t08]
(TPL / "anima08.json").write_text(json.dumps(t08, ensure_ascii=False, indent=1), encoding="utf-8")
print("anima08.json: nodes=", len(t08), "broken=", bad)

# ---------- 2) 更新 config.json ----------
cfg = json.loads(CFG.read_text(encoding="utf-8"))
for w in cfg["workflows"]:
    wid = w["id"]
    # 3号画风 LoRA 默认值 + 触发词 切换
    if wid in ("anima02", "anima04", "anima07"):
        for l in w.get("loras", []):
            if "04_style3_step800" in l.get("default", ""):
                l["default"] = "Anima_JT\\05_style3_v2_step1300.safetensors"
        if w.get("trigger_default"):
            w["trigger_default"] = w["trigger_default"].replace("jt_style3_v1", "jt_style3_v2")
        if "jt_style3_v1" in w.get("desc", ""):
            w["desc"] = w["desc"].replace("jt_style3_v1", "jt_style3_v2").replace("04_style3_step800", "05_style3_v2_step1300")

# 新增 anima08
anima08 = {
    "id": "anima08",
    "name": "Anima Base · 纯提示词生图（无LoRA无翻译）",
    "prompt_default": "1girl, black hair, school uniform, standing, city street at night, detailed, anime style",
    "needs_ollama": False,
    "loras": [],
    "trigger_default": None,
    "size_mode": "native",
    "size_presets": [
        {"label": "默认 768×1024", "w": 768, "h": 1024},
        {"label": "1:1 方图", "w": 1024, "h": 1024},
        {"label": "3:4 竖图", "w": 768, "h": 1024},
        {"label": "4:3 横图", "w": 1024, "h": 768},
        {"label": "9:16 竖长图", "w": 768, "h": 1360},
        {"label": "16:9 宽屏", "w": 1360, "h": 768},
    ],
    "batch_mode": "sequential",
    "batch_max": 4,
    "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
    "speed": "约1-2分钟/张",
    "ref": "无（纯文字生成，直接英文提示词）",
    "desc": "Anima Base 28步 CFG4，无LoRA无翻译，直接英文提示词",
    "template": "anima08.json",
}
cfg["workflows"].append(anima08)

CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
print("config.json updated:", len(cfg["workflows"]), "workflows")
for w in cfg["workflows"]:
    mark = "  <-- 新" if w["id"] == "anima08" else ""
    print(" -", w["id"], "|", w["name"][:24], "| trigger:", w.get("trigger_default"), mark)
