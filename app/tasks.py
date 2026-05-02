"""
Background task system.

Provides:
    - ``TaskQueue`` DB-backed persistent task queue
    - ``BackgroundWorker``   – async worker pool that drains the queue
    - ``DLQWorker``          – periodically re-queues entries from ``webhook_dlq``
    - ``TaskReaper``         – marks timed-out RUNNING tasks as FAILED
    - Concrete task handlers – callables dispatched by type string
    - Startup task registration

Import chain (no circularity):
    tasks → database, models, schemas, exceptions, config, ai, limits
    (never imports from auth, billing, middleware, dependencies)
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import ClaudeClient, get_claude_client
from app.config import settings
from app.database import get_async_db as get_db
from app.exceptions import GenerationError
from app.limits import record_usage
from app.models import (
    Generation,
    GenerationStatus,
    TaskQueue,
    TaskStatus,
    User,
    WebhookDLQ,
)
from app.schemas import TaskQueueResponse


# ---------------------------------------------------------------------------
# Type alias for task handler callables
# ---------------------------------------------------------------------------

TaskHandler = Callable[[dict[str, Any], AsyncSession], Coroutine[Any, Any, dict[str, Any]]]


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLER_REGISTRY: dict[str, TaskHandler] = {}
"""Maps task_type strings to their async handler callables."""


def register_task(task_type: str) -> Callable[[TaskHandler], TaskHandler]:
    """
    Decorator that registers a coroutine function as a named task handler.

    Usage::

        @register_task("app.tasks.my_task")
        async def my_task(payload: dict, db: AsyncSession) -> dict:
            ...

    Args:
        task_type: Dotted task type identifier used in ``TaskQueue.task_type``.

    Returns:
        The decorator (passes the function through unchanged).
    """
    def decorator(fn: TaskHandler) -> TaskHandler:
        _HANDLER_REGISTRY[task_type] = fn
        return fn
    return decorator


def get_handler(task_type: str) -> TaskHandler:
    """
    Look up the handler for ``task_type``.

    Args:
        task_type: Registered task type string.

    Returns:
        The registered async handler callable.

    Raises:
        KeyError: If no handler is registered for ``task_type``.
    """
    if task_type not in _HANDLER_REGISTRY:
        raise KeyError(f"No handler registered for task type: {task_type!r}")
    return _HANDLER_REGISTRY[task_type]


# ---------------------------------------------------------------------------
# Task queue helpers
# ---------------------------------------------------------------------------


async def enqueue_task(
    task_type: str,
    payload: dict[str, Any],
    db: AsyncSession,
    priority: int = 5,
    user_id: uuid.UUID | None = None,
    scheduled_at: datetime | None = None,
    max_attempts: int | None = None,
) -> TaskQueueResponse:
    """
    Insert a new task record into ``task_queue`` and return its schema.

    Args:
        task_type: Registered handler type string.
        payload: Serialisable arguments for the handler.
        db: Active database session.
        priority: Integer priority (1=highest, 10=lowest).
        user_id: Optional owning user ID.
        scheduled_at: Earliest time to run; NULL means run immediately.
        max_attempts: Override default max retries.

    Returns:
        ``TaskQueueResponse`` for the newly created task.
    """
    import json as _json

    kwargs: dict[str, Any] = {
        "task_type": task_type,
        # payload must be stored as a JSON string — TaskQueue.payload is Text
        "payload": _json.dumps(payload),
        "priority": priority,
        "status": TaskStatus.PENDING,
        "attempt_count": 0,
        "user_id": str(user_id) if user_id is not None else None,
        # run_after is the actual column; scheduled_at is a property alias
        "run_after": scheduled_at or datetime.now(timezone.utc),
    }
    if max_attempts is not None:
        kwargs["max_attempts"] = max_attempts

    task = TaskQueue(**kwargs)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return TaskQueueResponse.model_validate(task)


async def get_next_task(db: AsyncSession) -> TaskQueue | None:
    """
    Claim and return the next PENDING task eligible for execution.

    Uses ``SELECT … FOR UPDATE SKIP LOCKED`` to prevent multiple workers
    from claiming the same task concurrently.

    Args:
        db: Active database session.

    Returns:
        The claimed ``TaskQueue`` record with ``status=RUNNING``, or ``None``
        if the queue is empty or all eligible tasks are locked.
    """
    now = datetime.now(timezone.utc)

    # Use WITH FOR UPDATE SKIP LOCKED for concurrent-safe claiming
    # run_after is the DB column; scheduled_at is a Python property alias.
    result = await db.execute(
        select(TaskQueue)
        .where(
            TaskQueue.status == TaskStatus.PENDING,
            TaskQueue.run_after <= now,
        )
        .order_by(TaskQueue.priority.asc(), TaskQueue.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None

    task.status = TaskStatus.RUNNING
    task.started_at = now
    task.attempt_count += 1
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(
    task: TaskQueue,
    result: dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Mark a task as COMPLETED and store its result.

    Args:
        task: The ``TaskQueue`` record to finalise.
        result: Return value from the handler, stored as JSON.
        db: Active database session.
    """
    import json as _json
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc)
    # result column is Text — serialize dict to JSON string
    task.result = _json.dumps(result) if isinstance(result, dict) else str(result)
    task.error_message = None
    await db.commit()


