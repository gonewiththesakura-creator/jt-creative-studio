"""Resume-safe blinded counterfactual A/B for cold style-only candidate."""
from __future__ import annotations

import copy
import json
import random
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8188"
ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel/audit/cold_style_ab")
ROOT.mkdir(parents=True, exist_ok=True)
MANIFEST = ROOT / "manifest.json"
UNBLIND = ROOT / "unblind.json"
OUTPUT_ROOT = Path(r"D:/ComfyUI_Mie/ComfyUI/output")

SEEDS = [314159, 271828, 161803]
CONDITIONS = [
    {"id": "base", "lora_strength": None},
    {"id": "lora_04", "lora_strength": 0.4},
    {"id": "lora_06", "lora_strength": 0.6},
]
labels = ["A", "B", "C"]
random.Random(20260905).shuffle(labels)
LABEL_BY_CONDITION = {condition["id"]: labels[index] for index, condition in enumerate(CONDITIONS)}
CONDITION_BY_LABEL = {label: condition for condition, label in zip(CONDITIONS, labels)}

SCENES = [
    {
        "id": "adult_man",
        "width": 768,
        "height": 1024,
        "prompt": "jt_style3_v2, one adult man age 35, masculine mature face, short black hair, brown eyes, full body, charcoal long coat, rainy modern city street, hands visible, mature proportions",
        "negative": "child, teenager, young-looking, text, watermark, signature, logo, malformed anatomy, deformed face, extra fingers, extra limbs, blurry, low quality",
    },
    {
        "id": "different_adult_woman",
        "width": 768,
        "height": 1024,
        "prompt": "jt_style3_v2, one adult woman age 35, mature face, long dark brown curly hair, green eyes, olive tailored suit, full body, sunlit botanical library, hands visible, mature proportions, distinctly different person",
        "negative": "child, teenager, young-looking, text, watermark, signature, logo, malformed anatomy, deformed face, extra fingers, extra limbs, blurry, low quality",
    },
    {
        "id": "two_adults",
        "width": 1024,
        "height": 768,
        "prompt": "jt_style3_v2, two adults age 35, one Black adult man with shaved hair and one East Asian adult woman with long auburn hair, talking at a cafe table, distinct faces, both pairs of hands visible, medium wide shot, mature proportions",
        "negative": "child, teenager, young-looking, same face, duplicate person, text, watermark, signature, logo, malformed anatomy, deformed face, extra fingers, extra limbs, blurry, low quality",
    },
    {
        "id": "empty_town",
        "width": 1024,
        "height": 768,
        "prompt": "jt_style3_v2, empty fantasy town at sunset, wet cobblestone street, old stone buildings, warm window lights, no humans, no characters, no people, wide establishing shot",
        "negative": "person, human, character, face, child, text, watermark, signature, logo, blurry, low quality",
    },
]


def request_json(path: str, payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def graph(scene, seed, strength, prefix):
    model_link = ["1", 0]
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "Anima\\anima-base-v1.0.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "Anima\\qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "Anima\\qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": scene["prompt"]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": scene["negative"]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": scene["width"], "height": scene["height"], "batch_size": 1}},
    }
    if strength is not None:
        workflow["7"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "Anima_JT\\05_style3_v2_step1600.safetensors", "strength_model": strength}}
        model_link = ["7", 0]
    workflow.update({
        "8": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model_link, "shift": 3.0}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["8", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": seed, "steps": 28, "cfg": 4.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    })
    return workflow


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "seeds": SEEDS, "scenes": SCENES, "items": []}


def save_manifest(manifest):
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    queue = request_json("/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise SystemExit("ComfyUI queue is not empty; refusing to mix the audit with another run")
    UNBLIND.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "same_prompt_including_trigger_for_all_conditions": True,
        "labels": CONDITION_BY_LABEL,
        "sampling": {"steps": 28, "cfg": 4.0, "sampler": "euler", "scheduler": "simple", "shift": 3.0},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = load_manifest()
    done = {(item["scene"], item["blind_label"], item["seed"]) for item in manifest["items"] if item.get("status") == "success" and Path(item.get("absolute_path", "")).exists()}
    total = len(SCENES) * len(CONDITIONS) * len(SEEDS)
    for scene in SCENES:
        for condition in CONDITIONS:
            blind = LABEL_BY_CONDITION[condition["id"]]
            for seed in SEEDS:
                key = (scene["id"], blind, seed)
                if key in done:
                    print("SKIP", key, flush=True)
                    continue
                prefix = f"cold_style_ab/{scene['id']}/{blind}_{seed}"
                started = time.time()
                try:
                    response = request_json("/prompt", {"prompt": graph(scene, seed, condition["lora_strength"], prefix)}, timeout=90)
                    prompt_id = response["prompt_id"]
                    print("SUBMITTED", scene["id"], blind, seed, prompt_id, flush=True)
                    result = None
                    deadline = time.time() + 1200
                    while time.time() < deadline:
                        time.sleep(3)
                        history = request_json("/history/" + prompt_id, timeout=60)
                        if prompt_id in history:
                            result = history[prompt_id]
                            break
                    if result is None:
                        raise TimeoutError("generation timed out after 1200 seconds")
                    status = (result.get("status") or {}).get("status_str")
                    if status != "success":
                        raise RuntimeError(json.dumps(result.get("status"), ensure_ascii=False)[:2000])
                    outputs = []
                    for node_id, node_output in (result.get("outputs") or {}).items():
                        for image in node_output.get("images", []):
                            path = OUTPUT_ROOT / image.get("subfolder", "") / image["filename"]
                            outputs.append({"node_id": node_id, "filename": image["filename"], "subfolder": image.get("subfolder", ""), "absolute_path": str(path)})
                    if len(outputs) != 1 or not Path(outputs[0]["absolute_path"]).exists():
                        raise RuntimeError("expected one verified output image")
                    item = {"scene": scene["id"], "blind_label": blind, "seed": seed, "prompt_id": prompt_id, "status": "success", "seconds": round(time.time() - started, 2), **outputs[0]}
                except Exception as exc:
                    item = {"scene": scene["id"], "blind_label": blind, "seed": seed, "status": "error", "seconds": round(time.time() - started, 2), "error": f"{type(exc).__name__}: {exc}"}
                    manifest["items"].append(item)
                    save_manifest(manifest)
                    print("ERROR", json.dumps(item, ensure_ascii=False), flush=True)
                    raise
                manifest["items"].append(item)
                save_manifest(manifest)
                complete = sum(row.get("status") == "success" for row in manifest["items"])
                print("DONE", complete, "/", total, item["absolute_path"], flush=True)
    print("AUDIT_COMPLETE", MANIFEST, flush=True)


if __name__ == "__main__":
    main()
