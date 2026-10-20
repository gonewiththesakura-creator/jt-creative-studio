#!/usr/bin/env python3
"""Scheduled, consistent backup of JT workbench production data.

Runs as root from ``jt-backup.service``. It never stops the panel: the member
SQLite database is copied with SQLite's online backup API and the JSON ledgers
are copied inside the same "bracket". The bracket is accepted only when no
JSON ledger was replaced and no SQLite commit happened from the moment before
the database copy until after the last JSON copy, so every file reflects one
instant. Media directories are copied afterwards as a hard-link incremental
tree, then the finished snapshot is sent off-host with restic.

Configuration comes only from the environment (``/etc/jt-backup/backup.env``
on the server; see ``backup.env.example``). The script never prints the
environment, restic repository addresses, passwords or webhook URLs.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VERSION = 1
LEDGER_DB = "membership.sqlite3"
# JSON ledgers rewritten by server.py with an atomic os.replace.
LEDGER_JSON = ("jobs.json", "favorites.json", "upload_capabilities.json",
               "upload_usage.json", "membership-owner-migration.json")
REQUIRED = (LEDGER_DB, "jobs.json")
# Regenerable or transient content that does not belong in a restore point.
SKIP_DIRS = {"result_image_cache", "__pycache__"}
SKIP_SUFFIXES = (".tmp", "-wal", "-shm", "-journal", ".log")
SNAPSHOT_FORMAT = "%Y%m%dT%H%M%SZ"


class BackupError(Exception):
    """A failure whose message is safe to log and to send in an alert."""


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def log(message):
    print(f"jt-backup: {message}", flush=True)


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        raise BackupError(f"{name} must be an integer")


def load_config():
    root = Path(os.environ.get("JT_BACKUP_ROOT", "/var/backups/jt"))
    extra = [Path(p) for p in os.environ.get("JT_BACKUP_EXTRA_PATHS", "").split(":") if p.strip()]
    offsite = os.environ.get("JT_BACKUP_OFFSITE", "restic").strip().lower()
    if offsite not in ("restic", "none"):
        raise BackupError("JT_BACKUP_OFFSITE must be restic or none")
    return {
        "panel_dir": Path(os.environ.get("JT_BACKUP_PANEL_DIR", "/home/admin/comfy-panel/panel_data")),
        "identity_dir": Path(os.environ.get("JT_BACKUP_IDENTITY_DIR", "/opt/jt-identity/data")),
        "root": root,
        "extra_paths": extra,
        "keep": (env_int("JT_BACKUP_KEEP_DAILY", 7), env_int("JT_BACKUP_KEEP_WEEKLY", 4),
                 env_int("JT_BACKUP_KEEP_MONTHLY", 3)),
        "min_free_mb": env_int("JT_BACKUP_MIN_FREE_MB", 2048),
        "attempts": max(1, env_int("JT_BACKUP_BRACKET_ATTEMPTS", 20)),
        "freeze_unit": os.environ.get("JT_BACKUP_FREEZE_UNIT", "").strip(),
        "offsite": offsite,
        "restic": os.environ.get("JT_BACKUP_RESTIC_BIN", "restic"),
        "restic_prune": os.environ.get("JT_BACKUP_RESTIC_PRUNE", "1") == "1",
        "host_tag": os.environ.get("JT_BACKUP_HOST_TAG", "") or socket.gethostname(),
        "heartbeat": os.environ.get("JT_BACKUP_HEARTBEAT_URL", "").strip(),
    }


# ---------------------------------------------------------------- file helpers

def private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_private(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def lock_exclusive(path):
    import fcntl  # Linux only; the restore drill does not need it.
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BackupError("another backup run holds the lock")
    return handle


def ensure_free_space(root, min_free_mb):
    free_mb = shutil.disk_usage(str(root)).free // (1024 * 1024)
    if free_mb < min_free_mb:
        raise BackupError(f"only {free_mb} MiB free under backup root (need {min_free_mb})")


# ------------------------------------------------------------ SQLite snapshots

def seal_copy(db):
    """Make the copy a single self-contained file (no -wal/-shm on later reads).

    The backup API copies the WAL flag of the source header; the panel switches
    a restored file back to WAL on its first open.
    """
    db.execute("PRAGMA journal_mode=DELETE")


def sqlite_online_copy(source, dest):
    """Copy a live SQLite database with the online backup API (WAL safe)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = sqlite3.connect(str(source), timeout=30)
    try:
        src.execute("PRAGMA busy_timeout=30000")
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
            seal_copy(out)
        finally:
            out.close()
    finally:
        src.close()
    restore_sidecar_owner(source)
    os.chmod(dest, 0o600)


