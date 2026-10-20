"""Every feature release that restarts the panel runs the full release test gate first.

tools/release_*.py ship server.py's whole module closure, so a hand-picked pytest subset no
longer matches what they publish. They hand their payload to
deploy_realism_release.run_feature_release_gate(), which runs run_release_tests() and then
proves the payload bytes and HEAD did not move during the ~10 minute run, before any
production connection is made.
"""
import ast
import subprocess
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

release = transport.release
SCRIPTS = sorted(TOOLS.glob('release_*.py'))
# Static releases never restart the panel (tests/test_release_scripts_module_graph.py).
STATIC_RELEASES = {'release_admin_entry', 'release_identity_assets', 'release_image_layout',
                   'release_login_scene', 'release_video_ui'}
RUNTIME_RELEASES = [path.stem for path in SCRIPTS if path.stem not in STATIC_RELEASES]


class Connected(Exception):
    pass


def refuse(*args, **kwargs):
    raise AssertionError('release script test reached production')


def source(name):
    return (TOOLS / (name + '.py')).read_text(encoding='utf-8')


def built_on_transaction(name):
    return 'import release_video_queue_plan as transaction' in source(name)


def has_read_only_mode(name):
    return built_on_transaction(name) or "'--execute'" in source(name)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Run a release entrypoint offline until it opens its first production connection."""
    import release_video_queue_plan
    import release_video_queue_presets

    events = []

    def gate(data, normalize, root=release.BASE):
        events.append(('gate', data, normalize))

    def connect(*args, **kwargs):
        events.append(('connect',))
        raise Connected

    monkeypatch.setattr(release, 'run_feature_release_gate', gate)
    monkeypatch.setattr(release, 'run_release_tests', refuse)
    monkeypatch.setattr(transport, '_connect', connect)
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    # Entrypoints reconfigure the shared transactions; restore them for later tests.
    for name in ('MODULES', 'DEFAULT_STATE', 'verify_frontend_scope'):
        monkeypatch.setattr(release_video_queue_plan, name, getattr(release_video_queue_plan, name))
    monkeypatch.setattr(release_video_queue_presets, 'STATE', release_video_queue_presets.STATE)

    def run(name, execute):
        module = import_module(name)
        # Scope checks compare the candidate with HEAD; a committed release is not a candidate.
        for attribute in ('scope', 'verify_scope', 'verify_frontend_scope'):
            if hasattr(module, attribute):
                monkeypatch.setattr(module, attribute, lambda *args: None)
        # Audit state is untracked, so whether it exists depends on the checkout.
        absent = tmp_path / (name + '-absent.json')
        if hasattr(module, 'STATE'):
            monkeypatch.setattr(module, 'STATE', absent)
        argv = [str(TOOLS / (name + '.py'))]
        if execute:
            argv.append('--execute')
        if built_on_transaction(name) or "'--state'" in source(name):
            argv += ['--state', str(absent)]
        monkeypatch.setattr(sys, 'argv', argv)
        with pytest.raises(Connected):
            module.main()
        return events

    return run


@pytest.mark.parametrize('name', RUNTIME_RELEASES)
def test_restarting_release_runs_the_full_gate_before_production(name, offline):
    events = offline(name, execute=True)
    assert [event[0] for event in events] == ['gate', 'connect']
    _, data, normalize = events[0]
    missing = set(release.server_runtime_module_paths()) - set(data)
    assert not missing, 'the gate must re-check the whole published closure: ' + ', '.join(sorted(missing))
    for path, raw in data.items():
        assert normalize(path, (ROOT / path).read_bytes()) == raw, path


@pytest.mark.parametrize('name', [name for name in RUNTIME_RELEASES if has_read_only_mode(name)])
def test_read_only_preflight_does_not_wait_for_the_gate(name, offline):
    assert [event[0] for event in offline(name, execute=False)] == ['connect']


def test_every_restarting_release_defaults_to_a_read_only_preflight():
    # presets and membership_code used to publish on every invocation; since 2026-10-20 they need --execute.
    assert {name for name in RUNTIME_RELEASES if not has_read_only_mode(name)} == set()


def test_presets_preflight_only_reads_production(monkeypatch, capsys):
    import release_video_queue_presets as presets

    class ReadOnlySFTP:
        def open(self, path, mode):
            assert mode == 'rb', 'preflight must not write to production'
            raise FileNotFoundError(path)

        def close(self):
            pass

    class Client:
        def open_sftp(self):
            return ReadOnlySFTP()

        def close(self):
            pass

        def exec_command(self, *args, **kwargs):
            raise AssertionError('preflight must not run remote commands')

    monkeypatch.setattr(release, 'run_feature_release_gate', refuse)
    monkeypatch.setattr(release, 'acquire_release_lock', refuse)
    monkeypatch.setattr(transport, '_connect', lambda *args: Client())
    # Pretend every payload file is new (absent from HEAD), so missing production files are expected.
    monkeypatch.setattr(presets.subprocess, 'run', lambda *args, **kwargs: type('R', (), {'returncode': 1, 'stdout': b''})())
    presets.main(execute=False)
    output = capsys.readouterr().out
    assert '"preflight": "read-only"' in output and 'Pass --execute' in output


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.stem)
def test_release_script_does_not_hand_pick_tests(script):
    tree = ast.parse(script.read_text(encoding='utf-8'))
    picked = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
              and isinstance(node.value, str) and (node.value == 'pytest' or node.value.startswith('tests/'))]
    assert not picked, 'use deploy_realism_release.run_feature_release_gate(): ' + ', '.join(picked)


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=release-test', '-c', 'user.email=release-test@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false', *args],
                          cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'server.py').write_bytes(b'print(1)\n')
    git(tmp_path, 'add', 'server.py')
    git(tmp_path, 'commit', '-qm', 'baseline')
    (tmp_path / 'server.py').write_bytes(b'print(2)\n')
    runs = []

    def gate(during=lambda: None):
        def run_release_tests():
            runs.append(True)
            during()
        monkeypatch.setattr(release, 'run_release_tests', run_release_tests)
        release.run_feature_release_gate({'server.py': b'print(2)\n'},
                                         lambda path, raw: raw.replace(b'\r\n', b'\n'), root=tmp_path)
        return runs

    return tmp_path, gate


def test_gate_runs_the_full_release_tests_once(candidate):
    _, gate = candidate
    assert gate() == [True]


def test_gate_compares_with_the_scripts_own_normalization(candidate):
    root, gate = candidate
    gate(lambda: (root / 'server.py').write_bytes(b'print(2)\r\n'))


def test_gate_rejects_a_candidate_edited_during_the_run(candidate):
    root, gate = candidate
    with pytest.raises(RuntimeError, match='Candidate changed during checks: server.py'):
        gate(lambda: (root / 'server.py').write_bytes(b'print(3)\n'))


def test_gate_rejects_head_moving_during_the_run(candidate):
    root, gate = candidate
    with pytest.raises(RuntimeError, match='HEAD changed while release tests were running'):
        gate(lambda: git(root, 'commit', '-qam', 'moved'))


def test_gate_failure_stops_the_release(candidate):
    _, gate = candidate

    def fail():
        raise RuntimeError('release tests failed: []')

    with pytest.raises(RuntimeError, match='release tests failed'):
        gate(fail)
