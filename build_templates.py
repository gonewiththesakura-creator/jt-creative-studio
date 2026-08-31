"""Build panel API templates from the verified ComfyUI API/editor files.
Outputs templates/*.json with {{PROMPT}} {{WIDTH}} {{HEIGHT}} {{BATCH}} {{HD}} {{SEED}} {{PREFIX}} placeholders.
"""
import json, copy, pathlib, sys

BASE = pathlib.Path(r"D:/LAN-Share/lora/_work/comfy_panel")
TPL = BASE / "templates"
TPL.mkdir(exist_ok=True)

EDITOR_DIR = pathlib.Path(r"D:/ComfyUI_Mie/ComfyUI/user/default/workflows/Anima_JT")

def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))

def editor_nodes(p):
    return load(p)["nodes"]

def api_nodes(p):
    d = load(p)
    return d["nodes"] if "nodes" in d else d  # dict id->node

# ---------- extract exact strings from editors ----------
ed05 = editor_nodes(EDITOR_DIR / "05_Qwen_角色身份换装换场景_推荐.json")
ed06 = editor_nodes(EDITOR_DIR / "06_Qwen2511_双参考低串扰候选.json")
ed07 = editor_nodes(EDITOR_DIR / "07_FLUX2_Klein4B_双参考快速草图候选.json")

def node_by_id(nodes, nid):
    return next(n for n in nodes if n["id"] == nid)

# 05: production Chinese task text (node 21) + English instruction (node 7 last widget)
n21_05 = node_by_id(ed05, 21)["widgets_values"][0]
n7_05 = node_by_id(ed05, 7)["widgets_values"]
instr_05 = n7_05[-1]
print("05 default prompt len:", len(n21_05), "| instruction len:", len(instr_05))

# 06: node 8 widgets [prompt, target_size, vl_size, upscale, crop, instruction...]
w8_06 = node_by_id(ed06, 8)["widgets_values"]
prompt_06, instr_06 = w8_06[0], w8_06[-1]
print("06 default prompt len:", len(prompt_06), "| instruction len:", len(instr_06))

# 07: node 6 widgets [prompt, mode, batch, width, height, ...]
w6_07 = node_by_id(ed07, 6)["widgets_values"]
prompt_07 = w6_07[0]
print("07 default prompt len:", len(prompt_07))

# ---------- 07 template: from the complete known-good API ----------
api07 = api_nodes(r"D:/LAN-Share/lora/_work/flux2_klein4b_local_test/editor07/editor07_chinese_switch0_api.json")
t07 = copy.deepcopy(api07)
t07["6"]["inputs"]["prompt"] = "{{PROMPT}}"
t07["6"]["inputs"]["width"] = "{{WIDTH}}"
t07["6"]["inputs"]["height"] = "{{HEIGHT}}"
t07["6"]["inputs"]["batch_size"] = "{{BATCH}}"
t07["7"]["inputs"]["seed"] = "{{SEED}}"
t07["15"]["inputs"]["index"] = "{{HD}}"
t07["16"]["inputs"]["filename_prefix"] = "{{PREFIX}}"

# ---------- 05 template: known-good API minus LLM node + HD branch ----------
api05 = api_nodes(r"D:/LAN-Share/lora/_work/qwen05_fixed_editor_equivalent_api.json")
t05 = copy.deepcopy(api05)
t05.pop("21", None)  # drop ChinesePromptToEnglishLLM
n7 = t05["7"]["inputs"]
n7.pop("prompt", None)          # was a link from node 21
n7["prompt"] = "{{PROMPT}}"     # direct text now
n7["instruction"] = instr_05
# HD branch (mirror editor nodes 13-19)
t05["13"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-ClearRealityV1.pth"}}
t05["14"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": ["10", 0]}}
t05["15"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["14", 0], "upscale_method": "lanczos", "scale_by": 0.5}}
t05["16"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}}
t05["17"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["16", 0], "image": ["10", 0]}}
t05["18"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["17", 0], "upscale_method": "lanczos", "scale_by": 0.5}}
t05["19"]["inputs"]["index"] = "{{HD}}"
t05["19"]["inputs"]["image1"] = ["15", 0]
t05["19"]["inputs"]["image2"] = ["18", 0]
t05["9"]["inputs"]["seed"] = "{{SEED}}"
t05["11"]["inputs"]["filename_prefix"] = "{{PREFIX}}"

