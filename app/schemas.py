"""
Pydantic v2 request/response schemas.

Self-contained: imports only from the standard library and Pydantic.
No SQLAlchemy models or other app modules are imported to avoid circular
dependencies.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator


# ---------------------------------------------------------------------------
# Common config
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Common Pydantic v2 config shared by all schemas."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------


class RegisterRequest(_BaseSchema):
    """Payload for POST /auth/register."""

    email: EmailStr = Field(..., description="Valid email address.")
    password: SecretStr = Field(..., min_length=8, description="Min 8 chars.")
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: SecretStr) -> SecretStr:
        """Reject trivially weak passwords."""
        raw = v.get_secret_value()
        if len(raw) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in raw):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in raw):
            raise ValueError("Password must contain at least one digit.")
        return v


class LoginRequest(_BaseSchema):
    """Payload for POST /auth/login."""

    email: EmailStr
    password: SecretStr


class TokenResponse(_BaseSchema):
    """JWT token pair returned after successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token TTL in seconds.")


class RefreshRequest(_BaseSchema):
    """Payload for POST /auth/refresh."""

    refresh_token: str


class UserResponse(_BaseSchema):
    """Public user representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: Optional[str]
    plan: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class PasswordChangeRequest(_BaseSchema):
    """Payload for POST /auth/change-password."""

    current_password: SecretStr
    new_password: SecretStr = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if len(raw) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in raw):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in raw):
            raise ValueError("Password must contain at least one digit.")
        return v

    @model_validator(mode="after")
    def passwords_differ(self) -> "PasswordChangeRequest":
        """New password must differ from the current one."""
        if self.current_password.get_secret_value() == self.new_password.get_secret_value():
            raise ValueError("New password must be different from the current password.")
        return self


# ---------------------------------------------------------------------------
# API key schemas
# ---------------------------------------------------------------------------


class ApiKeyCreate(_BaseSchema):
    """Payload for POST /auth/api-keys."""

    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(
        None, ge=1, le=365, description="TTL in days; omit for no expiry."
    )


class ApiKeyResponse(_BaseSchema):
    """API key list item (raw key never returned after creation)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ApiKeyCreatedResponse(_BaseSchema):
    """
    Response for a newly created API key.

    ``raw_key`` is shown exactly once; it is not stored server-side.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    raw_key: str = Field(..., description="Full key value — shown once only.")
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Generation schemas
# ---------------------------------------------------------------------------


class GenerateRequest(_BaseSchema):
    """Payload for POST /generate."""

    input_type: Literal["user_story", "requirement", "openapi", "jira_text", "raw"] = Field(
        ..., description="Type of the input being submitted."
    )
    input_text: str = Field(
        ...,
        min_length=10,
        max_length=50_000,
        description="Input text to generate test cases from.",
    )
    output_format: Literal["gherkin", "tabular", "pytest"] = Field(
        ..., description="Desired output format for the generated test cases."
    )
    extra_instructions: Optional[str] = Field(
        None,
        max_length=1_000,
        description="Optional free-text guidance for the model.",
    )


class GenerateResponse(_BaseSchema):
    """Single generation record as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    input_type: str
    output_format: str
    output_text: Optional[str]
    status: str
    model: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: Optional[int]
    error_message: Optional[str]
    via_api_key: bool
    created_at: datetime
    completed_at: Optional[datetime]


class GenerationListItem(_BaseSchema):
    """Summary row for a generation record in a list view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    input_type: str
    output_format: str
    status: str
    total_tokens: Optional[int]
    latency_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]


class GenerationListResponse(_BaseSchema):
    """Paginated list of generation records."""

    items: list[GenerationListItem]
    total: int
    page: int
    page_size: int
    has_next: bool


# ---------------------------------------------------------------------------
# Billing schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(_BaseSchema):
    """Payload for POST /billing/checkout."""

    plan: Literal["solo", "pro", "team"] = Field(
        ..., description="Target plan to subscribe to."
    )
    success_url: str = Field(..., description="Redirect URL after successful payment.")
    cancel_url: str = Field(..., description="Redirect URL if the user cancels.")


class CheckoutResponse(_BaseSchema):
    """Stripe checkout session details returned to the frontend."""

    session_id: str
    checkout_url: str


class SubscriptionResponse(_BaseSchema):
    """Current subscription state for a user."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan: str
    status: str
    stripe_subscription_id: Optional[str]
    stripe_price_id: Optional[str]
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime


