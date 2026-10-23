"""Every feature release that restarts the panel ships server.py's whole local-module closure.

tools/release_*.py used to hand-write their Python payload (often just server.py), so a
changed sibling such as membership_http.py or result_image_cache.py could stay stale in
production. They now take it from deploy_realism_release.SERVER_RUNTIME_MODULE_PATHS and
hand the final path list to require_server_runtime_modules() before touching production.
"""
import ast
import re
import sys
import urllib.request
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import prepare_dreamapi_native_canary as transport  # noqa: E402

SCRIPTS = sorted(TOOLS.glob('release_*.py'))


@pytest.fixture(autouse=True)
def retired_entry_points_run_offline(monkeypatch):
    """Retired release scripts' main() only runs here, with production calls replaced."""
    import importlib.util as _util
    spec = _util.spec_from_file_location('retired_release', ROOT / 'tools' / 'retired_release.py')
    retired = _util.module_from_spec(spec)
    spec.loader.exec_module(retired)
    retired.OFFLINE_TESTS = True
    monkeypatch.setitem(sys.modules, 'retired_release', retired)
# Reviewed releases of hashed assets, entrypoints or nginx config only. Each asserts the
# panel process is unchanged, so the live process keeps the modules it already imported.
STATIC_RELEASES = {'release_admin_entry', 'release_identity_assets', 'release_image_layout',
                   'release_login_scene', 'release_video_ui'}
RUNTIME_RELEASES = [path.stem for path in SCRIPTS if path.stem not in STATIC_RELEASES]
RESTART = re.compile(r"""systemctl['", ]+(?:start|restart|stop)['", ]+comfy-panel|stop_panel_resilient""")
ROOT_MODULES = {path.name for path in ROOT.glob('*.py')}


class Captured(Exception):
    pass


def refuse(*args, **kwargs):
    raise AssertionError('release script test reached production')


@pytest.fixture
def payloads(monkeypatch, tmp_path):
    """Run a release entrypoint offline up to the moment it hands over its payload paths."""
    import release_membership_code
    import release_video_queue_plan
    import release_video_queue_presets

    calls = []

    def capture(paths, root=None):
        calls.append(list(paths))
        raise Captured

    monkeypatch.setattr(transport.release, 'require_server_runtime_modules', capture)
    monkeypatch.setattr(transport, '_connect', refuse)
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    # Entrypoints reconfigure the shared transactions; restore them for later tests.
    for name in ('MODULES', 'DEFAULT_STATE', 'verify_frontend_scope'):
        monkeypatch.setattr(release_video_queue_plan, name, getattr(release_video_queue_plan, name))
    monkeypatch.setattr(release_video_queue_presets, 'STATE', release_video_queue_presets.STATE)
    # Audit state is untracked, so whether it exists depends on the checkout.
    monkeypatch.setattr(release_membership_code, 'STATE', tmp_path / 'absent.json')
    return calls


def release_sources(name, seen=None):
    """A release script plus every tools/release_*.py it imports, transitively."""
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    for node in ast.walk(ast.parse((TOOLS / (name + '.py')).read_text(encoding='utf-8'))):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
        for imported in names:
            if imported.startswith('release_') and (TOOLS / (imported + '.py')).is_file():
                release_sources(imported, seen)
    return seen


def test_closure_reference_includes_the_previously_missed_modules():
    modules = set(transport.release.server_runtime_module_paths())
    assert {'server.py', 'membership_http.py', 'membership_auth.py', 'membership_store.py',
            'membership_media.py', 'result_image_cache.py', 'video_uploads.py'} <= modules
    assert modules == set(transport.release.SERVER_RUNTIME_MODULE_PATHS)


@pytest.mark.parametrize('name', RUNTIME_RELEASES)
def test_runtime_release_publishes_the_whole_server_module_closure(name, payloads, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(TOOLS / (name + '.py'))])
    with pytest.raises(Captured):
        import_module(name).main()
    assert len(payloads) == 1, 'payload must pass the module-closure guard exactly once'
    paths = payloads[0]
    missing = set(transport.release.server_runtime_module_paths()) - set(paths)
    assert not missing, sorted(missing)
    assert len(paths) == len(set(paths)), 'duplicate payload paths'


@pytest.mark.parametrize('name, payload', [
    ('release_h3_optimized', {'config.json'}),
    ('release_image_edit_playback', {'config.json'}),
    ('release_security_hardening', {'deploy/security/harden_host.py', 'deploy/security/disable_identity_signup.py'}),
    ('release_membership_code', {'requirements-membership.txt', 'tools/migrate_membership_owner.py'}),
    ('release_membership_cutover', {'tools/migrate_membership_owner.py'}),
    ('release_h3_lora_slots', {'config.json', 'video_wf/h3_edit_multi_api.json'}),
])
def test_runtime_release_keeps_its_non_python_payload(name, payload, payloads, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(TOOLS / (name + '.py'))])
    with pytest.raises(Captured):
        import_module(name).main()
    assert payload <= set(payloads[0])


def test_transaction_refuses_a_hand_picked_module_list(monkeypatch):
    import release_video_queue_plan as transaction
    monkeypatch.setattr(transaction, 'MODULES', ('server.py', 'config.json'))
    monkeypatch.setattr(transport, '_connect', refuse)
    with pytest.raises(RuntimeError, match=r'omits server\.py runtime modules: .*membership_http\.py'):
        transaction.main([])


def test_guard_returns_complete_payloads_and_names_every_omission():
    guard = transport.release.require_server_runtime_modules
    paths = ['static/app.html', *transport.release.SERVER_RUNTIME_MODULE_PATHS]
    assert guard(paths) is paths
    with pytest.raises(RuntimeError, match='membership_auth.py, membership_http.py'):
        guard(['server.py', 'membership_store.py', 'config.json'])


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.stem)
def test_release_script_has_no_hand_written_module_list(script):
    tree = ast.parse(script.read_text(encoding='utf-8'))
    listed = [element.value for node in ast.walk(tree) if isinstance(node, (ast.List, ast.Tuple, ast.Set))
              for element in node.elts if isinstance(element, ast.Constant) and element.value in ROOT_MODULES]
    assert not listed, 'derive Python payload from SERVER_RUNTIME_MODULE_PATHS: ' + ', '.join(listed)


@pytest.mark.parametrize('name', sorted(STATIC_RELEASES))
def test_static_release_never_restarts_the_panel(name):
    assert (TOOLS / (name + '.py')).is_file(), 'stale static release entry'
    for source in sorted(release_sources(name)):
        assert not RESTART.search((TOOLS / (source + '.py')).read_text(encoding='utf-8')), source
