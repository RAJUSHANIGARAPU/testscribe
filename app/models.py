"""
SQLAlchemy ORM models — SQLite-compatible.

All models use:
- String(36) primary keys with uuid4 defaults
- sqlalchemy.JSON for JSON columns (not JSONB)
- String columns for enum-like fields with CheckConstraints
- DateTime(timezone=True) for all timestamp columns

Tables:
    users            – registered accounts
    refresh_tokens   – JWT refresh token registry
    api_keys         – bearer tokens for programmatic access
    subscriptions    – Stripe subscription state per user
    generations      – individual AI generation records
    usage_daily      – pre-aggregated daily usage counters
    stripe_events    – idempotency log for processed Stripe webhook events
    webhook_dlq      – dead-letter queue for unprocessable webhook payloads
    task_queue       – persistent background task records
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enum shims
#
# The ORM columns use plain String fields (SQLite-compatible) with
# CheckConstraints.  These StrEnum classes give auth.py, billing.py,
# limits.py, tasks.py, and dependencies.py typed constants whose .value
# matches the DB string exactly.
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPPORT = "support"


class SubscriptionPlan(str, Enum):
    FREE = "free"
    STARTER = "solo"   # maps to the "solo" DB value
    PRO = "pro"
    ENTERPRISE = "team"  # maps to the "team" DB value


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"
    INCOMPLETE = "incomplete"
    UNPAID = "unpaid"


class GenerationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    """Generate a new UUID4 string suitable for use as a String(36) PK."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(Base):
    """Registered user account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True,
        doc="User email address (RFC 5321 max 320 chars).",
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        doc="bcrypt hash of the password; NULL for OAuth-only accounts.",
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Display name.",
    )
    plan: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="free",
        doc="Active plan: free | solo | pro | team.",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        doc="Access-control role: user | admin | support.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Soft-delete / account-suspension flag.",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True once email ownership is confirmed.",
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
        doc="Stripe Customer ID (cus_...).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Row creation timestamp (UTC, server-generated).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Row last-update timestamp (UTC, auto-updated).",
    )

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="user", uselist=False
    )
    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="user", cascade="all, delete-orphan"
    )
    usage_daily: Mapped[list["UsageDaily"]] = relationship(
        "UsageDaily", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("plan IN ('free','solo','pro','team')", name="ck_users_plan"),
        CheckConstraint("role IN ('user','admin','support')", name="ck_users_role"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} plan={self.plan}>"


class RefreshToken(Base):
    """JWT refresh token registry."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owning user.",
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        doc="SHA-256 hex digest of the raw refresh token.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Hard expiry; token is invalid after this timestamp.",
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True once the token has been explicitly revoked.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Row creation timestamp.",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")

    def __repr__(self) -> str:
        return f"<RefreshToken id={self.id} user_id={self.user_id} revoked={self.revoked}>"


class ApiKey(Base):
    """API key for programmatic access."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owning user.",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Human-readable label, e.g. 'CI pipeline'.",
    )
    key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        doc="SHA-256 hex digest of the raw key.",
    )
    key_prefix: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        doc="First characters of the raw key shown in the UI.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Soft-revoke flag.",
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of most recent authenticated call.",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Optional hard expiry; NULL means no expiry.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    __table_args__ = (Index("ix_api_keys_user_active", "user_id", "is_active"),)

    def __repr__(self) -> str:
        return f"<ApiKey id={self.id} prefix={self.key_prefix!r} active={self.is_active}>"


class Subscription(Base):
    """Stripe subscription state per user (one-to-one with User)."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        doc="Owning user (1-to-1).",
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
        doc="Stripe Subscription ID (sub_...).",
    )
    stripe_price_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Active Stripe Price ID.",
    )
    plan: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="free",
        doc="Resolved plan: free | solo | pro | team.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        doc="Stripe lifecycle status.",
    )
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Start of current billing period.",
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="End of current billing period.",
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Scheduled for cancellation at period end.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscription")

    __table_args__ = (
        CheckConstraint(
            "plan IN ('free','solo','pro','team')", name="ck_subscriptions_plan"
        ),
        CheckConstraint(
            "status IN ('active','past_due','canceled','trialing','incomplete','unpaid')",
            name="ck_subscriptions_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} plan={self.plan} status={self.status}>"


class Generation(Base):
    """Record of a single AI test-generation request."""

    __tablename__ = "generations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Requesting user.",
    )
    input_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Input type: user_story | requirement | openapi | jira_text | raw.",
    )
    input_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Original input submitted for generation.",
    )
    output_format: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Output format: gherkin | tabular | pytest.",
    )
    output_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="AI-generated output; NULL until generation completes.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        doc="Lifecycle state: pending | processing | completed | failed.",
    )
    model: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Claude model ID used for this generation.",
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Tokens consumed in the prompt.",
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Tokens in the completion.",
    )
    total_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Sum of prompt + completion tokens.",
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="End-to-end latency in milliseconds.",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error detail when status=failed.",
    )
    via_api_key: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True when the request was authenticated via an API key.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when generation finished (success or failure).",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="generations")

    __table_args__ = (
        CheckConstraint(
            "input_type IN ('user_story','requirement','openapi','jira_text','raw')",
            name="ck_generations_input_type",
        ),
        CheckConstraint(
            "output_format IN ('gherkin','tabular','pytest')",
            name="ck_generations_output_format",
        ),
        CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="ck_generations_status",
        ),
        Index("ix_generations_user_created", "user_id", "created_at"),
        Index("ix_generations_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Generation id={self.id} status={self.status} format={self.output_format}>"


class UsageDaily(Base):
    """Pre-aggregated daily usage counters per user."""

    __tablename__ = "usage_daily"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owning user.",
    )
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="Calendar date (UTC).",
    )
    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of completed generations on this date.",
    )
    tokens_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total tokens consumed on this date.",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="usage_daily")

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_usage_daily_user_date"),
        Index("ix_usage_daily_user_date", "user_id", "date"),
    )

    def __repr__(self) -> str:
        return f"<UsageDaily user={self.user_id} date={self.date} count={self.count}>"