# ---------- 06 template: rebuild API with HD branch from editor ----------
t06 = {
 "1":  {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2511_fp8_e4m3fn_scaled_lightning_comfyui_4steps_v1.0.safetensors", "weight_dtype": "default"}},
 "2":  {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
 "3":  {"class_type": "CFGNorm", "inputs": {"model": ["2", 0], "strength": 1.0}},
 "4":  {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
 "5":  {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
 "6":  {"class_type": "LoadImage", "inputs": {"image": "char3_old_front.png"}},
 "7":  {"class_type": "LoadImage", "inputs": {"image": "char3_old_threequarter.png"}},
 "8":  {"class_type": "TextEncodeQwenImageEditPlusAdvance_lrzjason", "inputs": {
           "prompt": "{{PROMPT}}", "target_size": 1024, "target_vl_size": 384,
           "upscale_method": "lanczos", "crop_method": "disabled", "instruction": instr_06,
           "clip": ["4", 0], "vae": ["5", 0], "vl_resize_image1": ["6", 0], "vl_resize_image2": ["7", 0]}},
 "9":  {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["8", 0]}},
 "10": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["8", 0], "reference_latents_method": "index_timestep_zero"}},
 "11": {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["9", 0], "reference_latents_method": "index_timestep_zero"}},
 "12": {"class_type": "KSampler", "inputs": {"model": ["3", 0], "positive": ["10", 0], "negative": ["11", 0], "latent_image": ["8", 1],
           "seed": "{{SEED}}", "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
 "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["5", 0]}},
 "14": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-ClearRealityV1.pth"}},
 "15": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["14", 0], "image": ["13", 0]}},
 "16": {"class_type": "ImageScaleBy", "inputs": {"image": ["15", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
 "17": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
 "18": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["17", 0], "image": ["13", 0]}},
 "19": {"class_type": "ImageScaleBy", "inputs": {"image": ["18", 0], "upscale_method": "lanczos", "scale_by": 0.5}},
 "20": {"class_type": "easy imageIndexSwitch", "inputs": {"index": "{{HD}}", "image0": ["13", 0], "image1": ["16", 0], "image2": ["19", 0]}},
 "21": {"class_type": "SaveImage", "inputs": {"images": ["20", 0], "filename_prefix": "{{PREFIX}}"}},
}

def check_links(nodes):
    ids = set(nodes.keys())
    bad = []
    for nid, node in nodes.items():
        for k, v in node.get("inputs", {}).items():
            if isinstance(v, list):
                if v[0] not in ids:
                    bad.append((nid, k, v[0]))
    return bad

for name, t in [("05_qwen2509", t05), ("06_qwen2511", t06), ("07_flux4b", t07)]:
    bad = check_links(t)
    out = TPL / f"{name}.json"
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: nodes={len(t)} broken_links={bad} -> {out}")

# ---------- workflow metadata for the panel ----------
config = {
 "workflows": [
  {
   "id": "qwen2509", "name": "Qwen 2509 · 身份换装换场景（生产基线）",
   "desc": "单参考+本地LLM中文理解，8步，约2-3分钟/张",
   "template": "05_qwen2509.json", "prompt_default": n21_05,
   "size_mode": "resize", "size_presets": [{"label": "默认(跟随参考图)", "w": 0, "h": 0}, {"label": "768×1152", "w": 768, "h": 1152}, {"label": "1024×1536", "w": 1024, "h": 1536}],
   "batch_mode": "sequential", "batch_max": 4, "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
   "speed": "约2-3分钟/张", "ref": "char3_best_ref_NEW02.png",
  },
  {
   "id": "qwen2511", "name": "Qwen 2511 · 双参考低串扰",
   "desc": "双参考(正脸+三分之四)，4步，串扰最低，约1.5-3分钟/张",
   "template": "06_qwen2511.json", "prompt_default": prompt_06,
   "size_mode": "resize", "size_presets": [{"label": "默认(跟随参考图)", "w": 0, "h": 0}, {"label": "768×1152", "w": 768, "h": 1152}, {"label": "1024×1536", "w": 1024, "h": 1536}],
   "batch_mode": "sequential", "batch_max": 4, "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
   "speed": "约1.5-3分钟/张", "ref": "char3_old_front + char3_old_threequarter",
  },
  {
   "id": "flux4b", "name": "FLUX.2 Klein 4B · 快速草图",
   "desc": "双参考，4步，约30秒/张，适合快速构图批量出图",
   "template": "07_flux4b.json", "prompt_default": prompt_07,
   "size_mode": "native", "size_presets": [{"label": "840×1256", "w": 840, "h": 1256}, {"label": "768×1152", "w": 768, "h": 1152}, {"label": "1024×1536", "w": 1024, "h": 1536}, {"label": "512×768", "w": 512, "h": 768}],
   "batch_mode": "native", "batch_max": 4, "hd": ["关闭", "ClearReality 极速2×", "UltraSharp 精细2×"],
   "speed": "约30秒/张", "ref": "char3_old_front + char3_old_threequarter",
  },
 ],
 "default_prompt_reset": True,
}
(BASE / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
print("config.json written")
