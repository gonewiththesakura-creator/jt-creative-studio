"""Offline tests for deploy/backup: consistent snapshot, retention, restore drill."""
import datetime as dt
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from membership_store import MembershipStore  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / "backup" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("jt_backup")
drill = load("jt_restore_drill")
alert = load("jt_backup_alert")


@pytest.fixture
def prod(tmp_path, monkeypatch):
    panel = tmp_path / "srv" / "panel_data"
    store = MembershipStore(panel / "membership.sqlite3", clock=lambda: 1800000000)
    admin = store.bootstrap_admin(store.upsert_identity("https://id.example", "owner", "owner")["id"])
    plan = store.save_plan(admin["id"], {"name": "月卡", "duration_days": 30, "image_units": 5,
                                         "video_units": 1, "max_concurrent": 1})
    store.redeem(admin["id"], store.issue_codes(admin["id"], plan["id"])[0]["code"])
    store.reserve_job(admin["id"], "job1", "image", 1)
    (panel / "jobs.json").write_text(json.dumps({"job1": {"id": "job1", "owner_user_id": admin["id"]}}), "utf-8")
    (panel / "favorites.json").write_text(json.dumps({"f1": {"image_path": "f1.png", "archive_status": "ready"}}), "utf-8")
    (panel / "upload_usage.json").write_text("[]", "utf-8")
    (panel / "favorites").mkdir()
    (panel / "favorites" / "f1.png").write_bytes(b"fav")
    (panel / "jobs" / "job1").mkdir(parents=True)
    (panel / "jobs" / "job1" / "out.png").write_bytes(b"image-bytes")
    (panel / "result_image_cache").mkdir()
    (panel / "result_image_cache" / "x.thumb.webp").write_bytes(b"cache")
    (panel / ".jobs.json.abc.tmp").write_text("{", "utf-8")
    ml = panel / "media_library" / "a"
    ml.mkdir(parents=True)
    (ml / "index.json").write_text('{"expires": 1}', "utf-8")

    identity = tmp_path / "srv" / "identity"
    identity.mkdir()
    db = sqlite3.connect(str(identity / "casdoor.db"))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE user(id TEXT)")
    db.execute("INSERT INTO user VALUES('a')")
    db.commit()
    db.close()

    for key in list(os.environ):
        if key.startswith(("JT_BACKUP_", "RESTIC_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("JT_BACKUP_PANEL_DIR", str(panel))
    monkeypatch.setenv("JT_BACKUP_IDENTITY_DIR", str(identity))
    monkeypatch.setenv("JT_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("JT_BACKUP_OFFSITE", "none")
    monkeypatch.setenv("JT_BACKUP_MIN_FREE_MB", "1")
    monkeypatch.setattr(backup, "lock_exclusive", lambda path: open(path, "a+"))
    return panel, store, tmp_path / "backups"


def snapshots(root):
    return sorted(p for p in (root / "snapshots").iterdir() if p.is_dir())


def test_backup_builds_point_in_time_snapshot_and_skips_transient_files(prod):
    panel, _, root = prod
    assert backup.main([]) == 0
    [snap] = snapshots(root)
    manifest = json.loads((snap / "manifest.json").read_text())
    assert manifest["consistency"] == "point-in-time"
    assert (snap / "panel_data" / "jobs" / "job1" / "out.png").read_bytes() == b"image-bytes"
    assert (snap / "identity" / "casdoor.db").is_file()
    assert not (snap / "panel_data" / "result_image_cache").exists()
    assert not list((snap / "panel_data").glob("*.tmp"))
    assert not list(snap.rglob("*-wal"))
    status = json.loads((root / "status.json").read_text())
    assert status["ok"] and status["last_success"] == snap.name
    if os.name == "posix":
        assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in snap.rglob("*") if p.is_file())


def test_second_run_hard_links_unchanged_media(prod, monkeypatch):
    panel, _, root = prod
    assert backup.main([]) == 0
    first = snapshots(root)[0]
    later = dt.datetime.strptime(first.name, backup.SNAPSHOT_FORMAT) + dt.timedelta(days=1)
    monkeypatch.setattr(backup, "utc_now", lambda: later.replace(tzinfo=dt.timezone.utc))
    assert backup.main([]) == 0
    second = snapshots(root)[-1]
    assert second != first
    assert os.stat(second / "panel_data" / "jobs" / "job1" / "out.png").st_nlink == 2


def test_bracket_retries_when_sqlite_commits_during_copy(prod, monkeypatch):
    panel, store, root = prod
    original = backup._copy_json
    calls = {"n": 0}

    def racing_copy(source, dest):
        calls["n"] += 1
        if calls["n"] == 1:  # a commit from another connection mid-bracket
            store.reserve_job(_first_user(panel), "job2", "image", 1)
        return original(source, dest)

    monkeypatch.setattr(backup, "_copy_json", racing_copy)
    consistency, attempts, _ = backup.snapshot_ledgers(panel, root / "t", 5, sleep=lambda s: None)
    assert (consistency, attempts) == ("point-in-time", 2)


def _first_user(panel):
    db = sqlite3.connect(str(panel / "membership.sqlite3"))
    try:
        return db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    finally:
        db.close()


def test_bracket_falls_back_to_crash_consistent_without_freeze(prod, monkeypatch):
    panel, _, root = prod
    monkeypatch.setattr(backup, "_bracket_once", lambda p, d: (False, {}))
    assert backup.snapshot_ledgers(panel, root / "t", 3, sleep=lambda s: None)[0] == "crash-consistent"


def test_missing_required_ledger_fails_and_records_status(prod):
    panel, _, root = prod
    (panel / "jobs.json").unlink()
    assert backup.main([]) == 1
    status = json.loads((root / "status.json").read_text())
    assert not status["ok"] and "jobs.json" in status["error"]


def test_offsite_required_unless_explicitly_disabled(prod, monkeypatch):
    _, _, root = prod
    monkeypatch.setenv("JT_BACKUP_OFFSITE", "restic")
    assert backup.main([]) == 1
    status = json.loads((root / "status.json").read_text())
    assert "not configured" in status["error"]
    assert len(snapshots(root)) == 1  # the local snapshot is still kept


def test_retention_keeps_7_daily_4_weekly_3_monthly():
    start = dt.datetime(2026, 5, 1, 19, 20)
    names = [(start + dt.timedelta(days=i)).strftime(backup.SNAPSHOT_FORMAT) for i in range(170)]
    keep = backup.select_keep(names, 7, 4, 3)
    newest = sorted(names)[-7:]
    assert set(newest) <= keep
    assert len(keep) <= 7 + 4 + 3
    months = {n[:6] for n in keep}
    assert len(months) >= 3


def test_freshness_check(prod):
    _, _, root = prod
    assert backup.main(["--check-freshness", "30"]) == 1
    assert backup.main([]) == 0
    assert backup.main(["--check-freshness", "30"]) == 0


def test_restore_drill_passes_on_snapshot_and_leaves_it_untouched(prod, capsys):
    _, _, root = prod
    assert backup.main([]) == 0
    [snap] = snapshots(root)
    before = sorted((p.relative_to(snap), p.stat().st_mtime_ns) for p in snap.rglob("*"))
    capsys.readouterr()
    assert drill.main(["--snapshot-dir", str(snap)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["sqlite"]["membership"]["integrity_check"] == "ok"
    assert report["cross"]["open_reservations_without_job"] == 0
    assert report["sqlite"]["identity/casdoor.db"]["integrity_check"] == "ok"
    assert sorted((p.relative_to(snap), p.stat().st_mtime_ns) for p in snap.rglob("*")) == before


def test_restore_drill_detects_tampering_and_orphans(prod, capsys):
    panel, _, root = prod
    (panel / "jobs.json").write_text("{}", "utf-8")  # reservation job1 now has no job
    assert backup.main([]) == 0
    [snap] = snapshots(root)
    capsys.readouterr()
    assert drill.main(["--snapshot-dir", str(snap)]) == 0
    assert json.loads(capsys.readouterr().out)["cross"]["open_reservations_without_job"] == 1
    os.chmod(snap / "panel_data" / "favorites.json", 0o600)
    (snap / "panel_data" / "favorites.json").write_text("{broken", "utf-8")
    assert drill.main(["--snapshot-dir", str(snap)]) == 1
    errors = json.loads(capsys.readouterr().out)["errors"]
    assert any("manifest" in e for e in errors) and any("favorites.json" in e for e in errors)


def test_restore_drill_refuses_live_panel_data(prod, capsys):
    panel, _, _ = prod
    assert drill.main(["--snapshot-dir", str(panel)]) == 1
    assert "live panel_data" in json.loads(capsys.readouterr().out)["errors"][0]


def test_alert_payload_formats_and_no_channel_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("JT_BACKUP_ROOT", str(tmp_path))
    monkeypatch.delenv("JT_BACKUP_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("JT_BACKUP_ALERT_EMAIL", raising=False)
    text = alert.build_message("jt-backup.service")
    assert "jt-backup.service" in text
    assert alert.webhook_body("wecom", "x") == {"msgtype": "text", "text": {"content": "x"}}
    assert alert.webhook_body("feishu", "x") == {"msg_type": "text", "content": {"text": "x"}}
    assert alert.main(["alert", "jt-backup.service"]) == 1