def restore_sidecar_owner(db_path):
    """Keep -wal/-shm owned like the database if this root process created them.

    SQLite already chowns sidecars it creates as root; this is a second guard so
    the unprivileged panel service can never be locked out of its own database.
    """
    if not hasattr(os, "chown"):
        return
    try:
        owner = os.stat(db_path)
    except OSError:
        return
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        try:
            st = os.stat(side)
            if (st.st_uid, st.st_gid) != (owner.st_uid, owner.st_gid):
                os.chown(side, owner.st_uid, owner.st_gid)
                os.chmod(side, 0o600)
                log(f"restored owner of {side.name}")
        except FileNotFoundError:
            pass
        except OSError:
            log(f"could not verify owner of {side.name}")


def readonly_uri(path):
    return "file:" + urllib.request.pathname2url(str(Path(path).resolve())) + "?mode=ro"


def integrity_check(path):
    db = sqlite3.connect(readonly_uri(path), uri=True)
    try:
        rows = [r[0] for r in db.execute("PRAGMA integrity_check").fetchall()]
    finally:
        db.close()
    if rows != ["ok"]:
        raise BackupError(f"integrity_check failed for {path.name}")


# ---------------------------------------------------- consistent ledger bracket

def _stat_key(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _copy_json(source, dest):
    """Copy one atomically replaced ledger; return the identity of the copied inode."""
    try:
        stream = open(source, "rb")
    except FileNotFoundError:
        return None
    with stream:
        st = os.fstat(stream.fileno())
        raw = stream.read()
    try:
        json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError(f"{source.name} is not valid UTF-8 JSON")
    write_private(dest, raw)
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _bracket_once(panel_dir, dest_dir):
    db_path = panel_dir / LEDGER_DB
    before = {name: _stat_key(panel_dir / name) for name in LEDGER_JSON}
    probe = sqlite3.connect(str(db_path), timeout=30)
    try:
        probe.execute("PRAGMA busy_timeout=30000")
        version_before = probe.execute("PRAGMA data_version").fetchone()[0]
        out_path = dest_dir / LEDGER_DB
        if out_path.exists():
            out_path.unlink()
        out = sqlite3.connect(str(out_path))
        try:
            probe.backup(out)
            seal_copy(out)
        finally:
            out.close()
        copied = {name: _copy_json(panel_dir / name, dest_dir / name) for name in LEDGER_JSON}
        after = {name: _stat_key(panel_dir / name) for name in LEDGER_JSON}
        # data_version changes when any *other* connection commits.
        version_after = probe.execute("PRAGMA data_version").fetchone()[0]
    finally:
        probe.close()
        restore_sidecar_owner(db_path)
    stable = version_before == version_after and before == after == copied
    for name in LEDGER_JSON:
        if copied[name] is None and (dest_dir / name).exists():
            (dest_dir / name).unlink()
    return stable, copied


def systemctl(*args):
    subprocess.run(["systemctl", *args], check=True, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def snapshot_ledgers(panel_dir, dest_dir, attempts, freeze_unit="", sleep=time.sleep):
    """Return (consistency, attempts_used, copied) for the ledger set."""
    for name in REQUIRED:
        if not (panel_dir / name).is_file():
            raise BackupError(f"required ledger {name} is missing")
    private_dir(dest_dir)
    copied = {}
    for attempt in range(1, attempts + 1):
        stable, copied = _bracket_once(panel_dir, dest_dir)
        if stable:
            return "point-in-time", attempt, copied
        sleep(random.uniform(0.2, 2.0))
    if freeze_unit:
        # Last resort: freeze the panel's cgroup for the sub-second copy. In-flight
        # requests stall but nothing is killed; thaw always runs.
        log(f"bracket unstable after {attempts} attempts; freezing {freeze_unit}")
        try:
            systemctl("freeze", freeze_unit)
        except (subprocess.SubprocessError, OSError):
            raise BackupError("systemctl freeze failed")
        try:
            stable, copied = _bracket_once(panel_dir, dest_dir)
        finally:
            try:
                systemctl("thaw", freeze_unit)
            except (subprocess.SubprocessError, OSError):
                raise BackupError("systemctl thaw failed; run: systemctl thaw " + freeze_unit)
        if stable:
            return "point-in-time-frozen", attempts + 1, copied
    # Each file is still internally consistent; across files this equals a crash
    # at that moment, which the panel already has to tolerate on restart.
    log("WARNING: snapshot is crash-consistent only")
    return "crash-consistent", attempts, copied


# ------------------------------------------------- hard-link incremental trees

def _skip(rel):
    name = rel.name
    return name.endswith(SKIP_SUFFIXES) or (name.startswith(".") and ".tmp" in name)


def link_or_copy_tree(source, dest, previous, exclude_top=()):
    """Mirror ``source`` into ``dest``, hard-linking files unchanged since ``previous``."""
    stats = {"files": 0, "linked": 0, "copied": 0, "bytes": 0, "vanished": 0}
    for dirpath, dirnames, filenames in os.walk(source):
        here = Path(dirpath)
        rel_dir = here.relative_to(source)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS
                             and not (rel_dir == Path(".") and d in exclude_top))
        for name in sorted(filenames):
            rel = rel_dir / name
            if (rel_dir == Path(".") and name in exclude_top) or _skip(rel):
                continue
            src = here / name
            try:
                st = os.stat(src)
            except FileNotFoundError:
                stats["vanished"] += 1
                continue
            out = dest / rel
            private_dir(out.parent)
            old = previous / rel if previous else None
            try:
                if old is not None:
                    ost = os.stat(old)
                    if ost.st_size == st.st_size and ost.st_mtime_ns == st.st_mtime_ns:
                        os.link(old, out)
                        stats["linked"] += 1
                        stats["files"] += 1
                        stats["bytes"] += st.st_size
                        continue
            except OSError:
                pass
            try:
                shutil.copy2(src, out)
            except FileNotFoundError:
                stats["vanished"] += 1
                continue
            os.chmod(out, 0o600)
            stats["copied"] += 1
            stats["files"] += 1
            stats["bytes"] += st.st_size
    return stats


def copy_identity(identity_dir, dest, previous):
    """Online-copy every SQLite file of the identity service; mirror the rest."""
    if not identity_dir.is_dir():
        raise BackupError("identity data directory is missing")
    private_dir(dest)
    databases = []
    for path in sorted(identity_dir.iterdir()):
        if path.is_file() and path.suffix in (".db", ".sqlite", ".sqlite3"):
            sqlite_online_copy(path, dest / path.name)
            databases.append(path.name)
    stats = link_or_copy_tree(identity_dir, dest, previous, exclude_top=set(databases))
    stats["databases"] = databases
    return stats


def copy_extra_paths(paths, dest):
    copied = []
    for path in paths:
        if not path.exists():
            log(f"extra path missing, skipped: {path}")
            continue
        target = dest / str(path).lstrip("/\\").replace(":", "")
        if path.is_dir():
            link_or_copy_tree(path, target, None)
        else:
            private_dir(target.parent)
            shutil.copy2(path, target)
            os.chmod(target, 0o600)
        copied.append(str(path))
    return copied


def harden_tree(root):
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o700)
        for name in filenames:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                os.chmod(path, 0o600)


