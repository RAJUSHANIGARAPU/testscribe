"""
FastAPI dependency functions.

All reusable ``Depends(...)`` callables live here.  They import from
``app.database``, ``app.models``, ``app.schemas``, ``app.auth``, and
``app.exceptions`` — never the other way around — to keep the
dependency graph acyclic.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Query, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db as get_db
from app.exceptions import AuthenticationError, PermissionDeniedError, SubscriptionRequiredError
from app.models import SubscriptionPlan, User, UserRole

# Re-export get_db so callers can do ``from app.dependencies import get_db``
__all__ = [
    "get_db",
    "get_current_user",
    "get_current_active_user",
    "require_role",
    "require_plan",
    "get_optional_user",
    "PaginationParams",
    "pagination_params",
    "DBSession",
    "CurrentUser",
    "ActiveUser",
]

# ---------------------------------------------------------------------------
# Bearer-token extractor (shared across JWT and API-key paths)
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Core auth dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User:
    """
    Resolve the authenticated user from either a JWT bearer token or an
    ``X-API-Key`` header.

    Evaluation order:
        1. ``Authorization: Bearer <jwt>`` header
        2. ``X-API-Key: <key>`` header

    Args:
        db: Active database session.
        credentials: Optional bearer token extracted by ``HTTPBearer``.
        x_api_key: Optional raw API key from the ``X-API-Key`` header.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        AuthenticationError: If no valid credential is present.
        InvalidTokenError: If the JWT is malformed or expired.
        ApiKeyInvalidError: If the API key is not found or revoked.
    """
    from app.auth import AuthService

    auth = AuthService(db)

    # 1. Try Bearer JWT token first
    if credentials is not None and credentials.credentials:
        return await auth.authenticate_from_token(credentials.credentials)

    # 2. Try X-API-Key header
    if x_api_key:
        return await auth.authenticate_from_api_key(x_api_key)

    raise AuthenticationError()


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Extend ``get_current_user`` by additionally asserting the account is active.

    Args:
        current_user: Already-resolved user from ``get_current_user``.

    Returns:
        The same user if the account is active.

    Raises:
        PermissionDeniedError: If ``user.is_active`` is False.
    """
    if not current_user.is_active:
        raise PermissionDeniedError(message="Account is inactive.")
    return current_user


async def get_optional_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User | None:
    """
    Like ``get_current_user`` but returns ``None`` instead of raising when
    no credential is present.  Useful for endpoints that serve both
    anonymous and authenticated traffic.

    Args:
        db: Active database session.
        credentials: Optional bearer token.
        x_api_key: Optional API key header.

    Returns:
        The authenticated user, or ``None`` if unauthenticated.
    """
    from app.auth import AuthService

    auth = AuthService(db)

    try:
        if credentials is not None and credentials.credentials:
            return await auth.authenticate_from_token(credentials.credentials)
        if x_api_key:
            return await auth.authenticate_from_api_key(x_api_key)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Role & plan guard factories
# ---------------------------------------------------------------------------


def require_role(*roles: UserRole):
    """
    Dependency factory that enforces one of the specified roles.

    Usage::

        @router.get("/admin")
        async def admin_endpoint(
            user: User = Depends(require_role(UserRole.ADMIN))
        ): ...

    Args:
        *roles: One or more ``UserRole`` values the user must have.

    Returns:
        An async dependency callable that resolves the active user and
        asserts their role is among the permitted set.

    Raises:
        PermissionDeniedError: If the user's role is not in ``roles``.
    """
    async def _dep(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in roles:
            raise PermissionDeniedError(
                message=f"Role {current_user.role!r} is not permitted. Required: {[r.value for r in roles]}"
            )
        return current_user

    return _dep


def require_plan(*plans: SubscriptionPlan):
    """
    Dependency factory that enforces an active subscription at one of the
    given plan tiers.

    Usage::

        @router.post("/generate")
        async def generate(
            user: User = Depends(require_plan(SubscriptionPlan.STARTER, SubscriptionPlan.PRO))
        ): ...

    Args:
        *plans: One or more ``SubscriptionPlan`` values that satisfy the gate.

    Returns:
        An async dependency callable that resolves the active user,
        loads their subscription, and checks the plan tier.

    Raises:
        SubscriptionRequiredError: If the user's plan is not in ``plans``.
    """
    async def _dep(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.limits import get_user_plan

        user_plan = await get_user_plan(current_user, db)
        if user_plan not in plans:
            raise SubscriptionRequiredError(
                message=f"This feature requires one of the following plans: {[p.value for p in plans]}"
            )
        return current_user

    return _dep


# ---------------------------------------------------------------------------
# Pagination dependency
# ---------------------------------------------------------------------------


class PaginationParams:
    """
    Standard pagination query parameters.

    Attributes:
        page: 1-based page number.
        page_size: Number of items per page (capped at 100).
        offset: Pre-computed SQL offset (``(page - 1) * page_size``).
    """

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number (1-based)."),
        page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
    ) -> None:
        """
        Args:
            page: Requested page number.
            page_size: Number of items per page.
        """
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        """Return the SQL OFFSET value for this page."""
        return (self.page - 1) * self.page_size


def pagination_params(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginationParams:
    """
    FastAPI-compatible dependency function that returns a ``PaginationParams``
    instance.  Prefer using this over instantiating ``PaginationParams``
    directly in route signatures.

    Args:
        page: Requested page number.
        page_size: Number of items per page.

    Returns:
        Populated ``PaginationParams``.
    """
    return PaginationParams(page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Type aliases for cleaner route signatures
# ---------------------------------------------------------------------------

DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
