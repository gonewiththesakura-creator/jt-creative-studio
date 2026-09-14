import importlib.util
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shlex
import sys
import threading
import time
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "deploy_realism_release.py"


def load_module():
    spec = importlib.util.spec_from_file_location("deploy_release_safety", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_rejects_an_empty_test_directory(tmp_path):
    module = load_module()

    with pytest.raises(RuntimeError, match="no release tests discovered"):
        module.run_release_tests(tmp_path)


@pytest.mark.parametrize(
    "name,source,missing",
    [
        ("test_only_pytest.py", "def test_only():\n    assert True\n", "script contracts"),
        ("test_only_script.py", "raise SystemExit(0)\n", "pytest files"),
    ],
)
def test_release_gate_rejects_an_empty_lane(tmp_path, name, source, missing):
    module = load_module()
    (tmp_path / name).write_text(source, encoding="utf-8")

    with pytest.raises(RuntimeError, match=missing):
        module.run_release_tests(tmp_path)


def test_default_release_gate_locks_the_reviewed_lane_baselines(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "classify_release_tests", lambda test_dir=None: (
        [Path(f"script-{index}.py") for index in range(module.MIN_SCRIPT_CONTRACTS - 1)],
        [Path(f"pytest-{index}.py") for index in range(module.MIN_PYTEST_FILES)],
    ))
    with pytest.raises(RuntimeError, match="inventory shrank"):
        module.run_release_tests()


def test_default_release_gate_rejects_an_equal_size_inventory_substitution(monkeypatch):
    module = load_module()
    scripts, pytest_files = module.classify_release_tests()
    scripts = [*scripts[:-1], scripts[-1].with_name("test_substitute_contract.py")]
    monkeypatch.setattr(module, "classify_release_tests", lambda test_dir=None: (
        scripts, pytest_files,
    ))
    with pytest.raises(RuntimeError, match="inventory differs"):
        module.run_release_tests()


def test_release_source_identity_rejects_a_head_change_after_tests(monkeypatch):
    module = load_module()
    heads = iter(["a" * 40, "b" * 40])

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        if command[1:] == ["status", "--porcelain"]:
            return Result("")
        if command[1:] == ["rev-parse", "HEAD"]:
            return Result(next(heads) + "\n")
        raise AssertionError(command)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    reviewed_head = module.require_clean_git()
    with pytest.raises(RuntimeError, match="HEAD changed while release tests were running"):
        module.require_clean_git(expected_head=reviewed_head)


def test_main_rechecks_the_same_clean_head_after_the_test_gate():
    source = SCRIPT.read_text(encoding="utf-8")
    main = source.split("def main(", 1)[1]

    first = main.index("reviewed_head = require_clean_git()")
    tests = main.index("run_release_tests()", first)
    second = main.index("require_clean_git(expected_head=reviewed_head)", tests)
    files = main.index("files = release_files()", second)
    snapshot = main.index("release_payloads_from_head(files, reviewed_head)", files)
    deploy = main.index("deploy(\n        files, payloads", snapshot)
    assert first < tests < second < files < snapshot < deploy


def test_release_payloads_come_from_the_reviewed_commit(monkeypatch):
    module = load_module()
    local = module.BASE / "server.py"

    class Result:
        returncode = 0
        stdout = b"committed bytes"
        stderr = b""

    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs:
                        calls.append(command) or Result())
    payloads = module.release_payloads_from_head(
        {local: module.REMOTE_ROOT + "/server.py"}, "a" * 40,
    )
    assert payloads == {local: b"committed bytes"}
    assert calls == [["git", "show", "a" * 40 + ":server.py"]]


def test_deploy_never_rereads_mutable_worktree_bytes():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert ".read_bytes()" not in deploy
    assert "payloads[local]" in deploy


@pytest.mark.parametrize("busy_key", ["cloud_busy", "local_busy", "api_busy"])
def test_public_idle_gate_rejects_each_active_backend(monkeypatch, busy_key):
    module = load_module()
    health = {
        "ok": True,
        "cloud_busy": False,
        "local_busy": False,
        "api_busy": False,
    }
    health[busy_key] = True
    monkeypatch.setattr(module, "fetch_json", lambda base, path: health)

    with pytest.raises(RuntimeError, match=busy_key):
        module.require_public_idle("http://panel", phase="pre-stop")


def test_public_idle_gate_fails_closed_when_busy_fields_are_missing(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "fetch_json", lambda base, path: {"ok": True})

    with pytest.raises(RuntimeError, match="invalid health response"):
        module.require_public_idle("http://panel", phase="preflight")


def test_public_idle_gate_does_not_require_the_local_comfy_tunnel(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "fetch_json", lambda base, path: {
        "ok": False, "local_comfy_ok": False,
        "cloud_busy": False, "local_busy": False, "api_busy": False,
    })
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    health = module.require_public_idle("http://panel", phase="preflight")
    assert health["ok"] is False


def test_public_idle_gate_requires_a_stable_idle_window(monkeypatch):
    module = load_module()
    samples = []
    sleeps = []
    monkeypatch.setattr(module, "fetch_json", lambda base, path: samples.append(path) or {
        "ok": True, "cloud_busy": False, "local_busy": False, "api_busy": False,
    })
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = module.require_public_idle("http://panel", phase="preflight")
    assert result["ok"] is True
    assert samples == ["/api/health"] * module.IDLE_STABILITY_CHECKS
    assert sleeps == [module.IDLE_STABILITY_INTERVAL] * (module.IDLE_STABILITY_CHECKS - 1)


