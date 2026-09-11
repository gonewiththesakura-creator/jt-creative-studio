import importlib.util
from pathlib import Path

ROOT = Path(r"D:/LAN-Share/lora/_work/comfy_panel")
spec = importlib.util.spec_from_file_location("hd_prune_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def build(hd):
    return server.build_api(
        "anima02", "adult woman, portrait", 768, 1024, 1, hd, 321321,
        {"LORA1": "Anima_JT\\09_style321_v1_step200.safetensors",
         "LORA2": "Anima_JT\\09_style321_v1_step200.safetensors"},
        "jt_style321_v1", False, "text, watermark",
        lora_strengths={"LORA1": 0.4, "LORA2": 0.0},
    )


def class_types(api):
    return [node["class_type"] for node in api.values()]


def test_hd_off_prunes_all_upscale_work():
    api = build(0)
    classes = class_types(api)
    assert "easy imageIndexSwitch" not in classes
    assert "UpscaleModelLoader" not in classes
    assert "ImageUpscaleWithModel" not in classes
    assert "ImageScaleBy" not in classes
    assert api["11"]["inputs"]["images"] == ["10", 0]


def test_clearreality_keeps_only_selected_upscale_chain():
    api = build(1)
    classes = class_types(api)
    assert "easy imageIndexSwitch" not in classes
    assert classes.count("UpscaleModelLoader") == 1
    assert classes.count("ImageUpscaleWithModel") == 1
    assert classes.count("ImageScaleBy") == 1
    assert api["13"]["inputs"]["model_name"] == "4x-ClearRealityV1.pth"
    assert api["11"]["inputs"]["images"] == ["15", 0]


def test_ultrasharp_keeps_only_selected_upscale_chain():
    api = build(2)
    classes = class_types(api)
    assert "easy imageIndexSwitch" not in classes
    assert classes.count("UpscaleModelLoader") == 1
    assert classes.count("ImageUpscaleWithModel") == 1
    assert classes.count("ImageScaleBy") == 1
    assert api["16"]["inputs"]["model_name"] == "4x-UltraSharp.pth"
    assert api["11"]["inputs"]["images"] == ["18", 0]


def test_pruning_preserves_unrelated_upscale_nodes():
    api = {
        "10": {"class_type": "Source", "inputs": {}},
        "13": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "a.pth"}},
        "14": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": ["10", 0]}},
        "19": {"class_type": "easy imageIndexSwitch", "inputs": {"index": 0, "image0": ["10", 0], "image1": ["14", 0], "image2": ["10", 0]}},
        "20": {"class_type": "SaveImage", "inputs": {"images": ["19", 0]}},
        "90": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "unrelated.pth"}},
        "91": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["90", 0], "image": ["10", 0]}},
        "92": {"class_type": "SaveImage", "inputs": {"images": ["91", 0]}},
    }
    result = server.prune_hd_switch_branches(api, 0)
    assert {"90", "91", "92"}.issubset(result)
    assert "13" not in result and "14" not in result and "19" not in result


def test_pruning_preserves_an_unselected_branch_used_by_another_output():
    api = {
        "10": {"class_type": "Source", "inputs": {}},
        "13": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "shared.pth"}},
        "14": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["13", 0], "image": ["10", 0]}},
        "19": {"class_type": "easy imageIndexSwitch", "inputs": {"index": 0, "image0": ["10", 0], "image1": ["14", 0], "image2": ["10", 0]}},
        "20": {"class_type": "SaveImage", "inputs": {"images": ["19", 0]}},
        "92": {"class_type": "SaveImage", "inputs": {"images": ["14", 0]}},
    }
    result = server.prune_hd_switch_branches(api, 0)
    assert "19" not in result
    assert result["20"]["inputs"]["images"] == ["10", 0]
    assert {"13", "14", "92"}.issubset(result)
    assert result["92"]["inputs"]["images"] == ["14", 0]