# ------------------------------------------------------------------ retention

def parse_snapshot_name(name):
    try:
        return dt.datetime.strptime(name, SNAPSHOT_FORMAT).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def select_keep(names, daily, weekly, monthly):
    """Grandfather-father-son selection, newest snapshot per bucket (restic semantics)."""
    dated = sorted(((parse_snapshot_name(n), n) for n in names if parse_snapshot_name(n)), reverse=True)
    keep = set()
    if dated:
        keep.add(dated[0][1])
    rules = ((daily, lambda d: d.date()),
             (weekly, lambda d: tuple(d.isocalendar())[:2]),
             (monthly, lambda d: (d.year, d.month)))
    for count, bucket in rules:
        seen = []
        for when, name in dated:
            key = bucket(when)
            if key in seen:
                continue
            if len(seen) >= count:
                break
            seen.append(key)
            keep.add(name)
    return keep


def prune_local(snapshots_dir, keep_rule):
    names = [p.name for p in snapshots_dir.iterdir() if p.is_dir()]
    keep = select_keep(names, *keep_rule)
    removed = []
    for name in sorted(names):
        if parse_snapshot_name(name) and name not in keep:
            shutil.rmtree(snapshots_dir / name)
            removed.append(name)
    return sorted(keep), removed


def latest_snapshot(snapshots_dir):
    names = sorted(p.name for p in snapshots_dir.iterdir()
                   if p.is_dir() and parse_snapshot_name(p.name) and (p / "manifest.json").is_file())
    return snapshots_dir / names[-1] if names else None