def test_deploy_checks_idle_before_connect_isolation_and_stop():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]

    first = deploy.index('require_public_idle(public_base, phase="preflight")')
    metadata_read = deploy.index('creds_path.read_text(encoding="utf-8")', first)
    key_read = deploy.index("paramiko.Ed25519Key.from_private_key_file(", metadata_read)
    connect = deploy.index("client.connect(", first)
    keepalive = deploy.index("configure_ssh_transport(client)", connect)
    acquire = deploy.index("acquire_release_lock(client, transaction)", keepalive)
    prepared = deploy.index('write_transaction_phase(client, transaction, "prepared")', acquire)
    second = deploy.index('require_public_idle(public_base, phase="pre-stop")', prepared)
    start_mark = deploy.index("start_draining_set = True", second)
    start_drain = deploy.index("set_release_start_draining(client, True)", start_mark)
    drain = deploy.index("enable_remote_release_drain(client)", start_drain)
    isolated_mark = deploy.index("watchdog_isolated = True", drain)
    isolate = deploy.index("isolate_watchdog(client)", isolated_mark)
    stop = deploy.index('command(client, "sudo systemctl stop comfy-panel"', start_drain)
    assert first < metadata_read < key_read < connect < keepalive < acquire < prepared < second
    assert second < start_mark < start_drain
    assert start_drain < drain < isolated_mark < isolate < stop


def test_release_authenticates_with_the_ignored_ed25519_key_not_a_password():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    ignore_patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert 'DEPLOY_SSH_KEY_PATH = BASE / "tools" / "id_ed25519"' in source
    assert "paramiko.Ed25519Key.from_private_key_file(" in deploy
    assert "pkey=deploy_key" in deploy
    assert "password=" not in deploy
    assert 'creds["password"]' not in deploy
    assert "tools/id_ed25519" in ignore_patterns


def test_ssh_transport_keepalive_requires_an_active_authenticated_transport():
    module = load_module()
    intervals = []

    class Transport:
        def __init__(self, active):
            self.active = active

        def is_active(self):
            return self.active

        def set_keepalive(self, interval):
            intervals.append(interval)

    active = Transport(True)
    assert module.configure_ssh_transport(
        types.SimpleNamespace(get_transport=lambda: active)
    ) is active
    assert intervals == [module.SSH_KEEPALIVE_INTERVAL]

    for transport in (None, Transport(False)):
        with pytest.raises(RuntimeError, match="SSH transport is not active"):
            module.configure_ssh_transport(
                types.SimpleNamespace(get_transport=lambda transport=transport: transport)
            )


def test_staging_retries_on_one_sftp_channel_and_byte_verifies(monkeypatch):
    module = load_module()
    payload = b"verified payload"
    stored = bytearray()
    opens = []
    writes = 0

    class RemoteFile:
        def __init__(self, mode):
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, data):
            nonlocal writes
            writes += 1
            if writes == 1:
                raise OSError("transient write failure")
            stored[:] = data

        def read(self):
            return bytes(stored)

    class SFTP:
        def open(self, path, mode):
            opens.append((path, mode))
            return RemoteFile(mode)

    commands = []
    fsyncs = []
    sleeps = []
    client = object()
    sftp = SFTP()
    transaction = {"stage_root": module.REMOTE_ROOT + "/tx/stage"}
    remote = module.REMOTE_ROOT + "/static/index.html"
    monkeypatch.setattr(module, "command", lambda *args: commands.append(args[1]))
    monkeypatch.setattr(module, "fsync_remote_file", lambda *args: fsyncs.append(args[1]))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    staged = module.stage_file_resilient(
        client, sftp, module.BASE / "static" / "index.html", remote,
        transaction, payload,
    )

    assert writes == 2
    assert [mode for _, mode in opens] == ["wb", "wb", "rb"]
    assert sleeps == [2]
    assert fsyncs == [staged]
    assert any(command.startswith("chmod 0600") for command in commands)


def test_default_release_fails_closed_without_the_remote_drain_contract():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert "if bootstrap_drain_contract:" in deploy
    default_branch = deploy.split("if not bootstrap_drain_contract:", 1)[1].split(
        "isolate_watchdog_or_restore", 1
    )[0]
    assert default_branch.index("drain_enabled = True") < default_branch.index(
        "enable_remote_release_drain(client)"
    )


def test_release_contract_prechecks_happen_before_watchdog_or_stop():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    acquire = deploy.index("acquire_release_lock(client, transaction)")
    precondition = deploy.index("require_bootstrap_drain_contract_absent(client)", acquire)
    bootstrap = deploy.index("snapshot_bootstrap_drain_contract(client, transaction)", precondition)
    persistent = deploy.index("require_persistent_release_drain_contract(client)", acquire)
    manager = deploy.index("require_release_start_draining_unset(client)", persistent)
    watchdog = deploy.index("capture_watchdog_state(client)", manager)
    stop = deploy.index('command(client, "sudo systemctl stop comfy-panel"', watchdog)
    assert acquire < precondition < bootstrap < manager < watchdog < stop
    assert acquire < persistent < manager < watchdog < stop


def test_bootstrap_is_explicit_and_installs_token_without_returning_it():
    module = load_module()
    args = module.parse_args(["--bootstrap-drain-contract"])
    assert args.bootstrap_drain_contract is True
    source = SCRIPT.read_text(encoding="utf-8")
    snapshot = source.split("def snapshot_bootstrap_drain_contract", 1)[1].split(
        "def require_persistent_release_drain_contract", 1
    )[0]
    bootstrap = source.split("def install_bootstrap_drain_contract", 1)[1].split(
        "def restore_bootstrap_drain_contract", 1
    )[0]
    assert "bootstrap-drain-state.json" in snapshot
    assert "START_PATH" in snapshot
    assert "created_directories" in snapshot
    assert "bootstrap state readback mismatch" in snapshot
    assert "bootstrap state metadata mismatch" in snapshot
    assert "PANEL_RELEASE_TOKEN=" in bootstrap
    assert "secrets.token_urlsafe" in bootstrap
    assert "bootstrap drain contract is already initialized" in bootstrap
    assert "base64.b64encode" not in bootstrap
    assert "bootstrap token readback mismatch" in bootstrap
    assert "bootstrap drop-in readback mismatch" in bootstrap
    assert "print(" not in bootstrap
    assert "fsync" in bootstrap