async def fail_task(
    task: TaskQueue,
    error: Exception,
    db: AsyncSession,
) -> None:
    """
    Record a failed task attempt, re-queuing (PENDING) or permanently
    failing (DEAD) based on ``attempt_count`` vs ``max_attempts``.

    Args:
        task: The ``TaskQueue`` record to update.
        error: The exception raised during execution.
        db: Active database session.
    """
    task.error_message = str(error)

    if task.attempt_count >= task.max_attempts:
        task.status = TaskStatus.DEAD
        task.completed_at = datetime.now(timezone.utc)
        logger.warning(
            "Task {id} ({type}) permanently failed after {n} attempts",
            id=task.id,
            type=task.task_type,
            n=task.attempt_count,
        )
    else:
        # Exponential backoff: 2^attempt minutes, capped at 60 minutes
        backoff_seconds = min(60 * 60, 60 * (2 ** task.attempt_count))
        task.status = TaskStatus.PENDING
        task.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        logger.info(
            "Task {id} ({type}) will retry in {s}s (attempt {n}/{max})",
            id=task.id,
            type=task.task_type,
            s=backoff_seconds,
            n=task.attempt_count,
            max=task.max_attempts,
        )

    await db.commit()


# ---------------------------------------------------------------------------
# Concrete task handlers
# ---------------------------------------------------------------------------


