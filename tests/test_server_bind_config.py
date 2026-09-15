import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_panel_bind_can_be_restricted_to_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_BIND", "127.0.0.1")
    monkeypatch.setenv("PANEL_DIR", str(tmp_path))
    module_name = "server_bind_config_panel"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert module.BIND_HOST == "127.0.0.1"
    finally:
        sys.modules.pop(module_name, None)