def test_bootstrap_dropin_has_real_systemd_directive_lines():
    module = load_module()
    assert module.RELEASE_DRAIN_DROPIN_BYTES == (
        b"[Service]\n"
        b"EnvironmentFile=/etc/comfy-panel/release.env\n"
    )
    assert module.RELEASE_DRAIN_DROPIN_BYTES.splitlines() == [
        b"[Service]",
        b"EnvironmentFile=/etc/comfy-panel/release.env",
    ]
    assert module.RELEASE_START_DRAIN_DROPIN_BYTES.splitlines() == [
        b"[Service]",
        b"Environment=PANEL_RELEASE_DRAIN_ON_START=1",
    ]


def test_bootstrap_fence_blocks_only_non_loopback_panel_admission_and_survives_reboot():
    module = load_module()
    config = module.BOOTSTRAP_FENCE_CONFIG_BYTES.decode("ascii")
    unit = module.BOOTSTRAP_FENCE_UNIT_BYTES.decode("ascii")

    assert "table inet comfy_panel_release_fence" in config
    assert 'iifname != "lo" tcp dport 8189 reject with tcp reset' in config
    assert "dport 22" not in config and "policy drop" not in config
    assert "DefaultDependencies=no" in unit
    assert "Before=comfy-panel.service" in unit
    assert "After=network-pre.target nftables.service firewalld.service ufw.service" in unit
    assert "RequiredBy=comfy-panel.service" in unit
    assert "WantedBy=multi-user.target" not in unit
    assert module.BOOTSTRAP_FENCE_ENABLE_LINK == (
        "/etc/systemd/system/comfy-panel.service.requires/"
        "comfy-panel-bootstrap-fence.service"
    )
    assert "RemainAfterExit=yes" in unit
    assert "/usr/sbin/nft -f " in unit
    assert "/usr/sbin/nft delete table inet comfy_panel_release_fence" in unit


def test_bootstrap_fence_precheck_and_remote_helpers_compile(monkeypatch):
    module = load_module()
    commands = []
    states = iter(["absent", "active", "active", "absent"])
    monkeypatch.setattr(module, "probe_bootstrap_fence", lambda client: next(states))
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        commands.append(text) or "")

    compile(module._bootstrap_fence_probe_source(), "<bootstrap-fence-probe>", "exec")
    module.require_bootstrap_fence_capability_absent(object())
    module.arm_bootstrap_fence(object())
    module.disarm_bootstrap_fence(object())
    embedded = [shlex.split(text)[3] for text in commands if text.startswith("sudo python3 -c ")]
    assert len(embedded) == 3
    for index, script in enumerate(embedded):
        compile(script, f"<bootstrap-fence-helper-{index}>", "exec")


def test_bootstrap_fence_exact_probe_requires_fail_closed_panel_dependency():
    module = load_module()
    probe = module._bootstrap_fence_probe_source()

    assert "comfy-panel.service.requires" in probe
    assert "panel_show('Requires')" in probe
    assert "required dependency mismatch" in probe
    assert "Before" in probe and "After" in probe and "comfy-panel.service" in probe
    assert all(name in probe for name in (
        "network-pre.target", "nftables.service", "firewalld.service", "ufw.service",
    ))
    assert "enable link mismatch" in probe


def test_bootstrap_fence_arm_reconciles_a_lost_command_response(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "command", lambda *args, **kwargs:
                        calls.append("arm") or (_ for _ in ()).throw(RuntimeError("lost response")))
    monkeypatch.setattr(module, "probe_bootstrap_fence", lambda client: "active")

    module.arm_bootstrap_fence(object())
    assert calls == ["arm"]


def test_bootstrap_fence_disarm_repairs_owned_partial_state(monkeypatch):
    module = load_module()
    probes = iter([RuntimeError("partial owned state"), "absent"])
    cleanup = []

    def probe(client):
        value = next(probes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(module, "probe_bootstrap_fence", probe)
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        cleanup.append(text) or "")
    module.disarm_bootstrap_fence(object())

    assert len(cleanup) == 1
    embedded = shlex.split(cleanup[0])[3]
    assert "cleanup target mismatch" in embedded
    assert "cleanup nft rule mismatch" in embedded
    assert "still_present" in embedded
    assert "comfy-panel.service.requires" in embedded
    assert "cleanup link mismatch" in embedded
    unlink = embedded.index("link.unlink()")
    reload = embedded.index("systemctl','daemon-reload", unlink)
    stop = embedded.index("systemctl','stop',unit_name", reload)
    assert unlink < reload < stop
    assert "systemctl','disable','--now" not in embedded
    assert "panel stopped while stopping bootstrap fence" in embedded


def test_bootstrap_fence_arm_persists_required_link_before_unit_payload(monkeypatch):
    module = load_module()
    commands = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        commands.append(text) or "")
    monkeypatch.setattr(module, "probe_bootstrap_fence", lambda client: "active")

    module.arm_bootstrap_fence(object())
    embedded = shlex.split(commands[0])[3]
    link = embedded.index("os.symlink(str(unit),tmp)")
    dependency = embedded.index("required dependency was not loaded", link)
    payload = embedded.index("f=open(tmp,'wb')", dependency)
    start = embedded.index("systemctl','start',unit_name", payload)
    assert link < dependency < payload < start
    assert "link_parent.is_symlink()" in embedded
    assert "systemctl','enable','--now" not in embedded


def test_fenced_loopback_idle_rejects_busy_work_without_stopping(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "command", lambda *args, **kwargs:
                        '{"ok":true,"cloud_busy":false,"local_busy":false,"api_busy":true}')
    with pytest.raises(module.ReleaseBusyError, match="api_busy"):
        module.require_loopback_idle(object(), "fenced", samples=1, interval=0)


def test_panel_stop_reconciles_a_lost_response(monkeypatch):
    module = load_module()
    calls = []

    def command(client, text, timeout=240):
        calls.append(text)
        if text == "sudo systemctl stop comfy-panel":
            raise RuntimeError("lost response")
        return "inactive\n"

    monkeypatch.setattr(module, "command", command)
    module.stop_panel_resilient(object())
    assert calls == ["sudo systemctl stop comfy-panel", "systemctl is-active comfy-panel || true"]


