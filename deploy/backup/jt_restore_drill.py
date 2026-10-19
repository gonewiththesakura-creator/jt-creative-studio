#!/usr/bin/env python3
"""Restore drill for JT backups: restore into a throwaway temp dir and verify.

  jt_restore_drill.py --snapshot-dir /var/backups/jt/snapshots/20261019T192000Z
  jt_restore_drill.py --restic latest            # needs RESTIC_* in the caller's env

The drill only ever writes inside a fresh ``tempfile.mkdtemp`` directory and
deletes it afterwards (``--keep`` leaves it for inspection). It never writes to
the source snapshot, never touches a live ``panel_data``, and has no upload
code path. The report contains counts and check results only, no ledger
contents, codes, hashes of credentials or secrets.

Checks: manifest sha256 of every recorded file, SQLite ``integrity_check`` and
``foreign_key_check`` for the member and identity databases, JSON parsing and
root types of every ledger, and cross-ledger consistency (open reservations
without a job, jobs owned by unknown users, ready favorites without media).
Exit status 0 means no errors; warnings do not fail the drill.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

LEDGER_TYPES = {"jobs.json": dict, "favorites.json": dict, "upload_capabilities.json": dict,
                "upload_usage.json": list, "membership-owner-migration.json": dict}
MEMBER_TABLES = ("users", "plans", "entitlements", "activation_codes", "login_credentials",
                 "auth_sessions", "reservations", "audit_events")
PRODUCTION_HINTS = ("/home/admin/comfy-panel", "/opt/jt-identity")


class DrillError(Exception):
    pass


def refuse_production(path):
    """Refuse anything that looks like live data rather than a finished snapshot."""
    resolved = str(Path(path).resolve()).replace("\\", "/")
    live = os.environ.get("PANEL_DIR")
    if any(resolved == h or resolved.startswith(h + "/") for h in PRODUCTION_HINTS):
        raise DrillError("refusing to read a production path; point at a snapshot")
    if live and Path(live).exists() and Path(live).resolve() == Path(path).resolve():
        raise DrillError("refusing to use the live PANEL_DIR")
    if Path(path).name == "panel_data" or (Path(path) / "membership.sqlite3-wal").exists():
        raise DrillError("this looks like a live panel_data directory, not a snapshot")


def find_snapshot_root(base):
    for manifest in sorted(Path(base).rglob("manifest.json")):
        if (manifest.parent / "panel_data").is_dir():
            return manifest.parent
    raise DrillError("restored data contains no snapshot manifest")


def restore(args, workdir):
    target = workdir / "restore"
    if args.snapshot_dir:
        source = Path(args.snapshot_dir)
        refuse_production(source)
        if not (source / "manifest.json").is_file():
            raise DrillError("snapshot directory has no manifest.json")
        shutil.copytree(source, target)  # copy so the drill can never alter the snapshot
        return target
    restic = os.environ.get("JT_BACKUP_RESTIC_BIN", "restic")
    result = subprocess.run([restic, "restore", args.restic, "--target", str(target),
                             "--host", os.environ.get("JT_BACKUP_HOST_TAG", "") or "jt-prod",
                             "--tag", "jt-panel"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=4 * 3600)
    if result.returncode != 0:
        raise DrillError(f"restic restore exited with {result.returncode}")
    return find_snapshot_root(target)


def sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def immutable_uri(path):
    """Read-only URI for a restored copy; immutable=1 creates no -wal/-shm files."""
    return "file:" + urllib.request.pathname2url(str(Path(path).resolve())) + "?mode=ro&immutable=1"


def check_sqlite(path, report, label):
    db = sqlite3.connect(immutable_uri(path), uri=True)
    try:
        integrity = [r[0] for r in db.execute("PRAGMA integrity_check").fetchall()]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        info = {"integrity_check": "ok" if integrity == ["ok"] else "failed",
                "foreign_key_violations": len(fk),
                "user_version": db.execute("PRAGMA user_version").fetchone()[0],
                "tables": len(tables)}
    finally:
        db.close()
    report["sqlite"][label] = info
    if integrity != ["ok"]:
        report["errors"].append(f"{label}: integrity_check failed")
    if fk:
        report["errors"].append(f"{label}: {len(fk)} foreign key violations")
    return tables


def run_checks(root):
    report = {"snapshot": root.name, "errors": [], "warnings": [], "sqlite": {}, "ledgers": {}, "cross": {}}
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    report["consistency"] = manifest.get("consistency")
    report["created_utc"] = manifest.get("created_utc")
    if manifest.get("consistency") != "point-in-time" and manifest.get("consistency") != "point-in-time-frozen":
        report["warnings"].append(f"snapshot consistency is {manifest.get('consistency')}")

    mismatched = [rel for rel, digest in manifest.get("sha256", {}).items()
                  if not (root / rel).is_file() or sha256(root / rel) != digest]
    report["sha256_checked"] = len(manifest.get("sha256", {}))
    if mismatched:
        report["errors"].append(f"{len(mismatched)} files differ from the manifest")

    panel = root / "panel_data"
    member_db = panel / "membership.sqlite3"
    if not member_db.is_file():
        raise DrillError("snapshot has no membership.sqlite3")
    tables = check_sqlite(member_db, report, "membership")
    db = sqlite3.connect(immutable_uri(member_db), uri=True)
    try:
        report["sqlite"]["membership"]["rows"] = {
            t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in MEMBER_TABLES if t in tables}
        open_jobs = {r[0] for r in db.execute(
            "SELECT job_id FROM reservations WHERE state IN ('reserved','running')")} if "reservations" in tables else set()
        users = {r[0] for r in db.execute("SELECT id FROM users")} if "users" in tables else set()
    finally:
        db.close()
    if report["sqlite"]["membership"]["user_version"] != 2:
        report["warnings"].append("membership schema user_version is not 2")

    ledgers = {}
    for name, kind in LEDGER_TYPES.items():
        path = panel / name
        if not path.exists():
            report["ledgers"][name] = "absent"
            if name == "jobs.json":
                report["errors"].append("jobs.json is missing")
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, ValueError):
            report["errors"].append(f"{name} does not parse")
            report["ledgers"][name] = "invalid"
            continue
        if not isinstance(value, kind):
            report["errors"].append(f"{name} root is not a {kind.__name__}")
        report["ledgers"][name] = {"records": len(value)}
        ledgers[name] = value

    index_errors = 0
    for index in (panel / "media_library").glob("*/index.json"):
        try:
            json.loads(index.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, ValueError):
            index_errors += 1
    if index_errors:
        report["errors"].append(f"{index_errors} media_library index.json files do not parse")

    jobs = ledgers.get("jobs.json", {})
    favorites = ledgers.get("favorites.json", {})
    orphan_reservations = len(open_jobs - set(jobs))
    unknown_owner = sum(1 for j in jobs.values()
                        if isinstance(j, dict) and j.get("owner_user_id") and j["owner_user_id"] not in users)
    missing_media = 0
    for fav in favorites.values():
        if isinstance(fav, dict) and fav.get("archive_status") in (None, "ready") and fav.get("image_path"):
            rel = Path(str(fav["image_path"]))
            if not rel.is_absolute() and ".." not in rel.parts and not (panel / "favorites" / rel).exists():
                missing_media += 1
    report["cross"] = {"open_reservations_without_job": orphan_reservations,
                       "jobs_with_unknown_owner": unknown_owner,
                       "ready_favorites_without_file": missing_media}
    if orphan_reservations:
        report["warnings"].append(f"{orphan_reservations} open reservations have no job in jobs.json")
    if unknown_owner:
        report["warnings"].append(f"{unknown_owner} jobs reference users missing from the member database")
    if missing_media:
        report["warnings"].append(f"{missing_media} ready favorites have no media file")

    identity = root / "identity"
    for db_name in manifest.get("identity", {}).get("databases", []):
        if (identity / db_name).is_file():
            check_sqlite(identity / db_name, report, f"identity/{db_name}")
        else:
            report["errors"].append(f"identity database {db_name} is missing")
    if not manifest.get("identity", {}).get("databases"):
        report["warnings"].append("snapshot holds no identity database")
    report["ok"] = not report["errors"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="JT backup restore drill (never touches production)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot-dir", help="a finished local snapshot directory")
    source.add_argument("--restic", metavar="SNAPSHOT", help="restic snapshot id or 'latest'")
    parser.add_argument("--report", help="also write the JSON report to this file (mode 0600)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary restore for inspection")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="jt-restore-drill-"))
    try:
        os.chmod(workdir, 0o700)
        refuse_production(workdir)
        root = restore(args, workdir)
        report = run_checks(root)
    except (DrillError, OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, DrillError) else type(error).__name__
        report = {"ok": False, "errors": [message]}
    finally:
        if args.keep:
            print(f"jt-restore-drill: restored copy kept at {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    text = json.dumps(report, indent=1, ensure_ascii=False, sort_keys=True)
    print(text)
    if args.report:
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text + "\n")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
