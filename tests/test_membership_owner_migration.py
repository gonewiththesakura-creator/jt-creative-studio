import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from membership_store import MembershipStore

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('owner_migration', ROOT/'tools/migrate_membership_owner.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
ISSUER = 'https://login.fixture.test'
SUBJECT = 'verified-owner-subject'


@pytest.fixture
def legacy(tmp_path):
    (tmp_path/'.jt-migration-fixture').write_text('fixture', encoding='utf-8')
    data = {
        'jobs.json': {
            'queued': {'id': 'queued', 'status': 'queued', 'video_queued': True, 'queue_order': 4,
                       'request_session_hash': 'old-a', 'quota_session_hash': 'old-a',
                       'prompt': '原提示词', 'params': {'seed': 123, 'lora': ['a', 'b']},
                       'media': {'source_video': 'upload-token'}, 'provider_media': {'source_video': 'private-provider-file'}},
            'running': {'id': 'running', 'status': 'running', 'rh_task_id': 'existing-provider-task',
                        'request_session_hash': 'old-b', 'queue_hold': True, 'images': [], 'elapsed': 300},
            'done': {'id': 'done', 'status': 'done', 'images': [{'url': '/api/result/done/0'}]},
        },
        'favorites.json': {'favorite': {'id': 'favorite', 'owner_session_hash': 'old-a',
                                      'image_path': '/kept/original.mp4', 'job_id': 'done',
                                      'selection_snapshot': {'prompt': '收藏提示词', 'params': {'lora': 'original'}}}},
        'upload_capabilities.json': {'hashed-token': {'session_hash': 'old-b', 'provider_name': 'private-file',
                                                    'workflow': 'wf', 'expires': 9999999999}},
    }
    for name, ledger in data.items():
        (tmp_path/name).write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
    return tmp_path, data


def raw_files(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def owner_from_db(directory):
    with sqlite3.connect(directory/'membership.sqlite3') as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute('SELECT * FROM users WHERE issuer=? AND subject=?', (ISSUER, SUBJECT)).fetchone())


def test_dry_run_is_read_only_and_has_no_identity_content(legacy, capsys, monkeypatch):
    directory, data = legacy
    before = raw_files(directory)
    monkeypatch.setenv('JT_OIDC_ISSUER', ISSUER)
    assert migration.main(['--test-fixture-dir', str(directory), '--subject', SUBJECT]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['counts'] == {'jobs': 3, 'favorites': 1, 'upload_capabilities': 1}
    assert SUBJECT not in output and ISSUER not in output and '原提示词' not in output
    assert raw_files(directory) == before
    assert not (directory/migration.BACKUPS).exists()


def test_apply_backs_up_first_changes_only_ownership_and_is_idempotent(legacy, monkeypatch):
    directory, original = legacy
    # A preexisting database must be backed up as well, even if it has no users.
    MembershipStore(directory/'membership.sqlite3')
    before = {name: (directory/name).read_bytes() for name in (*migration.LEDGERS, migration.DATABASE)}
    real_store = migration.MembershipStore
    observed = []

    def checked_store(path):
        marker = json.loads((directory/migration.MARKER).read_text(encoding='utf-8'))
        assert marker['phase'] == 'prepared'
        backup = directory/migration.BACKUPS/marker['backup']
        assert all((backup/name).read_bytes() == raw for name, raw in before.items())
        assert all((directory/name).read_bytes() == raw for name, raw in before.items())
        observed.append(True)
        return real_store(path)

    monkeypatch.setattr(migration, 'MembershipStore', checked_store)
    result = migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    assert observed == [True]
    assert result['mode'] == 'applied'
    user = owner_from_db(directory)
    assert user['is_admin'] == 1
    expected_hash = hashlib.sha256(('jt-session:'+user['owner_key']).encode()).hexdigest()
    transformed = copy.deepcopy(original)
    for job in transformed['jobs.json'].values():
        job.update(request_session_hash=expected_hash, quota_session_hash=expected_hash, owner_user_id=user['id'])
    transformed['favorites.json']['favorite']['owner_session_hash'] = expected_hash
    transformed['upload_capabilities.json']['hashed-token']['session_hash'] = expected_hash
    for name, expected in transformed.items():
        assert json.loads((directory/name).read_text(encoding='utf-8')) == expected
    store = real_store(directory/migration.DATABASE)
    entitlement = store.get_entitlement(user['id'])
    assert entitlement['image_available'] == entitlement['video_available'] == 1000000
    assert entitlement['plan']['name'] == '内部管理'
    assert entitlement['plan']['max_concurrent'] == 2
    assert set(entitlement['plan']['features']) == store.FEATURES
    assert set(entitlement['plan']['backends']) == store.BACKENDS
    assert store.list_plans(active_only=True) == []
    with sqlite3.connect(directory/migration.DATABASE) as db:
        assert db.execute('SELECT count(*) FROM reservations').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM activation_codes').fetchone()[0] == 1
    again = migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    assert again['mode'] == 'already_migrated'
    assert store.get_entitlement(user['id']) == entitlement
    assert len(list((directory/migration.BACKUPS).iterdir())) == 1


def test_publish_failure_restores_exact_original_ledgers_and_database(legacy, monkeypatch):
    directory, _ = legacy
    MembershipStore(directory/migration.DATABASE)
    before = {name: (directory/name).read_bytes() for name in (*migration.LEDGERS, migration.DATABASE)}
    real_write = migration.atomic_bytes
    failed = []

    def write(path, raw, owner=None):
        if path == directory/'favorites.json' and not failed:
            failed.append(True)
            raise OSError('injected replacement error')
        return real_write(path, raw, owner)

    monkeypatch.setattr(migration, 'atomic_bytes', write)
    with pytest.raises(migration.MigrationError, match='完整备份恢复') as caught:
        migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    assert failed, repr(caught.value.__cause__)
    assert all((directory/name).read_bytes() == raw for name, raw in before.items())
    marker = json.loads((directory/migration.MARKER).read_text(encoding='utf-8'))
    assert marker['phase'] == 'rolled_back'
    with sqlite3.connect(directory/migration.DATABASE) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 0


def test_interrupted_commit_recovers_before_one_new_entitlement(legacy):
    directory, original = legacy
    migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    marker = json.loads((directory/migration.MARKER).read_text(encoding='utf-8'))
    marker['phase'] = 'committing'
    (directory/migration.MARKER).write_text(json.dumps(marker), encoding='utf-8')
    result = migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    assert result['mode'] == 'applied'
    user = owner_from_db(directory)
    store = MembershipStore(directory/migration.DATABASE)
    assert store.get_entitlement(user['id'])['video_available'] == 1000000
    with sqlite3.connect(directory/migration.DATABASE) as db:
        assert db.execute('SELECT count(*) FROM activation_codes').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM reservations').fetchone()[0] == 0
    assert json.loads((directory/'jobs.json').read_text(encoding='utf-8'))['queued']['queue_order'] == 4


@pytest.mark.parametrize('state', ['active', 'activating', 'failed', 'deactivating'])
def test_apply_refuses_noninactive_service_without_changing_files(legacy, monkeypatch, state):
    directory, _ = legacy
    before = raw_files(directory)
    monkeypatch.setattr(migration, 'systemd_properties', lambda: {'ActiveState': state})
    with pytest.raises(migration.MigrationError, match='inactive'):
        migration.migrate(directory, ISSUER, SUBJECT, apply=True)
    assert raw_files(directory) == before


def test_apply_refuses_path_mismatch_and_other_owner(legacy, monkeypatch):
    directory, _ = legacy
    monkeypatch.setattr(migration, 'systemd_properties', lambda: {
        'ActiveState': 'inactive', 'Environment': 'PANEL_DIR=/a/different/server/directory'})
    with pytest.raises(migration.MigrationError, match='不一致'):
        migration.migrate(directory, ISSUER, SUBJECT, apply=True)
    store = MembershipStore(directory/migration.DATABASE)
    other = store.upsert_identity(ISSUER, 'another-subject')
    store.bootstrap_admin(other['id'])
    before = {name: (directory/name).read_bytes() for name in (*migration.LEDGERS, migration.DATABASE)}
    with pytest.raises(migration.MigrationError, match='已有其他管理员'):
        migration.migrate(directory, ISSUER, SUBJECT, apply=True, fixture=True)
    assert all((directory/name).read_bytes() == raw for name, raw in before.items())


def test_systemd_repeated_environment_files_preserve_effective_panel_dir(tmp_path, monkeypatch):
    first, last = tmp_path/'first.env', tmp_path/'membership.env'
    first.write_text('PANEL_DIR="/home/admin/comfy-panel/panel_data"\n', encoding='utf-8')
    last.write_text('JT_MEMBERSHIP_ENABLED=1\n', encoding='utf-8')
    output = '\n'.join([
        'ActiveState=inactive',
        f'EnvironmentFiles={tmp_path.as_posix()}/optional.env (ignore_errors=yes)',
        f'EnvironmentFiles={first.as_posix()} (ignore_errors=no)',
        f'EnvironmentFiles={last.as_posix()} (ignore_errors=no)',
        'WorkingDirectory=/home/admin/comfy-panel',
    ])
    monkeypatch.setattr(migration.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=output))
    properties = migration.systemd_properties()
    assert 'first.env' in properties['EnvironmentFiles'] and 'membership.env' in properties['EnvironmentFiles']
    assert migration.service_environment(properties)['PANEL_DIR'] == '/home/admin/comfy-panel/panel_data'