def test_bootstrap_deploy_orders_fence_loopback_stop_and_reopen():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    capability = deploy.index("require_bootstrap_fence_capability_absent(client)")
    snapshot = deploy.index("snapshot_bootstrap_drain_contract(client, transaction)")
    arm = deploy.index("arm_bootstrap_fence(client)")
    loopback_idle = deploy.index("require_loopback_idle(", arm)
    stop = deploy.index("stop_panel_resilient(client)", loopback_idle)
    start = deploy.index('command(client, "sudo systemctl start comfy-panel"', stop)
    drain = deploy.index("wait_for_remote_release_drain(client)", start)
    disarm = deploy.index("disarm_bootstrap_fence(client)", drain)
    public_live = deploy.index("wait_for_live(public_base", disarm)
    assert capability < snapshot < arm < loopback_idle < stop < start < drain < disarm < public_live


def test_bootstrap_rollback_keeps_fence_until_watchdog_restore_and_public_health():
    source = SCRIPT.read_text(encoding="utf-8")
    rollback = source.split("def rollback_release(", 1)[1].split(
        "def emergency_stop_after_failed_release", 1
    )[0]
    start = rollback.index('command(client, "sudo systemctl start comfy-panel"')
    loopback = rollback.index("wait_for_loopback_live", start)
    assert "disarm_bootstrap_fence" not in rollback
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    rolling_back = deploy.index('write_transaction_phase(client, transaction, "rolling-back")')
    restore = deploy.index("restore_watchdog_state(client, watchdog_state)", rolling_back)
    disarm = deploy.index("disarm_bootstrap_fence(client)", restore)
    public = deploy.index("legacy_live = wait_for_live(", disarm)
    assert start < loopback and restore < disarm < public


def test_restart_drain_uses_a_durable_dropin_and_effective_config_readback():
    source = SCRIPT.read_text(encoding="utf-8")
    helper = source.split("def set_release_start_draining", 1)[1].split(
        "def install_bootstrap_drain_contract", 1
    )[0]
    assert "RELEASE_START_DRAIN_DROPIN_FILE" in helper
    assert "os.replace" in helper and "os.fsync" in helper
    assert "systemctl','daemon-reload" in helper
    assert "DropInPaths" in helper and "Environment" in helper
    assert "set-environment" not in helper
    assert "show-environment" not in helper


def test_bootstrap_precondition_is_checked_before_snapshot_uncertainty():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    precondition = deploy.index("require_bootstrap_drain_contract_absent(client)")
    uncertainty = deploy.index("rollback_uncertain = True", precondition)
    snapshot = deploy.index("snapshot_bootstrap_drain_contract(client, transaction)")
    assert precondition < uncertainty < snapshot


def test_bootstrap_restore_removes_start_dropin_before_restarting_legacy():
    source = SCRIPT.read_text(encoding="utf-8")
    rollback = source.split("def rollback_release(", 1)[1].split(
        "def emergency_stop_after_failed_release", 1
    )[0]
    restore = rollback.index("restore_bootstrap_drain_contract(client, transaction)")
    restart = rollback.index('command(client, "sudo systemctl start comfy-panel"')
    assert restore < restart


def test_remote_drain_token_is_read_inside_remote_process_only():
    source = SCRIPT.read_text(encoding="utf-8")
    helper = source.split("def set_remote_release_drain", 1)[1].split(
        "def enable_remote_release_drain", 1
    )[0]
    assert "/proc/" in helper and "/environ" in helper
    assert "'Authorization':'Bearer '+token" in helper
    assert "PANEL_RELEASE_TOKEN" in helper
    assert "creds" not in helper


def test_remote_drain_and_bootstrap_embedded_python_compile(monkeypatch):
    module = load_module()
    commands = []

    def fake_command(client, text, timeout=240):
        commands.append(text)
        if "release-drain" in text:
            return '{"draining":true,"cloud_busy":false,"local_busy":false,"api_busy":false}'
        return ""

    monkeypatch.setattr(module, "command", fake_command)
    module.set_remote_release_drain(object(), True)
    module.require_bootstrap_drain_contract_absent(object())
    module.snapshot_bootstrap_drain_contract(object(), {"root": "/tmp/release"})
    module.require_persistent_release_drain_contract(object())
    module.require_release_start_draining_unset(object())
    module.set_release_start_draining(object(), True)
    module.install_bootstrap_drain_contract(object(), {"root": "/tmp/release"})
    embedded = [shlex.split(text)[3] for text in commands if text.startswith("sudo python3 -c ")]
    assert len(embedded) == 7
    for index, script in enumerate(embedded):
        compile(script, f"<remote-release-script-{index}>", "exec")


def test_enabled_drain_with_busy_work_is_undone_and_rejected(monkeypatch):
    module = load_module()
    calls = []

    def set_drain(client, enabled, require_start_draining=False):
        calls.append(enabled)
        return {
            "draining": enabled,
            "cloud_busy": enabled,
            "local_busy": False,
            "api_busy": False,
        }

    monkeypatch.setattr(module, "set_remote_release_drain", set_drain)
    with pytest.raises(RuntimeError, match="cloud_busy"):
        module.enable_remote_release_drain(object())
    assert calls == [True, False]


def test_restarted_drain_wait_never_retries_active_work(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "enable_remote_release_drain", lambda client, undo_if_busy=True,
                        require_start_draining=False:
                        calls.append((undo_if_busy, require_start_draining)) or (_ for _ in ()).throw(
                            module.ReleaseBusyError("api_busy")))
    with pytest.raises(module.ReleaseBusyError, match="api_busy"):
        module.wait_for_remote_release_drain(object(), timeout=60)
    assert calls == [(False, True)]


def test_restarted_drain_missing_process_flag_fails_without_retry(monkeypatch):
    module = load_module()
    sleeps = []
    monkeypatch.setattr(module, "command", lambda *args, **kwargs:
                        (_ for _ in ()).throw(RuntimeError("remote command failed (78): ")))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(module.ReleaseDrainContractError, match="did not inherit"):
        module.wait_for_remote_release_drain(object(), timeout=60)
    assert sleeps == []


