import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_FIXTURE = ROOT / "tests" / "fixtures" / "uploaded_workflow_provenance.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf8"))
BY_ID = {item["id"]: item for item in CONFIG["workflows"]}

SOURCES = {
    "h3_edit_n": {
        "name": "N无限制 视频编辑-Minnimax-H3",
        "editor_id": "2098341535964643329",
        "run_id": "2098330246185926657",
        "kind": "video",
        "media": {"reference_image": ("293", "image", True), "source_video": ("275", "video", True)},
        "params": {"prompt": ("244", "text"), "duration": ("247", "value"), "short_edge": ("251", "value"), "seed": ("222", "noise_seed")},
    },
    "h3_edit_t3": {
        "name": "MinimaxH3视频编辑T3",
        "editor_id": "2098341701604966401",
        "run_id": "2098330116945457154",
        "kind": "video",
        "media": {"source_video": ("221", "file", True)},
        "params": {"prompt": ("196", "text"), "duration": ("132", "value"), "long_edge": ("234", "value"), "seed": ("129", "noise_seed")},
    },
    "h3_edit_remove": {
        "name": "开源版MinimaxH3视频编辑去除人物去除物品去除元素",
        "editor_id": "2098341695082573826",
        "run_id": "2097937340852727809",
        "kind": "video",
        "media": {"source_video": ("221", "file", True)},
        "params": {"prompt": ("196", "text"), "duration": ("132", "value"), "long_edge": ("234", "value"), "seed": ("129", "noise_seed")},
    },
    "qwen_image_edit_zip": {
        "name": "全能修改图生图",
        "editor_id": "2098345504735592450",
        "run_id": "2097924547454918658",
        "kind": "rh_workflow",
        "media": {"source_image": ("7", "image", True)},
        "params": {"prompt": ("31", "text"), "batch": ("71", "value"), "seed": ("2", "seed")},
    },
    "wan_action_stabilized": {
        "name": "动作迁移，抖动优化",
        "editor_id": "2098345513989357570",
        "run_id": "2097924526817800193",
        "kind": "video",
        "media": {"reference_image": ("1031", "image", True), "driving_video": ("1075", "video", True)},
        "params": {"prompt": ("1062", "positive_prompt"), "duration": ("1063", "value"), "width": ("1049", "value"), "height": ("1050", "value"), "jitter": ("1072", "value"), "seed": ("1036", "seed")},
    },
    "scail2_action_replace": {
        "name": "最强动作迁移，角色替换",
        "editor_id": "2098345531529936898",
        "run_id": "2097870206308147201",
        "kind": "video",
        "media": {"reference_image": ("360", "image", True), "reference_image_2": ("639", "image", False), "reference_image_3": ("643", "image", False), "reference_image_4": ("647", "image", False), "driving_video": ("349", "video", True)},
        "params": {"prompt": ("344", "text"), "replace_target": ("686", "text"), "replacement_mode": ("201", "value"), "duration": ("347", "value"), "long_edge": ("473", "value"), "people": ("498", "value"), "seed": ("479", "seed")},
    },
}


def provenance():
    return json.loads(PROVENANCE_FIXTURE.read_text(encoding="utf8"))


def digest(name, api=False):
    key = "api_sha256" if api else "editor_sha256"
    return provenance()[name][key]


def test_uploaded_workflow_provenance_is_repo_relative_and_portable():
    assert ROOT == Path(__file__).resolve().parents[1]
    assert PROVENANCE_FIXTURE.is_file()
    assert PROVENANCE_FIXTURE.resolve().is_relative_to(ROOT.resolve())
    raw = PROVENANCE_FIXTURE.read_text(encoding="utf8")
    assert "api/" not in raw
    assert "\\\\" not in raw
    assert not any(
        isinstance(value, str) and len(value) > 2 and value[1:3] in {":/", ":\\"}
        for record in provenance().values()
        for value in record.values()
    )


def test_six_downloaded_workflows_are_registered_with_exact_chrome_provenance():
    for workflow_id, source in SOURCES.items():
        item = BY_ID[workflow_id]
        assert item["backend"] == "runninghub"
        assert item["kind"] == source["kind"]
        assert item["rh_workflow_id"] == source["run_id"]
        assert item["source_editor_workflow_id"] == source["editor_id"]
        assert item["source_editor_json_sha256"] == digest(source["name"])
        assert item["source_api_json_sha256"] == digest(source["name"], api=True)
        assert item["rh_schema_complete"] is True


def test_only_verified_business_inputs_are_exposed_with_exact_nodes():
    forbidden = {"model", "unet", "vae", "clip", "lora", "steps", "cfg", "sampler", "scheduler", "denoise", "device", "workflow_id", "node_id"}
    for workflow_id, source in SOURCES.items():
        item = BY_ID[workflow_id]
        assert set(item["rh_media"]) == set(source["media"])
        assert set(item["rh_params"]) == set(source["params"])
        for key, (node, field, required) in source["media"].items():
            mapping = item["rh_media"][key]
            assert (mapping["node"], mapping["field"], mapping["required"]) == (node, field, required)
        for key, (node, field) in source["params"].items():
            mapping = item["rh_params"][key]
            assert (mapping["node"], mapping["field"]) == (node, field)
            assert not forbidden.intersection({key.lower(), mapping.get("label", "").lower()})


def test_image_edit_is_in_realism_and_other_five_are_in_video_scope():
    assert BY_ID["qwen_image_edit_zip"]["kind"] == "rh_workflow"
    assert all(BY_ID[key]["kind"] == "video" for key in SOURCES if key != "qwen_image_edit_zip")


def test_optional_scail_reference_slots_fall_back_to_main_image_not_author_samples():
    workflow = BY_ID["scail2_action_replace"]
    for key in ("reference_image_2", "reference_image_3", "reference_image_4"):
        assert workflow["rh_media"][key]["fallback_to"] == "reference_image"


def test_known_strict_visual_failures_are_disclosed_in_the_workflow_ui():
    notices = {
        "h3_edit_remove": "实验性质量提醒：实测人物快速抬手时可能出现手部模糊，请先用短片核对主视频。",
        "scail2_action_replace": "实验性质量提醒：实测角色替换在快速过渡帧可能出现单帧重影，请先用短片核对主视频。",
    }
    for workflow_id, notice in notices.items():
        assert notice in BY_ID[workflow_id].get("fixed_features", [])
