"""
Tests for the background task queue in app/tasks.py.

The worker uses the async engine while the routes use the sync one, so these
tests put both on the same temporary SQLite file and create queue rows the
way ``POST /generations`` does for long inputs.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app import database as _db_module
from app import tasks
from app.ai import GenerationResult
from app.database import Base
from app.models import Generation, TaskQueue, UsageDaily, User


@pytest.fixture
async def shared_db(tmp_path: Path) -> AsyncGenerator[sessionmaker, None]:
    """Point the sync and async engines at one SQLite file; yield a sync factory."""
    import app.models  # noqa: F401 — registers all ORM classes with Base

    db_file = tmp_path / "tasks.db"
    sync_engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=sync_engine)
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    saved = (_db_module._async_engine, _db_module._AsyncSessionLocal)
    _db_module._async_engine = async_engine
    _db_module._AsyncSessionLocal = async_sessionmaker(
        bind=async_engine, autoflush=False, expire_on_commit=False
    )
    try:
        yield sessionmaker(bind=sync_engine)
    finally:
        _db_module._async_engine, _db_module._AsyncSessionLocal = saved
        await async_engine.dispose()
        sync_engine.dispose()


@pytest.fixture
def fake_client() -> Generator[MagicMock, None, None]:
    client = MagicMock()
    client.generate.return_value = GenerationResult(
        output_text="Feature: Password reset",
        prompt_tokens=120,
        completion_tokens=60,
        total_tokens=180,
        latency_ms=42,
        model="test-model",
        parse_success=True,
    )
    with patch("app.tasks.get_claude_client", return_value=client):
        yield client


def _queue_long_generation(factory: sessionmaker, **task_fields) -> tuple[str, str]:
    """Insert a user, a pending generation and its queue row, as main.py does."""
    with factory() as db:
        user = User(email="worker@example.com", hashed_password="x", plan="free")
        db.add(user)
        db.commit()
        gen = Generation(
            user_id=user.id,
            input_type="user_story",
            input_text="As a user I want to reset my password. " * 100,
            output_format="gherkin",
            status="pending",
            model="test-model",
            via_api_key=False,
        )
        db.add(gen)
        db.commit()
        task = TaskQueue(
            task_type=tasks.GENERATE_TESTS_TASK,
            payload=json.dumps({"generation_id": gen.id, "user_id": user.id}),
            priority=5,
            **task_fields,
        )
        db.add(task)
        db.commit()
        return gen.id, task.id


def _load(factory: sessionmaker, gen_id: str, task_id: str) -> tuple[Generation, TaskQueue]:
    with factory() as db:
        return db.get(Generation, gen_id), db.get(TaskQueue, task_id)


async def _run_one(task_id: str) -> None:
    """Claim and execute exactly one task, as a worker iteration would."""
    async for db in _db_module.get_async_db():
        task = await tasks.get_next_task(db)
        assert task is not None and task.id == task_id
        await tasks.BackgroundWorker()._execute_task(task, db)


async def test_worker_completes_queued_generation(shared_db, fake_client) -> None:
    gen_id, task_id = _queue_long_generation(shared_db)

    with patch.object(tasks.settings, "task_poll_interval", 0.05):
        worker = tasks.BackgroundWorker(concurrency=1)
        await worker.start()
        try:
            for _ in range(100):
                gen, _task = _load(shared_db, gen_id, task_id)
                if gen.status == "completed":
                    break
                await asyncio.sleep(0.05)
        finally:
            await worker.stop()

    gen, task = _load(shared_db, gen_id, task_id)
    assert gen.status == "completed"
    assert gen.output_text == "Feature: Password reset"
    assert gen.total_tokens == 180
    assert task.status == "completed"
    assert task.attempt_count == 1
    with shared_db() as db:
        usage = db.query(UsageDaily).one()
    assert (usage.count, usage.tokens_used) == (1, 180)


async def test_failed_attempt_with_retries_left_keeps_generation_pending(
    shared_db, fake_client
) -> None:
    fake_client.generate.side_effect = RuntimeError("upstream timeout")
    gen_id, task_id = _queue_long_generation(shared_db)

    await _run_one(task_id)

    gen, task = _load(shared_db, gen_id, task_id)
    assert task.status == "pending"
    assert task.attempt_count == 1
    assert task.run_after > datetime.now(timezone.utc).replace(tzinfo=None)
    # Not "failed": the task will run again, so clients must keep polling.
    assert gen.status == "pending"
    assert gen.error_message == "upstream timeout"


async def test_last_failed_attempt_marks_generation_failed(shared_db, fake_client) -> None:
    fake_client.generate.side_effect = RuntimeError("upstream timeout")
    gen_id, task_id = _queue_long_generation(shared_db, max_attempts=1)

    await _run_one(task_id)

    gen, task = _load(shared_db, gen_id, task_id)
    assert task.status == "dead"
    assert gen.status == "failed"
    assert gen.error_message == "upstream timeout"
    assert gen.completed_at is not None


async def test_reaped_dead_task_marks_generation_failed(shared_db) -> None:
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    gen_id, task_id = _queue_long_generation(
        shared_db, status="running", attempt_count=3, max_attempts=3, started_at=started
    )
    with shared_db() as db:
        db.get(Generation, gen_id).status = "processing"
        db.commit()

    reaped = await tasks.TaskReaper(stale_threshold_seconds=60)._reap_stale_tasks()

    gen, task = _load(shared_db, gen_id, task_id)
    assert reaped == 1
    assert task.status == "dead"
    assert gen.status == "failed"


async def test_retry_of_completed_generation_does_not_call_model_again(
    shared_db, fake_client
) -> None:
    gen_id, task_id = _queue_long_generation(shared_db)
    with shared_db() as db:
        db.get(Generation, gen_id).status = "completed"
        db.commit()

    await _run_one(task_id)

    fake_client.generate.assert_not_called()
    _gen, task = _load(shared_db, gen_id, task_id)
    assert task.status == "completed"


async def test_task_is_claimed_only_once(shared_db) -> None:
    _gen_id, task_id = _queue_long_generation(shared_db)

    async def claim():
        task = None
        async for db in _db_module.get_async_db():
            task = await tasks.get_next_task(db)
        return task.id if task is not None else None

    first = await claim()
    second = await claim()
    assert first == task_id
    assert second is None


async def test_lost_claim_race_returns_none(shared_db) -> None:
    """If another worker flips the row to running after our SELECT, we back off."""
    _gen_id, task_id = _queue_long_generation(shared_db)
    real_execute = None

    async for db in _db_module.get_async_db():
        real_execute = db.execute

        async def execute_after_rival_claim(stmt, *args, **kwargs):
            result = await real_execute(stmt, *args, **kwargs)
            if getattr(stmt, "is_select", False):
                with shared_db() as rival:
                    rival.get(TaskQueue, task_id).status = "running"
                    rival.commit()
            return result

        with patch.object(db, "execute", side_effect=execute_after_rival_claim):
            assert await tasks.get_next_task(db) is None


async def test_start_all_workers_starts_worker_and_reaper_only(shared_db) -> None:
    with patch.object(tasks.settings, "task_poll_interval", 0.05):
        await tasks.start_all_workers()
        # Let the reaper finish its first scan; cancelling it mid-connect leaves
        # an aiosqlite thread that outlives the test's event loop.
        await asyncio.sleep(0.2)
        try:
            assert tasks._background_worker is not None and tasks._background_worker.running
            assert tasks._task_reaper is not None and tasks._task_reaper._task is not None
            # No handler exists for the tasks DLQWorker would enqueue.
            assert tasks._dlq_worker is None
        finally:
            await tasks.stop_all_workers()
    assert tasks._background_worker is None
    assert tasks._task_reaper is None


async def test_enqueue_task_stores_json_payload(shared_db) -> None:
    async for db in _db_module.get_async_db():
        queued = await tasks.enqueue_task("app.tasks.send_welcome_email", {"user_id": "u1"}, db)

    with shared_db() as db:
        row = db.get(TaskQueue, queued.id)
    assert row.status == "pending"
    assert json.loads(row.payload) == {"user_id": "u1"}


async def test_unknown_task_type_dies_after_max_attempts(shared_db) -> None:
    async for db in _db_module.get_async_db():
        queued = await tasks.enqueue_task("app.tasks.no_such_task", {}, db, max_attempts=1)

    await _run_one(queued.id)

    with shared_db() as db:
        row = db.get(TaskQueue, queued.id)
    assert row.status == "dead"
    assert "Unknown task type" in row.error_message