def test_post_start_busy_keeps_admission_draining(monkeypatch):
    module = load_module()
    calls = []

    def set_drain(client, enabled, require_start_draining=False):
        calls.append(enabled)
        return {
            "draining": enabled,
            "cloud_busy": False,
            "local_busy": False,
            "api_busy": enabled,
        }

    monkeypatch.setattr(module, "set_remote_release_drain", set_drain)
    with pytest.raises(module.ReleaseBusyError, match="api_busy"):
        module.enable_remote_release_drain(object(), undo_if_busy=False)
    assert calls == [True]


def test_backup_rejects_symlink_or_other_non_regular_release_targets(monkeypatch):
    module = load_module()

    class FakeSFTP:
        def lstat(self, path):
            return types.SimpleNamespace(st_mode=stat_mode)

    monkeypatch.setattr(module, "command", lambda *args, **kwargs: "")
    transaction = {"backup_root": module.REMOTE_ROOT + "/tx/backup"}
    for stat_mode in (0o120777, 0o040755):
        with pytest.raises(RuntimeError, match="not a regular file"):
            module.backup_release(
                object(), FakeSFTP(), [module.REMOTE_ROOT + "/server.py"], transaction,
            )


def test_mutating_release_rolls_back_base_exceptions_before_unlocking():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    handler = deploy.split('command(client, "sudo systemctl stop comfy-panel"', 1)[1]

    assert "except BaseException:" in handler
    assert "rollback_uncertain = True" in handler
    assert "rollback_uncertain = False" in handler


def _exercise_interrupted_deploy(monkeypatch, tmp_path, rollback_error=None,
                                 final_idle_error=None, isolation_error=None,
                                 restore_error=None, acquire_error=None,
                                 fence_error=None):
    module = load_module()
    local = tmp_path / "payload"
    local.write_bytes(b"new")
    remote = module.REMOTE_ROOT + "/payload"
    events = []

    class FakeSFTP:
        def posix_rename(self, source, destination):
            events.append("swap")
            raise KeyboardInterrupt()

        def close(self):
            events.append("sftp-close")

    class FakeClient:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, *args, **kwargs):
            events.append("connect")

        def get_transport(self):
            return types.SimpleNamespace(
                is_active=lambda: True,
                set_keepalive=lambda interval: events.append(("keepalive", interval)),
            )

        def open_sftp(self):
            return FakeSFTP()

        def close(self):
            events.append("client-close")

    fake_paramiko = types.SimpleNamespace(
        Ed25519Key=types.SimpleNamespace(
            from_private_key_file=lambda path: object(),
        ),
        MissingHostKeyPolicy=object,
        SSHException=RuntimeError,
        SSHClient=FakeClient,
    )
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)
    def idle(*args, **kwargs):
        events.append("idle")

    monkeypatch.setattr(module, "require_public_idle", idle)
    monkeypatch.setattr(module, "require_bootstrap_fence_capability_absent",
                        lambda *args: events.append("fence-capability"))
    def arm_fence(*args):
        events.append("fence-on")
        if fence_error is not None:
            raise fence_error
    monkeypatch.setattr(module, "arm_bootstrap_fence", arm_fence)
    monkeypatch.setattr(module, "disarm_bootstrap_fence",
                        lambda *args: events.append("fence-off"))
    monkeypatch.setattr(module, "probe_bootstrap_fence", lambda *args: "active")
    def loopback_idle(*args, **kwargs):
        events.append("loopback-idle")
        if final_idle_error is not None:
            raise final_idle_error
    monkeypatch.setattr(module, "require_loopback_idle", loopback_idle)
    monkeypatch.setattr(module, "stop_panel_resilient",
                        lambda *args: events.append("panel-stop"))
    monkeypatch.setattr(module, "enable_remote_release_drain",
                        lambda *args: events.append("drain-on"))
    monkeypatch.setattr(module, "set_remote_release_drain",
                        lambda client, enabled: events.append("drain-on" if enabled else "drain-off"))
    monkeypatch.setattr(module, "set_release_start_draining",
                        lambda client, enabled: events.append("start-drain-on" if enabled else "start-drain-off"))
    monkeypatch.setattr(module.pathlib.Path, "read_text", lambda self, **kwargs:
                        '{"host":"test","port":22,"user":"test","password":"test"}')
    def acquire(*args):
        events.append("lock")
        if acquire_error is not None:
            raise acquire_error

    monkeypatch.setattr(module, "acquire_release_lock", acquire)
    monkeypatch.setattr(module, "release_release_lock", lambda *args: events.append("unlock"))
    monkeypatch.setattr(module, "capture_watchdog_state", lambda *args: {key: None for key in module.WATCHDOG_STATE_KEYS})
    monkeypatch.setattr(module, "stage_file_resilient", lambda *args: None)
    monkeypatch.setattr(module, "backup_release", lambda *args: {
        remote: {"exists": True, "sha256": "a" * 64, "mode": 0o644}
    })
    monkeypatch.setattr(module, "write_transaction_phase", lambda client, tx, phase: events.append(phase))
    isolation_calls = []
    def isolate(*args):
        label = "isolate-first" if not isolation_calls else "isolate-rollback"
        isolation_calls.append(label)
        events.append(label)
        if isolation_error is not None and len(isolation_calls) == 1:
            raise isolation_error

    def restore(*args):
        events.append("restore")
        if restore_error is not None:
            raise restore_error

    monkeypatch.setattr(module, "isolate_watchdog", isolate)
    monkeypatch.setattr(module, "restore_watchdog_state", restore)
    monkeypatch.setattr(module, "cleanup_release_transaction", lambda *args: events.append("cleanup"))
    monkeypatch.setattr(module, "emergency_stop_after_failed_release",
                        lambda *args: events.append("emergency-stop"))

    def rollback(*args, **kwargs):
        events.append("rollback")
        if rollback_error is not None:
            raise rollback_error

    monkeypatch.setattr(module, "rollback_release", rollback)
    def command(client, text, **kwargs):
        if "systemctl stop comfy-panel" in text:
            events.append("panel-stop")
        return ""

    monkeypatch.setattr(module, "command", command)

    with pytest.raises(BaseException):
        module.deploy(
            {local: remote}, {local: b"new"}, public_base="http://panel",
            bootstrap_drain_contract=final_idle_error is not None,
        )
    return events