# --------------------------------------------------------------------- offsite

def run_restic(cfg, args, log_path):
    """Run restic with output captured in a root-only log, never on stdout."""
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as out:
        out.write(f"\n== restic {args[0]} {utc_now().strftime('%Y-%m-%dT%H:%M:%SZ')}\n".encode())
        out.flush()
        result = subprocess.run([cfg["restic"], *args], stdout=out, stderr=out, timeout=6 * 3600)
    if result.returncode != 0:
        raise BackupError(f"restic {args[0]} exited with {result.returncode}")


def offsite_copy(cfg, work, log_path):
    if cfg["offsite"] == "none":
        log("offsite copy disabled (JT_BACKUP_OFFSITE=none)")
        return "disabled"
    if not os.environ.get("RESTIC_REPOSITORY") and not os.environ.get("RESTIC_REPOSITORY_FILE"):
        raise BackupError("offsite restic repository is not configured")
    tags = ["--host", cfg["host_tag"], "--tag", "jt-panel"]
    # The work path is fixed so restic finds the parent snapshot; hard links
    # change ctime, so ctime/inode are ignored and content dedup does the rest.
    run_restic(cfg, ["backup", str(work), *tags, "--ignore-ctime", "--ignore-inode"], log_path)
    if cfg["restic_prune"]:
        daily, weekly, monthly = cfg["keep"]
        run_restic(cfg, ["forget", *tags, "--group-by", "host,tags",
                         "--keep-daily", str(daily), "--keep-weekly", str(weekly),
                         "--keep-monthly", str(monthly), "--prune"], log_path)
    return "restic"


def heartbeat(url, ok):
    if not url:
        return
    target = url if ok else url.rstrip("/") + "/fail"
    try:
        urllib.request.urlopen(target, timeout=10).close()
    except Exception:
        log("heartbeat ping failed")


# ------------------------------------------------------------------------ run

