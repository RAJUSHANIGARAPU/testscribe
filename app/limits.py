"""
Usage gate and recording layer.

Responsible for:
    - Checking whether a user has remaining quota before a generation
    - Atomically recording usage after a successful generation
    - Returning usage summaries for the dashboard

Import chain (no circularity):
    limits → database, models, schemas, exceptions, config
    (never imports from auth, ai, billing, tasks)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import UsageLimitExceededError
from app.models import Generation, Subscription, SubscriptionPlan, UsageDaily, User
from app.schemas import UsageDailyResponse, UsageSummaryResponse


# ---------------------------------------------------------------------------
# Plan limits registry
# ---------------------------------------------------------------------------


class PlanLimit(NamedTuple):
    """
    Daily generation limits for a single subscription plan tier.

    Attributes:
        daily_generations: Maximum allowed completed generations per calendar day.
    """

    daily_generations: int


# Plan → daily generation cap.  None means unlimited (enterprise / internal).
_PLAN_DAILY_CAPS: dict[SubscriptionPlan, int] = {
    SubscriptionPlan.FREE: 5,
    SubscriptionPlan.STARTER: 50,
    SubscriptionPlan.PRO: 200,
    SubscriptionPlan.ENTERPRISE: 1_000,
}

PLAN_LIMITS: dict[SubscriptionPlan, PlanLimit] = {}
"""
Maps each ``SubscriptionPlan`` to its ``PlanLimit``.