def test_keyboard_interrupt_unlocks_only_after_verified_rollback(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(monkeypatch, tmp_path)
    assert events.index("swap") < events.index("rollback") < events.index("restore")
    assert events.index("restore") < events.index("rolled-back") < events.index("unlock")
    assert not {"fence-capability", "fence-on", "fence-off", "loopback-idle"}.intersection(events)


def test_keyboard_interrupt_during_isolation_restores_once_then_unlocks(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, isolation_error=KeyboardInterrupt(),
    )
    assert events.count("restore") == 1
    assert events.index("isolate-first") < events.index("restore") < events.index("unlock")
    assert "panel-stop" not in events
    assert "swap" not in events


def test_keyboard_interrupt_during_isolation_keeps_lock_if_restore_fails(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, isolation_error=KeyboardInterrupt(),
        restore_error=RuntimeError("restore failed"),
    )
    assert events.count("restore") == 1
    assert "unlock" not in events
    assert "panel-stop" not in events


def test_lost_acquire_response_uses_owner_verified_unlock(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, acquire_error=KeyboardInterrupt(),
    )
    assert events.index("lock") < events.index("unlock") < events.index("client-close")
    assert "panel-stop" not in events


def test_keyboard_interrupt_keeps_lock_when_rollback_fails(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, rollback_error=RuntimeError("rollback failed")
    )
    assert "rollback" in events
    assert "rollback-failed" in events
    assert "emergency-stop" in events
    assert "start-drain-off" not in events
    assert "unlock" not in events


def test_new_job_at_final_idle_gate_restores_watchdog_without_stopping_panel(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, final_idle_error=RuntimeError("cloud_busy"),
    )
    assert "restore" in events
    assert "swap" not in events
    assert "rollback" not in events
    assert "panel-stop" not in events
    assert "unlock" in events
    assert events.index("fence-on") < events.index("loopback-idle")
    assert events.index("restore") < events.index("fence-off") < events.index("unlock")


def test_bootstrap_restore_failure_keeps_fence_stops_and_retains_lock(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, final_idle_error=RuntimeError("cloud_busy"),
        restore_error=RuntimeError("watchdog restore failed"),
    )
    assert "fence-off" not in events
    assert "emergency-stop" in events
    assert "unlock" not in events


def test_keyboard_interrupt_while_arming_bootstrap_fence_restores_before_unlock(monkeypatch, tmp_path):
    events = _exercise_interrupted_deploy(
        monkeypatch, tmp_path, final_idle_error=RuntimeError("bootstrap mode"),
        fence_error=KeyboardInterrupt(),
    )
    assert events.index("fence-on") < events.index("restore") < events.index("fence-off")
    assert "panel-stop" not in events
    assert "swap" not in events
    assert "unlock" in events


def test_emergency_stop_verifies_panel_and_watchdog_are_inactive(monkeypatch):
    module = load_module()
    calls = []

    def command(client, text, timeout=240):
        calls.append(text)
        if "is-active comfy-panel || true" in text:
            return "inactive\n"
        return ""

    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "watchdog_isolation_state", lambda client:
                        ("inactive", "disabled", "inactive", "masked-runtime"))
    module.emergency_stop_after_failed_release(object())
    assert any("systemctl stop comfy-panel" in text for text in calls)


def test_watchdog_isolation_accepts_a_clean_host_without_units(monkeypatch):
    module = load_module()

    def command(client, text, timeout=240):
        if text.startswith("python3 -c"):
            return "inactive\nnot-found\ninactive\nnot-found\n"
        return ""

    monkeypatch.setattr(module, "command", command)
    module.isolate_watchdog(object())


def test_rollback_preparation_failure_always_attempts_emergency_stop():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    rollback_handler = deploy.split("except BaseException as rollback_error:", 1)[1]
    assert rollback_handler.index("emergency_stop_after_failed_release(client)") < rollback_handler.index(
        'write_transaction_phase(client, transaction, "rollback-failed")'
    )


def test_transport_cleanup_cannot_skip_release_lock_cleanup():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    cleanup = deploy.split("        cleanup_errors = []", 1)[1]
    sftp_close = cleanup.index("sftp.close()")
    lock_release = cleanup.index("release_release_lock(client, transaction)")
    client_close = cleanup.index("client.close()")
    assert sftp_close < lock_release < client_close
    assert "except BaseException as error:" in cleanup[:lock_release]
    assert "finally:" in cleanup[lock_release:client_close]


def test_remote_lock_and_transaction_directory_entries_are_fsynced(monkeypatch):
    module = load_module()
    calls = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        calls.append(text) or "")
    transaction = {
        "id": "reviewed-release",
        "root": module.RELEASE_TRANSACTIONS_DIR + "/reviewed-release",
        "stage_root": module.RELEASE_TRANSACTIONS_DIR + "/reviewed-release/stage",
        "backup_root": module.RELEASE_TRANSACTIONS_DIR + "/reviewed-release/backup",
    }
    module.acquire_release_lock(object(), transaction)
    module.release_release_lock(object(), transaction)
    assert "os.fsync" in calls[0]
    assert module.RELEASE_TRANSACTIONS_DIR in calls[0]
    assert module.REMOTE_ROOT in calls[0]
    assert "os.fsync" in calls[1]


def test_live_swap_and_rollback_are_fsynced_before_phase_or_restart():
    source = SCRIPT.read_text(encoding="utf-8")
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    rollback = source.split("def rollback_release(", 1)[1].split("def fetch_json", 1)[0]

    swap = deploy.split("for remote in remote_paths:", 1)[1].split("for local, remote in files.items():", 1)[0]
    assert "fsync_remote_file(client, remote)" in swap
    assert 'rollback_temp = remote + ".rollback-"' in rollback
    assert "fsync_remote_file(client, rollback_temp)" in rollback
    assert "mv -f --" in rollback
    assert "fsync_remote_file(client, remote)" in rollback
    assert "fsync_remote_directory" in rollback