class StripeEvent(Base):
    """Idempotency log for processed Stripe webhook events."""

    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        doc="Stripe event ID (evt_...) — used as natural PK for idempotency.",
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Stripe event type, e.g. 'customer.subscription.updated'.",
    )
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Raw Stripe event JSON stored for audit/replay.",
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Timestamp when this event was successfully processed.",
    )

    def __repr__(self) -> str:
        return f"<StripeEvent id={self.stripe_event_id} type={self.event_type!r}>"


class WebhookDLQ(Base):
    """Dead-letter queue for unprocessable webhook payloads."""

    __tablename__ = "webhook_dlq"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="stripe",
        doc="Originating service, e.g. 'stripe'.",
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Event type from the originating service.",
    )
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Raw request body as received.",
    )
    error_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Exception or error detail from the last processing attempt.",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Number of processing attempts made so far.",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        doc="Maximum allowed attempts before the entry is considered permanently dead.",
    )
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Earliest time the DLQ worker should re-attempt processing.",
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True once the entry has been manually or automatically resolved.",
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when resolved; NULL = still open.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("ix_webhook_dlq_resolved", "resolved"),)

    def __repr__(self) -> str:
        return f"<WebhookDLQ id={self.id} source={self.source!r} type={self.event_type!r}>"


class TaskQueue(Base):
    """Persistent background task queue."""

    __tablename__ = "task_queue"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        doc="UUID v4 surrogate primary key.",
    )
    task_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Dotted handler name, e.g. 'app.tasks.generate_tests'.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        doc="Lifecycle state: pending | running | completed | failed | dead.",
    )
    payload: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="JSON-serialised task arguments.",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        doc="Lower value = higher priority (1 = highest, 10 = lowest).",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of execution attempts made.",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        doc="Maximum allowed attempts before marking as dead.",
    )
    # Optional owning user (informational only — not a FK constraint here so
    # tasks can outlive users).
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        doc="Owning user ID (informational; no FK cascade).",
    )
    # run_after / scheduled_at are the same concept — keep both names as
    # aliases so main.py (run_after) and tasks.py (scheduled_at) both work.
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Earliest wall-clock time to attempt execution (alias: scheduled_at).",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the current/last attempt was claimed by a worker.",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the task finished (success or permanent failure).",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error from the most recent failed attempt.",
    )
    # result stores the JSON-serialised handler return value.
    result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="JSON-serialised return value captured on success.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ---------------------------------------------------------------------------
    # scheduled_at property — alias for run_after so tasks.py can use either name
    # ---------------------------------------------------------------------------

    @property
    def scheduled_at(self) -> datetime:
        """Alias for ``run_after`` used by the async task layer."""
        return self.run_after

    @scheduled_at.setter
    def scheduled_at(self, value: datetime) -> None:
        self.run_after = value

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','dead')",
            name="ck_task_queue_status",
        ),
        Index("ix_task_queue_status_priority", "status", "priority", "created_at"),
        Index("ix_task_queue_run_after_status", "run_after", "status"),
    )

    def __repr__(self) -> str:
        return f"<TaskQueue id={self.id} type={self.task_type!r} status={self.status}>"
