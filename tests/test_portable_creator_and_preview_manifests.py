import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "build_unified_three_styles.py").read_text(encoding="utf8")
PREVIEW_MANIFEST = ROOT / "static" / "previews" / "manifest.json"
POOL_MANIFEST = ROOT / "sources" / "pool_union_manifest.json"


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)


def is_absolute_machine_path(value):
    return bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/home/", "/Users/")))


def test_released_preview_manifest_has_no_workstation_paths():
    manifest = json.loads(PREVIEW_MANIFEST.read_text(encoding="utf8"))
    assert not any(is_absolute_machine_path(value) for value in all_strings(manifest))
    assert all("source" not in item and "source_sha256" not in item for item in manifest)
    assert all(item.get("output") and item.get("sha256") for item in manifest)


def test_pool_manifest_and_creator_builder_are_repo_relative():
    manifest = json.loads(POOL_MANIFEST.read_text(encoding="utf8"))
    assert not any(is_absolute_machine_path(value) for value in all_strings(manifest.get("sources", {})))
    assert "Path(__file__).resolve().parent" in BUILDER
    assert "C:/Users/" not in BUILDER
    assert "D:/LAN-Share/" not in BUILDER


def test_video_and_preview_builders_do_not_embed_workstation_paths():
    video_builder = (ROOT / "build_video_workbench.py").read_text(encoding="utf-8")
    preview_builder = (ROOT / "tools" / "build_preview_assets.py").read_text(encoding="utf-8")
    for text in (video_builder, preview_builder):
        assert "D:/LAN-Share/" not in text
        assert "C:/Users/JT/" not in text
    assert "Path(__file__).resolve()" in video_builder
    assert "argparse" in preview_builder
    for source in ("cold_promptgen_source.html", "sketch_promptgen_source.html", "graphic_promptgen_source.html"):
        assert (ROOT / "sources" / source).is_file(), source
        assert source in BUILDER