def test_watchdog_restore_is_durable_and_verified():
    source = SCRIPT.read_text(encoding="utf-8")
    capture = source.split("def capture_watchdog_state", 1)[1].split("def restore_watchdog_state", 1)[0]
    restore = source.split("def restore_watchdog_state", 1)[1].split("def remove_watchdog_units", 1)[0]

    for mode_key in ("service_mode", "timer_mode", "executable_mode"):
        assert mode_key in capture
    assert "os.fsync" in restore
    assert "os.replace" in restore
    assert "verify_watchdog_state(client, state)" in restore
    assert "p.is_symlink()" in capture
    assert "info.st_uid != 0 or info.st_gid != 0" in capture


def test_watchdog_snapshot_rejects_unrestorable_or_malformed_states_before_mutation(monkeypatch):
    module = load_module()
    valid = {
        "service_exists": False, "service_b64": "", "service_mode": None,
        "timer_exists": False, "timer_b64": "", "timer_mode": None,
        "executable_exists": False, "executable_b64": "", "executable_mode": None,
        "service_active": "inactive", "service_enabled": "static",
        "timer_active": "active", "timer_enabled": "enabled",
    }
    calls = []
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: calls.append(args[1]) or "")
    for field, value in (
        ("service_active", "failed"),
        ("timer_enabled", "linked-runtime"),
        ("service_b64", "not base64!"),
    ):
        invalid = dict(valid)
        invalid[field] = value
        if field == "service_b64":
            invalid["service_exists"] = True
            invalid["service_mode"] = 0o644
        with pytest.raises(RuntimeError, match="watchdog"):
            module.restore_watchdog_state(object(), invalid)
    assert calls == []


def test_watchdog_install_is_fsynced_before_commit_and_runtime_enable_is_preserved():
    source = SCRIPT.read_text(encoding="utf-8")
    install = source.split("def install_watchdog_units", 1)[1].split("def watchdog_isolation_state", 1)[0]
    restore = source.split("def restore_watchdog_state", 1)[1].split("def remove_watchdog_units", 1)[0]
    deploy = source.split("def deploy(", 1)[1].split("def parse_args(", 1)[0]
    assert "fsync_remote_file(client, path)" in install
    assert install.index("fsync_remote_file(client, path)") < install.index("systemctl daemon-reload")
    assert "fsync_systemd_unit_state(client)" in install
    assert "systemctl unmask --runtime" in install
    assert "sudo systemctl start comfy-panel-watchdog.service" in install
    assert "watchdog service execution verification failed" in install
    assert 'enable_flag = "--runtime " if enabled == "enabled-runtime"' in restore
    assert "systemctl unmask --runtime" in restore
    assert deploy.index("install_watchdog_units(client)") < deploy.index(
        'write_transaction_phase(client, transaction, "committed")'
    )


def test_watchdog_effective_contract_embedded_python_compiles(monkeypatch):
    module = load_module()
    commands = []
    monkeypatch.setattr(module, "command", lambda client, text, timeout=240:
                        commands.append(text) or "")
    module.verify_installed_watchdog_contract(object())
    assert len(commands) == 1 and commands[0].startswith("sudo python3 -c ")
    compile(shlex.split(commands[0])[3], "<watchdog-effective-contract>", "exec")


def test_legacy_deploy_entrypoints_are_inert_and_do_not_load_secrets():
    legacy = (
        "tools/deploy.py",
        "tools/deploy_nff_motion_release.py",
        "tools/deploy_liuli_realcomic_release.py",
        "tools/deploy_ui_branch.py",
    )
    forbidden = (
        "paramiko",
        "creds.json",
        "PANEL_TOKEN.txt",
        "AutoAddPolicy",
        "DEEPSEEK_API_KEY",
        "open_sftp",
        "systemctl",
    )
    for relative in legacy:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "RETIRED_DEPLOY_MESSAGE" in text, relative
        assert "deploy_realism_release.py" in text, relative
        assert all(token not in text for token in forbidden), relative


def test_environment_files_are_ignored():
    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".env" in patterns
    assert ".env.*" in patterns


class _QuietHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass


def _start_http_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _stop_http_server(server):
    server.shutdown()
    server.server_close()


def test_public_fetch_accepts_normal_and_bounded_gzip_responses():
    module = load_module()
    plain = b"plain public response"
    compressed = gzip.compress(plain)

    class Handler(_QuietHTTPHandler):
        def do_GET(self):
            body = compressed if self.path == "/gzip" else plain
            self.send_response(200)
            if self.path == "/gzip":
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server, base = _start_http_server(Handler)
    try:
        assert module.fetch_bytes(base, "/plain", max_bytes=len(plain)) == plain
        assert module.fetch_bytes(
            base, "/gzip", accept_gzip=True, max_bytes=len(plain),
        ) == plain
    finally:
        _stop_http_server(server)


def test_public_fetch_rejects_declared_streamed_and_gzip_expansion_overflow():
    module = load_module()
    gzip_bomb = gzip.compress(b"x" * 4096)

    class Handler(_QuietHTTPHandler):
        def do_GET(self):
            self.send_response(200)
            if self.path == "/declared":
                self.send_header("Content-Length", "4096")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            if self.path == "/gzip-bomb":
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(gzip_bomb)))
                self.end_headers()
                self.wfile.write(gzip_bomb)
                return
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"streamed body without a declared length")
            self.close_connection = True

    server, base = _start_http_server(Handler)
    try:
        with pytest.raises(RuntimeError, match="exceeds byte limit"):
            module.fetch_bytes(base, "/declared", max_bytes=8)
        # Windows curl can surface a no-length overflow as CURLE_RECV_ERROR
        # after aborting the socket; both outcomes remain fail-closed.
        with pytest.raises(RuntimeError, match="exceeds byte limit|public response download failed"):
            module.fetch_bytes(base, "/streamed", max_bytes=8)
        with pytest.raises(RuntimeError, match="gzip response exceeds"):
            module.fetch_bytes(
                base, "/gzip-bomb", accept_gzip=True, max_bytes=128,
            )
    finally:
        _stop_http_server(server)