@register_task("app.tasks.generate_tests")
async def handle_generate_tests(
    payload: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Execute a queued test-generation job.

    Expected payload keys:
        - ``generation_id`` (str): UUID of the ``Generation`` record.
        - ``user_id`` (str): UUID of the requesting user.

    Args:
        payload: Task payload dict.
        db: Active database session.

    Returns:
        Dict with ``generation_id`` and ``status`` keys.

    Raises:
        GenerationError: If the Claude API call fails.
    """
    generation_id = uuid.UUID(payload["generation_id"])
    user_id = uuid.UUID(payload["user_id"])

    # Fetch the Generation record
    result = await db.execute(select(Generation).where(Generation.id == str(generation_id)))
    gen = result.scalar_one_or_none()
    if gen is None:
        raise GenerationError(message=f"Generation {generation_id} not found")

    # Fetch the User record for the plan (avoids lazy-load in async context)
    user_result = await db.execute(select(User).where(User.id == str(user_id)))
    requesting_user = user_result.scalar_one_or_none()
    plan = requesting_user.plan if requesting_user is not None else "free"

    # Mark as processing
    gen.status = GenerationStatus.PROCESSING
    await db.commit()

    try:
        # Call Claude using the Generation record's actual fields
        client = get_claude_client()
        import asyncio as _asyncio
        generation_result = await _asyncio.to_thread(
            client.generate,
            input_type=gen.input_type,
            input_text=gen.input_text,
            output_format=gen.output_format,
            plan=plan,
        )

        # Persist result using the actual Generation column names
        gen.status = GenerationStatus.COMPLETED
        gen.output_text = generation_result.output_text
        gen.prompt_tokens = generation_result.prompt_tokens
        gen.completion_tokens = generation_result.completion_tokens
        gen.total_tokens = generation_result.total_tokens
        gen.latency_ms = generation_result.latency_ms
        gen.model = generation_result.model
        from datetime import datetime, timezone as _tz
        gen.completed_at = datetime.now(_tz.utc)
        await db.commit()

        # Record usage (reuse already-fetched user)
        if requesting_user is not None:
            await record_usage(
                user=requesting_user,
                generation_id=generation_id,
                prompt_tokens=generation_result.prompt_tokens,
                completion_tokens=generation_result.completion_tokens,
                db=db,
            )

    except Exception as exc:
        gen.status = GenerationStatus.FAILED
        gen.error_message = str(exc)
        await db.commit()
        raise GenerationError(message=str(exc)) from exc

    return {"generation_id": str(generation_id), "status": "completed"}


@register_task("app.tasks.send_welcome_email")
async def handle_send_welcome_email(
    payload: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Send a welcome email to a newly registered user.

    Expected payload keys:
        - ``user_id`` (str): UUID of the new user.

    Args:
        payload: Task payload dict.
        db: Active database session.

    Returns:
        Dict with ``user_id`` and ``sent`` keys.
    """
    user_id = payload["user_id"]
    # Email sending is a future integration; log and no-op for now.
    logger.info("Welcome email task for user {uid} — email integration not yet wired", uid=user_id)
    return {"user_id": user_id, "sent": False}


@register_task("app.tasks.sync_stripe_subscription")
async def handle_sync_stripe_subscription(
    payload: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Re-sync a subscription record from the Stripe API.

    Expected payload keys:
        - ``stripe_subscription_id`` (str): Stripe sub ID to re-fetch.
        - ``user_id`` (str): UUID of the subscription owner.

    Args:
        payload: Task payload dict.
        db: Active database session.

    Returns:
        Dict with ``subscription_id`` and ``plan`` keys.
    """
    import asyncio
    import stripe as _stripe
    from app.billing import BillingService, price_id_to_plan
    from app.models import Subscription

    stripe_sub_id: str = payload["stripe_subscription_id"]
    user_id = uuid.UUID(payload["user_id"])

    try:
        stripe_sub = await asyncio.to_thread(_stripe.Subscription.retrieve, stripe_sub_id)
    except _stripe.StripeError as exc:
        raise GenerationError(message=f"Stripe API error: {exc}") from exc

    # Find user
    user_result = await db.execute(select(User).where(User.id == str(user_id)))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise GenerationError(message=f"User {user_id} not found")

    billing_service = BillingService(db)
    await billing_service._upsert_subscription(user, stripe_sub)

    # Determine plan for response
    items = stripe_sub.get("items", {}).get("data", [])
    price_id = items[0].get("price", {}).get("id") if items else None
    plan = "free"
    if price_id:
        try:
            plan = price_id_to_plan(price_id).value
        except Exception:
            pass

    return {"subscription_id": stripe_sub_id, "plan": plan}


# ---------------------------------------------------------------------------
# Worker classes
# ---------------------------------------------------------------------------


class BackgroundWorker:
    """
    Async worker pool that continuously drains the ``task_queue`` table.

    The worker spawns up to ``concurrency`` coroutines, each of which
    loops: claim a task → execute handler → mark complete/failed → repeat.

    Attributes:
        concurrency: Maximum number of concurrent task coroutines.
        running: True while the worker loop is active.
        _tasks: Set of in-flight asyncio tasks.
    """

    def __init__(self, concurrency: int | None = None) -> None:
        """
        Args:
            concurrency: Max concurrent workers; defaults to 2.
        """
        self.concurrency: int = concurrency if concurrency is not None else 2
        self.running: bool = False
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """
        Start the worker pool.

        Spawns ``concurrency`` asyncio tasks that each run ``_worker_loop``.
        Should be called from the application lifespan startup hook.
        """
        if self.running:
            return
        self.running = True
        for i in range(self.concurrency):
            task = asyncio.create_task(self._worker_loop(), name=f"bg-worker-{i}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        logger.info("BackgroundWorker started with {n} coroutines", n=self.concurrency)

    async def stop(self) -> None:
        """
        Gracefully shut down the worker pool.

        Sets ``running = False`` and waits for all in-flight tasks to
        finish before returning.  Should be called from the lifespan
        shutdown hook.
        """
        self.running = False
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("BackgroundWorker stopped")

    async def _worker_loop(self) -> None:
        """
        Inner loop executed by each worker coroutine.

        Continuously polls for tasks, executes them, and sleeps briefly
        when the queue is empty to avoid busy-waiting.
        """
        while self.running:
            try:
                async for db in get_db():
                    task = await get_next_task(db)
                    if task is None:
                        await asyncio.sleep(settings.task_poll_interval)
                        break
                    await self._execute_task(task, db)
            except Exception as exc:
                logger.exception("Worker loop error: {}", exc)
                await asyncio.sleep(settings.task_poll_interval)

    async def _execute_task(self, task: TaskQueue, db: AsyncSession) -> None:
        """
        Execute a single ``TaskQueue`` record using the registered handler.

        Args:
            task: The claimed task record to execute.
            db: Active database session.
        """
        try:
            handler = get_handler(task.task_type)
        except KeyError:
            await fail_task(task, ValueError(f"Unknown task type: {task.task_type!r}"), db)
            return

        try:
            import json as _json
            if isinstance(task.payload, dict):
                payload = task.payload
            elif task.payload:
                try:
                    payload = _json.loads(task.payload)
                except Exception:
                    payload = {}
            else:
                payload = {}
            result = await handler(payload, db)
            await complete_task(task, result, db)
        except Exception as exc:
            logger.exception("Task {id} ({type}) failed: {err}", id=task.id, type=task.task_type, err=exc)
            await fail_task(task, exc, db)


class DLQWorker:
    """
    Periodic worker that re-queues entries from the ``webhook_dlq`` table.

    Runs on a fixed interval (configurable), selects unresolved DLQ rows,
    and attempts to re-enqueue them as tasks.  Entries that exceed a
    maximum retry count are left in the DLQ for manual intervention.
    """

    _MAX_DLQ_ATTEMPTS = 5

    def __init__(self, interval_seconds: int | None = None) -> None:
        """
        Args:
            interval_seconds: Polling interval; defaults to 300 seconds.
        """
        self.interval_seconds: int = interval_seconds if interval_seconds is not None else 300
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the DLQ polling loop as a background asyncio task."""
        self._task = asyncio.create_task(self._run(), name="dlq-worker")
        logger.info("DLQWorker started (interval={}s)", self.interval_seconds)

    async def stop(self) -> None:
        """Cancel the DLQ polling task and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DLQWorker stopped")

    async def _run(self) -> None:
        """Main polling loop body — runs until ``stop()`` is called."""
        while True:
            try:
                count = await self._process_dlq_batch()
                if count:
                    logger.info("DLQWorker re-queued {} entries", count)
            except Exception as exc:
                logger.exception("DLQWorker error: {}", exc)
            await asyncio.sleep(self.interval_seconds)

    async def _process_dlq_batch(self) -> int:
        """
        Fetch a batch of unresolved DLQ entries and re-enqueue them.

        Returns:
            Number of entries successfully re-queued in this batch.
        """
        re_queued = 0
        async for db in get_db():
            result = await db.execute(
                select(WebhookDLQ)
                .where(
                    WebhookDLQ.resolved_at.is_(None),
                    WebhookDLQ.attempt_count < self._MAX_DLQ_ATTEMPTS,
                )
                .limit(20)
            )
            entries = result.scalars().all()
            for entry in entries:
                try:
                    await enqueue_task(
                        task_type="app.tasks.process_webhook_dlq",
                        payload={"dlq_id": str(entry.id), "event_type": entry.event_type, "payload": entry.payload},
                        db=db,
                    )
                    entry.attempt_count += 1
                    re_queued += 1
                except Exception as exc:
                    logger.exception("DLQWorker failed to re-queue entry {id}: {err}", id=entry.id, err=exc)
            await db.commit()
        return re_queued


class TaskReaper:
    """
    Periodic task that marks stale RUNNING records as FAILED.

    A task is considered stale if it has been in RUNNING state longer
    than ``stale_threshold_seconds`` (e.g. the worker process died
    mid-execution).
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        stale_threshold_seconds: int = 300,
    ) -> None:
        """
        Args:
            interval_seconds: How often to scan for stale tasks.
            stale_threshold_seconds: Age in seconds after which a RUNNING
                task is considered hung and should be reaped.
        """
        self.interval_seconds = interval_seconds
        self.stale_threshold_seconds = stale_threshold_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the reaper loop as a background asyncio task."""
        self._task = asyncio.create_task(self._run(), name="task-reaper")
        logger.info("TaskReaper started (interval={}s, threshold={}s)", self.interval_seconds, self.stale_threshold_seconds)

    async def stop(self) -> None:
        """Cancel the reaper task and wait for clean shutdown."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TaskReaper stopped")

    async def _run(self) -> None:
        """Main reaper loop body."""
        while True:
            try:
                reaped = await self._reap_stale_tasks()
                if reaped:
                    logger.info("TaskReaper reaped {} stale tasks", reaped)
            except Exception as exc:
                logger.exception("TaskReaper error: {}", exc)
            await asyncio.sleep(self.interval_seconds)

    async def _reap_stale_tasks(self) -> int:
        """
        Find and mark timed-out RUNNING tasks as FAILED.

        Returns:
            Number of tasks reaped in this scan.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.stale_threshold_seconds)
        reaped = 0
        async for db in get_db():
            result = await db.execute(
                select(TaskQueue).where(
                    TaskQueue.status == TaskStatus.RUNNING,
                    TaskQueue.started_at < cutoff,
                )
            )
            stale_tasks = result.scalars().all()
            for task in stale_tasks:
                logger.warning(
                    "Reaping stale task {id} ({type}) stuck since {started}",
                    id=task.id,
                    type=task.task_type,
                    started=task.started_at,
                )
                await fail_task(task, TimeoutError("Task timed out in RUNNING state"), db)
                reaped += 1
        return reaped


# ---------------------------------------------------------------------------
# Module-level worker singletons
# ---------------------------------------------------------------------------

_background_worker: BackgroundWorker | None = None
_dlq_worker: DLQWorker | None = None
_task_reaper: TaskReaper | None = None


async def start_all_workers() -> None:
    """
    Initialise and start all background worker singletons.

    Called once from the FastAPI lifespan ``startup`` phase.
    """
    global _background_worker, _dlq_worker, _task_reaper
    _background_worker = BackgroundWorker()
    _dlq_worker = DLQWorker()
    _task_reaper = TaskReaper(
        interval_seconds=int(settings.task_reaper_interval),
        stale_threshold_seconds=300,
    )
    await _background_worker.start()
    await _dlq_worker.start()
    await _task_reaper.start()
    logger.info("All background workers started")


async def stop_all_workers() -> None:
    """
    Gracefully stop all background worker singletons.

    Called once from the FastAPI lifespan ``shutdown`` phase.
    """
    if _background_worker is not None:
        await _background_worker.stop()
    if _dlq_worker is not None:
        await _dlq_worker.stop()
    if _task_reaper is not None:
        await _task_reaper.stop()
    logger.info("All background workers stopped")


# ---------------------------------------------------------------------------
# Startup tasks
# ---------------------------------------------------------------------------


async def run_startup_tasks(db: AsyncSession) -> None:
    """
    Execute one-time tasks that should run every time the application starts.

    Examples:
        - Requeue any tasks left in RUNNING state (from a previous crash).
        - Emit a startup-health log entry.

    Args:
        db: Database session for any required DB work.
    """
    # Reset tasks that were left in RUNNING state from a previous crash
    result = await db.execute(
        select(TaskQueue).where(TaskQueue.status == TaskStatus.RUNNING)
    )
    stuck = result.scalars().all()
    for task in stuck:
        logger.warning(
            "Startup: resetting stuck RUNNING task {id} ({type}) to PENDING",
            id=task.id,
            type=task.task_type,
        )
        task.status = TaskStatus.PENDING
        task.started_at = None

    if stuck:
        await db.commit()
        logger.info("Startup: reset {} stuck tasks to PENDING", len(stuck))

    logger.info("Startup tasks complete")