Populated at module load time from ``settings``; never mutated at runtime.
"""


def _build_plan_limits() -> dict[SubscriptionPlan, PlanLimit]:
    """
    Build the plan-limits mapping from application settings.

    Returns:
        Dict mapping each ``SubscriptionPlan`` to its ``PlanLimit``.
    """
    return {plan: PlanLimit(daily_generations=cap) for plan, cap in _PLAN_DAILY_CAPS.items()}


# Populate on module load
PLAN_LIMITS.update(_build_plan_limits())


# ---------------------------------------------------------------------------
# Usage gate
# ---------------------------------------------------------------------------


async def check_usage_gate(user: User, db: AsyncSession) -> None:
    """
    Assert that ``user`` has not exhausted their daily generation quota.

    Resolves the user's current plan from the ``subscriptions`` table,
    looks up today's usage from ``usage_daily``, and raises if the
    daily limit has been reached.

    This function should be called at the top of the generation handler,
    *before* the Claude API is invoked, to avoid burning tokens on
    requests that would be rejected anyway.

    Args:
        user: The authenticated requesting user.
        db: Active database session.

    Raises:
        UsageLimitExceededError: If ``used_today >= daily_limit``.
    """
    plan = await get_user_plan(user, db)
    limit = get_daily_limit_for_plan(plan)
    used = await get_daily_usage_count(user.id, db)
    if used >= limit:
        raise UsageLimitExceededError(
            message=f"Daily generation limit of {limit} reached for plan {plan.value}.",
            details={"used": used, "limit": limit, "plan": plan.value},
        )


async def get_user_plan(user: User, db: AsyncSession) -> SubscriptionPlan:
    """
    Return the current subscription plan for ``user``.

    Falls back to ``FREE`` if no subscription record exists.

    Args:
        user: The user whose plan to look up.
        db: Active database session.

    Returns:
        The user's ``SubscriptionPlan``.
    """
    result = await db.execute(
        select(Subscription.plan).where(Subscription.user_id == user.id)
    )
    plan = result.scalar_one_or_none()
    return plan if plan is not None else SubscriptionPlan.FREE


# ---------------------------------------------------------------------------
# Usage recording
# ---------------------------------------------------------------------------


async def record_usage(
    user: User,
    generation_id: uuid.UUID,
    prompt_tokens: int,
    completion_tokens: int,
    db: AsyncSession,
) -> None:
    """
    Atomically increment today's ``usage_daily`` counters for ``user``.

    Uses PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` so concurrent
    requests do not cause lost updates.

    Args:
        user: The user to credit usage against.
        generation_id: UUID of the ``Generation`` record being finalised.
        prompt_tokens: Prompt tokens consumed in this generation.
        completion_tokens: Completion tokens returned in this generation.
        db: Active database session.
    """
    today = _today_utc()
    today_dt = datetime(today.year, today.month, today.day)  # naive, matches DB column

    # Determine if we can use the PostgreSQL dialect upsert
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    dialect_name = ""
    try:
        engine = db.bind  # type: ignore[attr-defined]
        if engine is not None:
            dialect_name = engine.dialect.name
    except AttributeError:
        pass

    total_tokens = prompt_tokens + completion_tokens

    if dialect_name == "postgresql":
        stmt = (
            pg_insert(UsageDaily)
            .values(
                id=str(uuid.uuid4()),
                user_id=user.id,
                date=today_dt,
                count=1,
                tokens_used=total_tokens,
            )
            .on_conflict_do_update(
                constraint="uq_usage_daily_user_date",
                set_={
                    "count": UsageDaily.count + 1,
                    "tokens_used": UsageDaily.tokens_used + total_tokens,
                },
            )
        )
        await db.execute(stmt)
    else:
        # SQLite / generic fallback: fetch-then-update in the same session.
        # Wrap INSERT in try/except IntegrityError to handle the rare concurrent-
        # request race where two sessions both see row=None and both try to INSERT.
        result = await db.execute(
            select(UsageDaily).where(
                UsageDaily.user_id == user.id,
                UsageDaily.date == today_dt,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            try:
                row = UsageDaily(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    date=today_dt,
                    count=1,
                    tokens_used=total_tokens,
                )
                db.add(row)
                await db.flush()  # flush to catch IntegrityError before commit
            except IntegrityError:
                await db.rollback()
                # Another concurrent request already inserted — fall back to UPDATE
                result2 = await db.execute(
                    select(UsageDaily).where(
                        UsageDaily.user_id == user.id,
                        UsageDaily.date == today_dt,
                    )
                )
                row = result2.scalar_one()
                row.count += 1
                row.tokens_used += total_tokens
        else:
            row.count += 1
            row.tokens_used += total_tokens

    await db.commit()


def _today_utc() -> date:
    """
    Return today's date in UTC as a ``datetime.date``.

    Extracted as a helper so tests can patch it for time-travel scenarios.

    Returns:
        Current UTC date.
    """
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Usage queries
# ---------------------------------------------------------------------------


async def get_usage_summary(user: User, db: AsyncSession) -> UsageSummaryResponse:
    """
    Build a full usage summary for the dashboard.

    Fetches:
        - The user's current plan and its daily limit.
        - Today's generation count.
        - The last 30 days of ``usage_daily`` history.

    Args:
        user: The user whose usage to summarise.
        db: Active database session.

    Returns:
        ``UsageSummaryResponse`` with plan, limits, and daily history.
    """
    plan = await get_user_plan(user, db)
    daily_limit = get_daily_limit_for_plan(plan)
    used_today = await get_daily_usage_count(user.id, db)
    remaining = max(0, daily_limit - used_today)
    history = await get_daily_history(user.id, 30, db)

    return UsageSummaryResponse(
        plan=plan,
        daily_limit=daily_limit,
        used_today=used_today,
        remaining_today=remaining,
        daily_history=history,
    )


async def get_daily_usage_count(user_id: uuid.UUID | str, db: AsyncSession) -> int:
    """
    Return the number of completed generations for ``user_id`` today (UTC).

    Args:
        user_id: UUID (or string) of the user to query.
        db: Active database session.

    Returns:
        Integer count (0 if no record exists for today).
    """
    today = _today_utc()
    today_dt = datetime(today.year, today.month, today.day)

    result = await db.execute(
        select(UsageDaily.count).where(
            UsageDaily.user_id == str(user_id),
            UsageDaily.date == today_dt,
        )
    )
    count = result.scalar_one_or_none()
    return count if count is not None else 0


async def get_daily_history(
    user_id: uuid.UUID | str,
    days: int,
    db: AsyncSession,
) -> list[UsageDailyResponse]:
    """
    Return the most recent ``days`` days of daily usage records for ``user_id``.

    Args:
        user_id: UUID (or string) of the user to query.
        days: Number of calendar days of history to return (max 90).
        db: Active database session.

    Returns:
        List of ``UsageDailyResponse`` ordered by date descending.
    """
    days = min(days, 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_dt = datetime(cutoff.year, cutoff.month, cutoff.day)

    result = await db.execute(
        select(UsageDaily)
        .where(
            UsageDaily.user_id == str(user_id),
            UsageDaily.date >= cutoff_dt,
        )
        .order_by(UsageDaily.date.desc())
    )
    rows = result.scalars().all()
    return [UsageDailyResponse.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# Limit helpers for dependency injection
# ---------------------------------------------------------------------------


def get_daily_limit_for_plan(plan: SubscriptionPlan) -> int:
    """
    Return the daily generation limit integer for a given plan.

    Args:
        plan: The subscription plan tier.

    Returns:
        Daily generation cap as an integer.
    """
    plan_limit = PLAN_LIMITS.get(plan)
    if plan_limit is None:
        return _PLAN_DAILY_CAPS.get(SubscriptionPlan.FREE, 5)
    return plan_limit.daily_generations