def test_public_fetch_kills_a_no_length_slow_drip_at_the_wall_clock_deadline():
    module = load_module()

    class Handler(_QuietHTTPHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for _ in range(100):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server, base = _start_http_server(Handler)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="verification timeout"):
            module.fetch_bytes(base, "/slow", timeout=0.2, max_bytes=4096)
        assert time.monotonic() - started < 1.5
    finally:
        _stop_http_server(server)


def test_all_public_release_responses_share_one_absolute_deadline(monkeypatch):
    module = load_module()
    expected_realism = b"realism"
    expected_creator = b"creator"
    expected_preview = b"preview"
    calls = []

    def fetch(base, path, **kwargs):
        calls.append((path, kwargs["deadline"], kwargs["max_bytes"]))
        if path == "/realism":
            return expected_realism
        if path == "/static/previews/style-retro-manga-luxury.webp":
            return expected_preview
        return expected_creator

    monkeypatch.setattr(module, "fetch_bytes_resilient", fetch)
    result = module.verify_public_large_responses(
        "http://panel", expected_creator, expected_preview,
        expected_realism=expected_realism,
    )
    assert result == (
        expected_realism, expected_creator, expected_creator, expected_preview,
    )
    assert calls[0][0] == "/realism"
    assert calls[1][0] == "/"
    assert {deadline for _, deadline, _ in calls} == {calls[0][1]}
    assert all(limit in {
        len(expected_realism), len(expected_creator), len(expected_preview),
    } for _, _, limit in calls)


def test_public_verification_timeout_enters_rollback_and_reopens_drain(monkeypatch):
    module = load_module()
    local_paths = (
        module.BASE / "server.py",
        module.BASE / "config.json",
        module.BASE / "static" / "index.html",
        module.BASE / "static" / "realism.html",
        module.BASE / "static" / "previews" / "style-retro-manga-luxury.webp",
    )
    files = {
        local: module.REMOTE_ROOT + "/" + local.relative_to(module.BASE).as_posix()
        for local in local_paths
    }
    payloads = {local: ("payload:" + local.name).encode() for local in local_paths}
    remote_payloads = {files[local]: payloads[local] for local in local_paths}
    events = []

    class RemoteReader:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return self.data

    class FakeSFTP:
        def posix_rename(self, source, destination):
            events.append("swap")

        def open(self, path, mode):
            return RemoteReader(remote_payloads[path])

        def close(self):
            events.append("sftp-close")

    class FakeClient:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, *args, **kwargs):
            events.append("connect")

        def get_transport(self):
            return types.SimpleNamespace(
                is_active=lambda: True,
                set_keepalive=lambda interval: events.append(("keepalive", interval)),
            )

        def open_sftp(self):
            return FakeSFTP()

        def close(self):
            events.append("client-close")

    fake_paramiko = types.SimpleNamespace(
        Ed25519Key=types.SimpleNamespace(
            from_private_key_file=lambda path: object(),
        ),
        MissingHostKeyPolicy=object,
        SSHException=RuntimeError,
        SSHClient=FakeClient,
    )
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)
    monkeypatch.setattr(module.pathlib.Path, "read_text", lambda self, **kwargs:
                        '{"host":"test","port":22,"user":"test","password":"test"}')
    monkeypatch.setattr(module, "require_public_idle", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "require_persistent_release_drain_contract", lambda *args: None)
    monkeypatch.setattr(module, "require_release_start_draining_unset", lambda *args: None)
    monkeypatch.setattr(module, "acquire_release_lock", lambda *args: events.append("lock"))
    monkeypatch.setattr(module, "release_release_lock", lambda *args: events.append("unlock"))
    monkeypatch.setattr(module, "capture_watchdog_state", lambda *args:
                        {key: None for key in module.WATCHDOG_STATE_KEYS})
    monkeypatch.setattr(module, "stage_file_resilient", lambda *args: None)
    monkeypatch.setattr(module, "backup_release", lambda *args: {
        remote: {"exists": True, "sha256": "a" * 64, "mode": 0o644}
        for remote in files.values()
    })
    monkeypatch.setattr(module, "write_transaction_phase", lambda client, tx, phase:
                        events.append(phase))
    monkeypatch.setattr(module, "set_release_start_draining", lambda client, enabled:
                        events.append("start-drain-on" if enabled else "start-drain-off"))
    monkeypatch.setattr(module, "enable_remote_release_drain", lambda *args:
                        events.append("drain-on"))
    monkeypatch.setattr(module, "set_remote_release_drain", lambda client, enabled:
                        events.append("drain-on" if enabled else "drain-off"))
    monkeypatch.setattr(module, "isolate_watchdog", lambda *args: events.append("isolate"))
    monkeypatch.setattr(module, "restore_watchdog_state", lambda *args: events.append("restore"))
    monkeypatch.setattr(module, "fsync_remote_file", lambda *args: None)
    monkeypatch.setattr(module, "wait_for_remote_release_drain", lambda *args: None)
    monkeypatch.setattr(module, "wait_for_live", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(module, "fetch_json", lambda base, path:
                        {"dreamapi_configured": True})
    monkeypatch.setattr(module, "verify_public_large_responses", lambda *args, **kwargs:
                        (_ for _ in ()).throw(RuntimeError(
                            "public large response verification timeout")))
    monkeypatch.setattr(module, "rollback_release", lambda *args, **kwargs:
                        events.append("rollback"))
    monkeypatch.setattr(module, "cleanup_release_transaction", lambda *args:
                        events.append("cleanup"))

    def command(client, text, **kwargs):
        if "systemctl stop comfy-panel" in text:
            events.append("panel-stop")
        if "systemctl start comfy-panel" in text:
            events.append("panel-start")
        return ""

    monkeypatch.setattr(module, "command", command)
    with pytest.raises(RuntimeError, match="verification timeout"):
        module.deploy(files, payloads, public_base="http://panel")

    assert events.index("panel-start") < events.index("rollback")
    assert events.index("rollback") < events.index("restore")
    assert events.index("restore") < events.index("drain-off")
    assert events.index("drain-off") < events.index("unlock")
