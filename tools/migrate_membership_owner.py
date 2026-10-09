#!/usr/bin/env python3
"""Offline, backed-up ownership migration for the original JT site owner.

Default is read-only. Production apply requires the actual PANEL_DIR from the
service environment and comfy-panel.service in ActiveState=inactive. Never
imports server.py, submits jobs, or accepts an email as administrator identity.
"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from membership_store import MembershipStore

LEDGERS = ('jobs.json', 'favorites.json', 'upload_capabilities.json')
DATABASE = 'membership.sqlite3'
FILES = (*LEDGERS, DATABASE, DATABASE+'-wal', DATABASE+'-shm')
MARKER = 'membership-owner-migration.json'
BACKUPS = 'membership-owner-backups'
INTERNAL_PLAN = dict(name='内部管理', duration_days=3650, image_units=1000000,
                     video_units=1000000, max_concurrent=2,
                     features=sorted(MembershipStore.FEATURES), backends=sorted(MembershipStore.BACKENDS),
                     active=True, price_display='')


class MigrationError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def identity_fingerprint(issuer, subject):
    return digest(json.dumps([issuer, subject], ensure_ascii=False, separators=(',', ':')))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError('账本包含重复字段，已停止且未覆盖原文件')
        result[key] = value
    return result


def read_object(path, optional=False):
    if optional and not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
    except (ValueError, OSError) as error:
        raise MigrationError(f'{path.name} 无法完整读取，已保留原文件') from error
    if not isinstance(value, dict):
        raise MigrationError(f'{path.name} 必须是对象账本')
    return value


def read_ledgers(directory):
    result = {name: read_object(directory/name, optional=True) for name in LEDGERS}
    if any(not isinstance(row, dict) for ledger in result.values() for row in ledger.values()):
        raise MigrationError('账本含有非对象记录，不能安全迁移')
    return result


def _fsync_dir(directory):
    if os.name == 'nt':
        return
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path, raw, owner=None):
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if owner is not None and hasattr(os, 'chown'):
            os.chown(temporary, owner.st_uid, owner.st_gid)
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value, owner=None):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'), owner)


@contextmanager
def migration_lock(directory):
    with (directory/'.membership-owner-migration.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0');handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise MigrationError('已有迁移正在进行') from error
            try:
                yield
            finally:
                handle.seek(0);msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise MigrationError('已有迁移正在进行') from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def systemd_properties():
    try:
        result = subprocess.run(['systemctl', 'show', 'comfy-panel.service', '-p', 'ActiveState',
                                 '-p', 'Environment', '-p', 'EnvironmentFiles', '-p', 'WorkingDirectory'],
                                check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError('无法核对 comfy-panel.service，禁止执行迁移') from error
    properties = {}
    for line in result.stdout.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        properties[key] = (properties.get(key, '')+' '+value).strip() if key in ('Environment', 'EnvironmentFiles') else value
    return properties


def service_environment(properties):
    values = dict(entry.split('=', 1) for entry in shlex.split(properties.get('Environment', '')) if '=' in entry)
    # Standard systemd output is "path (ignore_errors=no)"; no shell execution.
    tokens = shlex.split(properties.get('EnvironmentFiles', ''))
    for index, token in enumerate(tokens):
        if token.startswith('('):
            continue
        file = Path(token.lstrip('-'))
        if not file.is_absolute():
            raise MigrationError('服务环境文件路径不明确，请核对配置')
        if not file.is_file():
            optional = index+1 < len(tokens) and tokens[index+1] == '(ignore_errors=yes)'
            if token.startswith('-') or optional:
                continue
            raise MigrationError('服务环境文件缺失，请核对配置')
        for line in file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, raw = line.removeprefix('export ').split('=', 1)
            if key.strip() != 'PANEL_DIR':
                continue
            parsed = shlex.split(raw, comments=True)
            if len(parsed) != 1:
                raise MigrationError('服务 PANEL_DIR 无法明确解析')
            values['PANEL_DIR'] = parsed[0]
    return values


def require_offline(directory, fixture=False):
    if fixture:
        if not (directory/'.jt-migration-fixture').is_file():
            raise MigrationError('测试迁移目录缺少显式 fixture 标记')
        return
    properties = systemd_properties()
    if properties.get('ActiveState') != 'inactive':
        raise MigrationError('请先停止 comfy-panel.service；迁移仅允许 inactive 状态')
    values = service_environment(properties)
    configured = values.get('PANEL_DIR')
    if configured:
        expected = Path(configured)
        if not expected.is_absolute():
            expected = Path(properties.get('WorkingDirectory') or '/')/expected
    elif properties.get('WorkingDirectory'):
        expected = Path(properties['WorkingDirectory'])/'panel_data'
    else:
        raise MigrationError('无法定位服务实际 PANEL_DIR，禁止猜测数据路径')
    if expected.resolve() != directory:
        raise MigrationError('PANEL_DIR 与当前服务数据目录不一致，禁止迁移')


def create_backup(directory):
    parent = directory/BACKUPS
    if parent.is_symlink():
        raise MigrationError('备份目录不能是符号链接')
    parent.mkdir(mode=0o700, exist_ok=True)
    backup = parent/(time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+uuid.uuid4().hex[:12])
    backup.mkdir(mode=0o700)
    manifest = {'version': 1, 'files': {}}
    for name in FILES:
        path = directory/name
        if path.is_symlink():
            raise MigrationError('数据账本不能是符号链接')
        if not path.exists():
            manifest['files'][name] = {'exists': False}
            continue
        raw = path.read_bytes()
        atomic_bytes(backup/name, raw)
        manifest['files'][name] = {'exists': True, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    atomic_json(backup/'backup-manifest.json', manifest)
    _fsync_dir(parent)
    return backup, manifest


def validated_backup(directory, backup):
    backup = backup.resolve()
    if backup.parent != (directory/BACKUPS).resolve():
        raise MigrationError('备份不属于当前工作台，禁止恢复')
    manifest = read_object(backup/'backup-manifest.json')
    if set(manifest.get('files', {})) != set(FILES):
        raise MigrationError('备份清单不完整，禁止恢复')
    for name, info in manifest['files'].items():
        if info['exists'] and (backup/name).is_file():
            if hashlib.sha256((backup/name).read_bytes()).hexdigest() != info['sha256']:
                raise MigrationError('备份校验失败，禁止恢复')
        elif info['exists']:
            raise MigrationError('备份文件缺失，禁止恢复')
    return manifest


def restore_backup(directory, backup, fixture=False):
    require_offline(directory, fixture)
    manifest = validated_backup(directory, backup)
    owner = directory.stat()
    # All targets are fixed filenames in an already verified offline PANEL_DIR.
    for name in FILES:
        info = manifest['files'][name]
        if info['exists']:
            atomic_bytes(directory/name, (backup/name).read_bytes(), owner)
        else:
            (directory/name).unlink(missing_ok=True)
    _fsync_dir(directory)


def stage_database(directory, backup):
    staged = backup/'staged'
    staged.mkdir(mode=0o700)
    target = staged/DATABASE
    source = directory/DATABASE
    if source.exists():
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as before, closing(sqlite3.connect(target)) as after:
            before.backup(after)
    return staged, target


def check_existing_owner(database, issuer, subject):
    if not database.exists():
        return None
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT id,issuer,subject,is_admin FROM users').fetchall()
    except sqlite3.Error as error:
        raise MigrationError('会员数据库无法核对，不能安全迁移') from error
    existing = next((row for row in rows if row[1:3] == (issuer, subject)), None)
    if any(row[3] and row[1:3] != (issuer, subject) for row in rows):
        raise MigrationError('已有其他管理员，禁止替换原站主身份')
    return existing[0] if existing else None


def migrate(directory, issuer, subject, apply=False, fixture=False):
    directory = Path(directory).resolve()
    if not directory.is_dir() or directory == Path(directory.anchor):
        raise MigrationError('必须指定实际工作台数据目录')
    if not issuer or not subject or len(issuer) > 500 or len(subject) > 300:
        raise MigrationError('必须提供 JT_OIDC_ISSUER 和已核验的 subject')
    identity = identity_fingerprint(issuer, subject)
    marker_path = directory/MARKER
    marker = read_object(marker_path, optional=True)
    if marker and marker.get('identity') != identity:
        raise MigrationError('此数据目录已有不同身份的迁移记录')
    if marker.get('phase') == 'committed':
        return {'mode': 'already_migrated', 'counts': marker['counts'], 'changed': False}
    ledgers = read_ledgers(directory)
    counts = {'jobs': len(ledgers['jobs.json']), 'favorites': len(ledgers['favorites.json']),
              'upload_capabilities': len(ledgers['upload_capabilities.json'])}
    if not apply:
        return {'mode': 'dry_run', 'counts': counts, 'changed': False,
                'recovery_required': marker.get('phase') in ('prepared', 'committing')}
    require_offline(directory, fixture)
    with migration_lock(directory):
        marker = read_object(marker_path, optional=True)
        if marker and marker.get('identity') != identity:
            raise MigrationError('迁移身份已改变，请核对后重试')
        if marker.get('phase') == 'committed':
            return {'mode': 'already_migrated', 'counts': marker['counts'], 'changed': False}
        if marker.get('phase') in ('prepared', 'committing'):
            if marker['phase'] == 'committing':
                restore_backup(directory, directory/BACKUPS/marker['backup'], fixture)
            marker['phase'] = 'rolled_back'
            atomic_json(marker_path, marker, directory.stat())
        ledgers = read_ledgers(directory)
        counts = {'jobs': len(ledgers['jobs.json']), 'favorites': len(ledgers['favorites.json']),
                  'upload_capabilities': len(ledgers['upload_capabilities.json'])}
        backup, manifest = create_backup(directory)
        marker = {'version': 1, 'identity': identity, 'phase': 'prepared', 'backup': backup.name, 'counts': counts}
        owner = directory.stat()
        atomic_json(marker_path, marker, owner)
        publishing = False
        try:
            staged, database = stage_database(directory, backup)
            existing_owner = check_existing_owner(database, issuer, subject)
            if any(job.get('owner_user_id') and job['owner_user_id'] != existing_owner for job in ledgers['jobs.json'].values()):
                raise MigrationError('存在其他用户任务，禁止按单人数据迁移')
            store = MembershipStore(database)
            user = store.upsert_identity(issuer, subject, username='JT 管理员')
            user = store.bootstrap_admin(user['id'])
            # This is a private bootstrap entitlement, not a retail price or
            # public product. Disable the plan after its one-time redemption.
            plan = store.save_plan(user['id'], INTERNAL_PLAN)
            code = store.issue_codes(user['id'], plan['id'], note='原站主离线迁移初始化')[0]['code']
            store.redeem(user['id'], code)
            store.save_plan(user['id'], {**INTERNAL_PLAN, 'active': False}, plan['id'])
            owner_hash = digest('jt-session:'+user['owner_key'])
            for job in ledgers['jobs.json'].values():
                job['request_session_hash'] = owner_hash
                job['quota_session_hash'] = owner_hash
                job['owner_user_id'] = user['id']
            for favorite in ledgers['favorites.json'].values():
                favorite['owner_session_hash'] = owner_hash
            for capability in ledgers['upload_capabilities.json'].values():
                capability['session_hash'] = owner_hash
            for name in LEDGERS:
                if manifest['files'][name]['exists']:
                    atomic_json(staged/name, ledgers[name])
            with closing(sqlite3.connect(database)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise MigrationError('迁移数据库完整性校验失败')
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                db.execute('PRAGMA journal_mode=DELETE')
            require_offline(directory, fixture)
            # Verify originals still match the complete snapshot before publish.
            for name in (*LEDGERS, DATABASE):
                info = manifest['files'][name]
                if info['exists'] and hashlib.sha256((directory/name).read_bytes()).hexdigest() != info['sha256']:
                    raise MigrationError('原账本在迁移期间改变，已停止')
                if not info['exists'] and (directory/name).exists():
                    raise MigrationError('原账本在迁移期间新增，已停止')
            marker['phase'] = 'committing'
            atomic_json(marker_path, marker, owner)
            publishing = True
            for suffix in ('-wal', '-shm'):
                (directory/(DATABASE+suffix)).unlink(missing_ok=True)
            atomic_bytes(directory/DATABASE, database.read_bytes(), owner)
            for name in LEDGERS:
                if manifest['files'][name]['exists']:
                    atomic_bytes(directory/name, (staged/name).read_bytes(), owner)
            marker.update(phase='committed', user_id=user['id'], committed_at=int(time.time()))
            atomic_json(marker_path, marker, owner)
        except BaseException as error:
            if publishing:
                restore_backup(directory, backup, fixture)
            marker.update(phase='rolled_back', rolled_back_at=int(time.time()))
            atomic_json(marker_path, marker, owner)
            if isinstance(error, MigrationError):
                raise
            raise MigrationError('迁移失败，已从完整备份恢复；原任务未重新提交') from error
        return {'mode': 'applied', 'counts': counts, 'changed': True, 'backup_directory': str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', required=True, help='已核验 OIDC subject；不接受邮箱推断身份')
    parser.add_argument('--apply', action='store_true', help='执行离线迁移；默认只显示记录数量')
    parser.add_argument('--test-fixture-dir', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    directory = args.test_fixture_dir or os.environ.get('PANEL_DIR')
    if not directory:
        parser.error('请加载当前 comfy-panel 服务环境中的 PANEL_DIR')
    try:
        result = migrate(directory, os.environ.get('JT_OIDC_ISSUER', ''), args.subject,
                         apply=args.apply, fixture=args.test_fixture_dir is not None)
    except MigrationError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
