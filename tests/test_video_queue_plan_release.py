"""Protect production migration verification and compatible code rollback."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from release_video_queue_plan import verify_database
from membership_store import MembershipStore


def legacy_store(tmp_path):
    source = subprocess.check_output(['git', 'show', 'a28b141fa6e1e42a29e8a3a20422f180144e8dc2:membership_store.py'], cwd=ROOT)
    module = types.ModuleType('legacy_video_queue_membership_store')
    exec(compile(source, 'legacy_membership_store.py', 'exec'), module.__dict__)
    before = tmp_path / 'before.sqlite3'
    store = module.MembershipStore(before)
    with sqlite3.connect(before) as db:
        db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ('legacy-plan', 'Original', 30, 100, 10, 1, '["video"]', '["cloud"]', 1, 'unchanged', 1, 1))
        snapshot = '{ "name": "Original", "video_units": 10, "legacy": true }'
        db.execute("INSERT INTO entitlements(id,user_id,plan_id,plan_snapshot,starts_at,expires_at,image_granted,video_granted,image_available,video_available,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ('entitlement', 'member', 'legacy-plan', snapshot, 1, 9999999999, 100, 10, 100, 10, 1, 1))
        db.execute("INSERT INTO activation_codes(id,code_hash,code_hint,plan_id,plan_snapshot,created_by,created_at,note) VALUES(?,?,?,?,?,?,?,?)",
                   ('renewal', 'hash-only', 'hint', 'legacy-plan', snapshot, 'owner', 1, ''))
        db.execute("INSERT INTO login_credentials(id,code_hash,code_hint,plan_id,plan_snapshot,created_by,created_at,note) VALUES(?,?,?,?,?,?,?,?)",
                   ('login', 'hash-only', 'hint', 'legacy-plan', snapshot, 'owner', 1, ''))
    after = tmp_path / 'after.sqlite3'
    with sqlite3.connect(before) as source_db, sqlite3.connect(after) as target_db:
        source_db.backup(target_db)
    return before, after, module


def test_additive_migration_preserves_all_old_rows_and_old_runtime_starts(tmp_path):
    before, after, legacy = legacy_store(tmp_path)
    MembershipStore(after)
    result = verify_database(before, after)
    assert result['existing_membership_preserved'] is True
    assert result['table_counts']['plans'] == 1
    # Code rollback must open the migrated DB without dropping its new column.
    old = legacy.MembershipStore(after)
    assert old.list_plans()[0]['name'] == 'Original'
    assert verify_database(before, after)['legacy_queue_default'] == 100


@pytest.mark.parametrize('mutation,error', [
    ("UPDATE plans SET name='Changed'", 'Existing membership data changed'),
    ("UPDATE plans SET max_video_queued=7", 'Legacy plan defaults changed'),
    ("PRAGMA user_version=3", 'Schema version must remain compatible'),
    ("CREATE TABLE unexpected(value TEXT)", 'Unexpected membership table changes'),
    ("ALTER TABLE plans ADD COLUMN unexpected TEXT", 'Unexpected columns'),
    ("INSERT INTO rate_buckets VALUES('new',1,999999)", 'Existing membership data changed'),
    ("UPDATE entitlements SET plan_snapshot='{}'", 'Existing membership data changed'),
    ("UPDATE activation_codes SET plan_snapshot='{}'", 'Existing membership data changed'),
    ("UPDATE login_credentials SET plan_snapshot='{}'", 'Existing membership data changed'),
])
def test_release_verifier_rejects_unreviewed_data_or_schema_changes(tmp_path, mutation, error):
    before, after, _ = legacy_store(tmp_path)
    MembershipStore(after)
    with sqlite3.connect(after) as db:
        db.execute(mutation)
    with pytest.raises(AssertionError, match=error):
        verify_database(before, after)
