"""2026-11-11 regression: ended-but-unconfirmed jobs must not keep "并发已满".

Live report: submitting kept failing with "当前套餐并发已满". Root cause: a job
that ended in `error` without a confirmed provider failure (unclassified
exception, timeout, or a service restart turning in-flight jobs into errors)
keeps its reservation for administrator review, and that reservation stayed
`running`, so it counted toward the plan's max_concurrent forever.
"""
import sqlite3
import time
from types import SimpleNamespace

import pytest

from membership_http import MembershipGateway
from membership_store import MembershipError, MembershipStore


@pytest.fixture
def env(tmp_path):
    now = [1800000000]
    store = MembershipStore(tmp_path / "members.sqlite3", clock=lambda: now[0])
    admin = store.bootstrap_admin(store.upsert_identity("https://identity.example", "owner", "Owner")["id"])
    alice = store.upsert_identity("https://identity.example", "alice", "Alice")
    plan = store.save_plan(admin["id"], {
        "name": "单并发", "duration_days": 30, "image_units": 20, "video_units": 20,
        "max_concurrent": 1, "backends": ["cloud", "api", "local"],
    })
    store.redeem(alice["id"], store.issue_codes(admin["id"], plan["id"])[0]["code"])
    gateway = MembershipGateway(tmp_path, store=store)
    gateway.enabled = True
    return SimpleNamespace(store=store, now=now, admin=admin, alice=alice, gateway=gateway)


def image_job(job_id, **fields):
    return {"id": job_id, "style_id": "realism", "batch": 1, "generation_backend": "cloud", "status": "running"} | fields


def submit(env, job):
    return env.gateway.reserve(job, env.alice["owner_key"])


def test_store_release_frees_slot_but_keeps_quota_held(env):
    store, alice = env.store, env.alice
    store.reserve_job(alice["id"], "job-a", "image")
    store.start_job("job-a")
    store.reserve_job(alice["id"], "job-b", "image")
    with pytest.raises(MembershipError) as caught:
        store.start_job("job-b")
    assert caught.value.code == "concurrency_limit"
    assert "最多同时运行 1 个任务" in str(caught.value) and "继续排队" not in str(caught.value)

    assert store.release_slot("job-a") is True
    assert store.release_slot("job-a") is False  # idempotent
    assert store.start_job("job-b")["state"] == "running"
    view = store.get_entitlement(alice["id"])
    assert view["running_jobs"] == 1 and view["held_jobs"] == 1
    assert view["image_available"] == 18  # job-a's unit is still held, not refunded
    assert store.get_reservation("job-a")["state"] == "running"
    assert [row["job_id"] for row in store.list_unsettled_reservations()] == ["job-a", "job-b"]
    # Administrator review still settles the held reservation exactly once.
    assert store.admin_settle_job(env.admin["id"], "job-a", False, "云端核对无结果，退回额度")["state"] == "refunded"
    assert store.get_entitlement(alice["id"])["image_available"] == 19


def test_release_ignores_reserved_and_settled_reservations(env):
    store, alice = env.store, env.alice
    store.reserve_job(alice["id"], "queued", "video")
    assert store.release_slot("queued") is False
    store.start_job("queued")
    store.settle_job("queued", True)
    assert store.release_slot("queued") is False


@pytest.mark.parametrize("ended", [
    {"error": "comfyui timeout after 1800s", "submit_started": 1.0, "comfy_prompt_id": "p1", "generation_backend": "local"},
    {"error": "服务重启，任务提交状态未确认；请核对历史后再运行", "submit_started": 1.0},
    {"error": "结果下载失败", "submit_started": 1.0, "rh_task_id": "rh-1", "provider_result_received_at": 1.0},
])
def test_unconfirmed_error_no_longer_blocks_next_submission(env, ended):
    first = image_job("aaaaaaaaaaa1")
    assert submit(env, first) is None
    blocked = submit(env, image_job("aaaaaaaaaaa2"))
    assert blocked["code"] == "concurrency_limit"

    first.update(status="error", **ended)
    env.gateway.reconcile([first])
    # Quota is not refunded: the outcome is unknown and needs review.
    assert env.store.get_reservation(first["id"])["state"] == "running"
    assert submit(env, image_job("aaaaaaaaaaa3")) is None


@pytest.mark.parametrize("still_live", [
    {"status": "running", "submit_started": 1.0},
    {"status": "recovering", "submit_started": 1.0, "rh_task_id": "rh-1"},
    {"status": "error", "submit_started": 1.0, "queue_hold": True},
    {"status": "error", "generation_backend": "api", "submit_started": 1.0, "api_pending_until": time.time() + 600},
    {"status": "cancelled", "submit_started": 1.0, "rh_task_id": "rh-1", "cancel_requested": True},
])
def test_live_or_unresolved_provider_work_keeps_its_slot(env, still_live):
    first = image_job("bbbbbbbbbbb1")
    assert submit(env, first) is None
    first.update(still_live)
    env.gateway.reconcile([first])
    assert submit(env, image_job("bbbbbbbbbbb2"))["code"] == "concurrency_limit"


def test_startup_releases_reservations_missing_from_job_ledger(env):
    assert submit(env, image_job("ccccccccccc1")) is None
    restarted = MembershipGateway(env.store.path.parent, store=env.store)
    restarted.enabled = True
    restarted.reconcile_startup({})
    assert env.store.get_reservation("ccccccccccc1")["state"] == "running"  # quota held
    assert submit(env, image_job("ccccccccccc2")) is None


def test_existing_database_gains_release_column(tmp_path):
    path = tmp_path / "old.sqlite3"
    MembershipStore(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE reservations DROP COLUMN slot_released_at")
    MembershipStore(path)
    with sqlite3.connect(path) as db:
        assert "slot_released_at" in {row[1] for row in db.execute("PRAGMA table_info(reservations)")}