def build_snapshot(cfg, work, previous):
    started = time.time()
    panel_out = work / "panel_data"
    consistency, attempts, _ = snapshot_ledgers(cfg["panel_dir"], panel_out, cfg["attempts"], cfg["freeze_unit"])
    ledger_done = time.time()
    exclude = {LEDGER_DB, *LEDGER_JSON}
    media = link_or_copy_tree(cfg["panel_dir"], panel_out, previous / "panel_data" if previous else None,
                              exclude_top=exclude)
    identity = copy_identity(cfg["identity_dir"], work / "identity",
                             previous / "identity" if previous else None)
    extra = copy_extra_paths(cfg["extra_paths"], work / "config")
    harden_tree(work)

    checked = {}
    for db in [panel_out / LEDGER_DB] + [work / "identity" / n for n in identity["databases"]]:
        integrity_check(db)
        checked[str(db.relative_to(work)).replace("\\", "/")] = sha256_file(db)
    for name in LEDGER_JSON:
        path = panel_out / name
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))
            checked[f"panel_data/{name}"] = sha256_file(path)
    manifest = {
        "format": VERSION,
        "created_utc": dt.datetime.fromtimestamp(started, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": cfg["host_tag"],
        "consistency": consistency,
        "bracket_attempts": attempts,
        "ledger_seconds": round(ledger_done - started, 3),
        "sha256": checked,
        "media": media,
        "identity": identity,
        "config_paths": extra,
        "source": {"panel_dir": str(cfg["panel_dir"]), "identity_dir": str(cfg["identity_dir"])},
    }
    write_private(work / "manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode())
    return manifest


def write_status(root, status):
    write_private(root / "status.json", json.dumps(status, indent=1, sort_keys=True).encode())


def run_backup(cfg):
    os.umask(0o077)
    root = private_dir(cfg["root"])
    snapshots = private_dir(root / "snapshots")
    logs = private_dir(root / "logs")
    lock = lock_exclusive(root / ".lock")
    stamp = utc_now().strftime(SNAPSHOT_FORMAT)
    status = {"last_run": stamp, "ok": False}
    try:
        old = json.loads((root / "status.json").read_text()) if (root / "status.json").exists() else {}
        status["last_success"] = old.get("last_success")
    except ValueError:
        pass
    try:
        ensure_free_space(root, cfg["min_free_mb"])
        work = root / "work" / "snapshot"
        if work.exists():
            shutil.rmtree(work)  # leftover of an interrupted run; never a finished snapshot
        private_dir(work)
        previous = latest_snapshot(snapshots)
        manifest = build_snapshot(cfg, work, previous)
        log(f"snapshot built: consistency={manifest['consistency']} attempts={manifest['bracket_attempts']} "
            f"media_files={manifest['media']['files']} copied={manifest['media']['copied']}")
        offsite_error = None
        try:
            status["offsite"] = offsite_copy(cfg, work, logs / f"restic-{stamp[:8]}.log")
        except (BackupError, subprocess.SubprocessError, OSError) as error:
            offsite_error = error if isinstance(error, BackupError) else BackupError("restic could not run")
        final = snapshots / stamp
        os.replace(work, final)
        kept, removed = prune_local(snapshots, cfg["keep"])
        status.update(snapshot=stamp, consistency=manifest["consistency"], kept=kept, removed=removed)
        if offsite_error:
            raise offsite_error
        status.update(ok=True, last_success=stamp, error=None)
        log(f"done: {stamp} kept={len(kept)} removed={len(removed)} offsite={status['offsite']}")
        heartbeat(cfg["heartbeat"], True)
        return 0
    except BackupError as error:
        status["error"] = str(error)
        log(f"FAILED: {error}")
    except Exception as error:  # unexpected: report the type only, never values
        status["error"] = f"unexpected {type(error).__name__}"
        log(f"FAILED: unexpected {type(error).__name__}")
    finally:
        write_status(root, status)
        lock.close()
    heartbeat(cfg["heartbeat"], False)
    return 1


def check_freshness(cfg, max_age_hours):
    """Exit non-zero when the last successful backup is too old (dead-man check)."""
    try:
        status = json.loads((cfg["root"] / "status.json").read_text())
        last = parse_snapshot_name(status.get("last_success") or "")
    except (OSError, ValueError):
        last = None
    if last is None:
        log("FAILED: no successful backup recorded")
        return 1
    age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 3600
    if age > max_age_hours:
        log(f"FAILED: last successful backup is {age:.1f} h old")
        return 1
    log(f"ok: last successful backup {age:.1f} h ago")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-freshness", type=float, metavar="HOURS",
                        help="only verify that the last success is younger than HOURS")
    args = parser.parse_args(argv)
    try:
        cfg = load_config()
    except BackupError as error:
        log(f"FAILED: {error}")
        return 1
    if args.check_freshness is not None:
        return check_freshness(cfg, args.check_freshness)
    return run_backup(cfg)


if __name__ == "__main__":
    sys.exit(main())
