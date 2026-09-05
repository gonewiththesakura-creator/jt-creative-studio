import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
SPEC = importlib.util.spec_from_file_location("cold_style_branch_runtime", ROOT / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def make_job(preset, mode="original"):
    return {
        "id": f"cold-{mode}",
        "workflow": "anima02",
        "prompt": "adult man, black hair, long coat, rainy city street",
        "negative_prompt": "text, watermark, signature",
        "trigger": preset["trigger"],
        "width": 768,
        "height": 1024,
        "batch": 1,
        "hd": 0,
        "seed": 24681357,
        "loras": {"LORA1": preset["LORA1"], "LORA2": preset["LORA2"]},
        "lora_strengths": dict(preset["strengths"]),
        "style_id": "cold",
        "style_variant": preset["id"],
        "mode": mode,
        "prompt_ids": [],
        "progress_pct": 0,
    }


def cloud_fields(job):
    return {(row["nodeId"], row["fieldName"]): row["fieldValue"]
            for row in server.rh_build_node_info(job)}


def test_cold_keeps_existing_bound_branch_exactly():
    preset = server.resolve_style_preset("cold", "character_bound")
    assert preset == {
        "id": "character_bound",
        "trigger": "jt_style3_v2",
        "LORA1": "05_style3_v2_step1600.safetensors",
        "LORA2": "04_style3_step800.safetensors",
        "strengths": {"LORA1": 0.7, "LORA2": 0.6},
    }


def test_cold_style_only_uses_clean_v2_candidate_and_never_old_v1_lora():
    preset = server.resolve_style_preset("cold", "style_only")
    serialized = json.dumps(preset, ensure_ascii=False)
    assert preset["id"] == "style_only"
    assert preset["trigger"] == "jt_style3_v2"
    assert preset["LORA1"] == "05_style3_v2_step1600.safetensors"
    assert preset["LORA2"] == "05_style3_v2_step1600.safetensors"
    assert preset["strengths"] == {"LORA1": 0.6, "LORA2": 0.0}
    assert "04_style3_step800" not in serialized
    assert "jt_style3_v1" not in serialized


def test_cold_style_only_cloud_and_local_apply_same_single_effective_lora():
    preset = server.resolve_style_preset("cold", "style_only")
    job = make_job(preset)
    fields = cloud_fields(job)
    assert fields[("7", "lora_name")] == "05_style3_v2_step1600.safetensors"
    assert fields[("8", "lora_name")] == "05_style3_v2_step1600.safetensors"
    assert fields[("7", "strength_model")] == 0.6
    assert fields[("8", "strength_model")] == 0.0
    assert fields[("4", "text")].count("jt_style3_v2") == 1

    api = server.build_api(
        "anima02", job["prompt"], job["width"], job["height"], job["batch"],
        job["hd"], job["seed"],
        {key: server.local_lora_name(value) for key, value in job["loras"].items()},
        job["trigger"], False, job["negative_prompt"],
        lora_strengths=job["lora_strengths"],
    )
    assert api["70"]["inputs"]["lora_name"] == "Anima_JT\\05_style3_v2_step1600.safetensors"
    assert api["71"]["inputs"]["lora_name"] == "Anima_JT\\05_style3_v2_step1600.safetensors"
    assert api["70"]["inputs"]["strength_model"] == 0.6
    assert api["71"]["inputs"]["strength_model"] == 0.0
    assert api["4"]["inputs"]["text"].count("jt_style3_v2") == 1


@pytest.mark.parametrize("variant", ["character_bound", "style_only"])
@pytest.mark.parametrize("mode", ["original", "character"])
def test_cold_all_four_variant_mode_combinations_are_valid(variant, mode):
    preset = server.resolve_style_preset("cold", variant)
    job = make_job(preset, mode)
    fields = cloud_fields(job)
    assert fields[("4", "text")].count("jt_style3_v2") == 1
    assert job["mode"] == mode
    assert job["style_variant"] == variant


def test_invalid_cold_variant_is_rejected_instead_of_falling_back_silently():
    with pytest.raises(ValueError, match="unknown style_variant"):
        server.resolve_style_preset("cold", "attacker-variant")