class PortalResponse(_BaseSchema):
    """Stripe billing portal session URL."""

    portal_url: str


class WebhookAcknowledgeResponse(_BaseSchema):
    """Minimal response body returned from POST /billing/webhook."""

    received: bool = True


# ---------------------------------------------------------------------------
# Usage schemas
# ---------------------------------------------------------------------------


class CurrentMonthUsage(_BaseSchema):
    """Aggregated usage for the current calendar month."""

    total_generations: int
    total_tokens: int
    days_active: int


class UsageHistoryItem(_BaseSchema):
    """Daily usage counters for a single calendar date."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    count: int
    tokens_used: int


class UsageResponse(_BaseSchema):
    """Usage overview returned to the user."""

    plan: str
    daily_limit: int
    used_today: int
    remaining_today: int
    current_month: CurrentMonthUsage
    daily_history: list[UsageHistoryItem]


# Aliases used by limits.py (map directly onto the UsageDaily ORM model columns)
class UsageDailyResponse(_BaseSchema):
    """Per-day usage record as returned by the limits service."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    count: int
    tokens_used: int


class UsageSummaryResponse(_BaseSchema):
    """Full usage summary including plan, limits, and history."""

    plan: str
    daily_limit: int
    used_today: int
    remaining_today: int
    daily_history: list[UsageDailyResponse]


# ---------------------------------------------------------------------------
# Admin schemas
# ---------------------------------------------------------------------------


class AdminStatsResponse(_BaseSchema):
    """High-level platform statistics for the admin dashboard."""

    total_users: int
    active_subscriptions: int
    generations_today: int
    generations_total: int
    revenue_mtd_cents: int


class AdminUserResponse(_BaseSchema):
    """Extended user representation visible only to admins."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: Optional[str]
    plan: str
    role: str
    is_active: bool
    is_verified: bool
    stripe_customer_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    subscription: Optional[SubscriptionResponse]


class AdminUserListResponse(_BaseSchema):
    """Paginated list of all users for the admin panel."""

    items: list[AdminUserResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class AdminUserUpdateRequest(_BaseSchema):
    """Admin payload for PATCH /admin/users/{user_id}."""

    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None


# ---------------------------------------------------------------------------
# Schema aliases used by auth.py
# ---------------------------------------------------------------------------

# auth.py imports UserRegisterRequest and ApiKeyCreateRequest; map them to the
# canonical names that main.py and the routes actually use.
UserRegisterRequest = RegisterRequest
ApiKeyCreateRequest = ApiKeyCreate


# ---------------------------------------------------------------------------
# Billing aliases used by billing.py
# ---------------------------------------------------------------------------

class CheckoutSessionRequest(_BaseSchema):
    """Alias-compatible checkout request used by BillingService."""

    plan: str = Field(..., description="Target plan: solo | pro | team.")
    success_url: str = Field(..., description="Redirect after successful payment.")
    cancel_url: str = Field(..., description="Redirect if the user cancels.")


class CheckoutSessionResponse(_BaseSchema):
    """Alias for CheckoutResponse used by BillingService."""

    session_id: str
    checkout_url: str


class PortalSessionResponse(_BaseSchema):
    """Stripe billing portal session response used by BillingService."""

    portal_url: str


# ---------------------------------------------------------------------------
# Task schemas
# ---------------------------------------------------------------------------


class TaskQueueResponse(_BaseSchema):
    """Response schema for a TaskQueue record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_type: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    user_id: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Common / shared schemas
# ---------------------------------------------------------------------------


class ErrorResponse(_BaseSchema):
    """Standard error response body."""

    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable description.")
    details: Optional[dict[str, Any]] = Field(
        None, description="Additional structured context."
    )


class PaginationParams(_BaseSchema):
    """Reusable pagination query parameters."""

    page: int = Field(1, ge=1, description="1-based page number.")
    page_size: int = Field(20, ge=1, le=100, description="Items per page.")

    @property
    def offset(self) -> int:
        """Calculate the SQL OFFSET value from page and page_size."""
        return (self.page - 1) * self.page_size


class ValidationErrorResponse(_BaseSchema):
    """422 Unprocessable Entity body wrapping Pydantic validation errors."""

    code: str = "VALIDATION_ERROR"
    message: str = "Request validation failed."
    errors: list[dict[str, Any]]
