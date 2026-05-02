"""
Authentication and authorisation service.

Handles user registration, login, JWT issuance/verification, refresh
token rotation, and API key lifecycle management.

Import chain (no circularity):
    auth → database, models, schemas, exceptions, config
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    ApiKeyInvalidError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    TokenExpiredError,
    UserAlreadyExistsError,
)
from app.models import ApiKey, Subscription, SubscriptionPlan, User, UserRole
from app.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
)


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------


def hash_password(plain_password: str) -> str:
    """
    Hash ``plain_password`` with bcrypt at work-factor 12.

    Args:
        plain_password: The user-supplied plaintext password.

    Returns:
        bcrypt hash string suitable for storing in the database.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify ``plain_password`` against a stored bcrypt hash.

    Args:
        plain_password: The candidate plaintext password.
        hashed_password: The stored bcrypt hash.

    Returns:
        ``True`` if the password matches, ``False`` otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str | uuid.UUID,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Token subject — typically the user UUID as a string.
        extra_claims: Additional claims to embed (e.g. ``role``).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: str | uuid.UUID) -> str:
    """
    Create a signed JWT refresh token with a longer TTL.

    Args:
        subject: Token subject — typically the user UUID as a string.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT, returning the claims payload.

    Args:
        token: The raw encoded JWT string.

    Returns:
        Decoded claims dict.

    Raises:
        TokenExpiredError: If ``exp`` claim is in the past.
        InvalidTokenError: If signature or structure is invalid.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError() from exc


def _build_token_response(user: User) -> TokenResponse:
    """
    Build a ``TokenResponse`` for the given user.

    Args:
        user: The authenticated user ORM instance.

    Returns:
        ``TokenResponse`` with fresh access and refresh tokens.
    """
    extra = {"role": user.role.value if hasattr(user.role, "value") else user.role}
    access_token = create_access_token(user.id, extra_claims=extra)
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# API key helpers
# ---------------------------------------------------------------------------


def _generate_raw_api_key(prefix: str = "tsc_") -> str:
    """
    Generate a cryptographically random API key string.

    Args:
        prefix: Key prefix (e.g. ``"tsc_"``).

    Returns:
        Full raw key string, e.g. ``"tsc_abc123..."``.
    """
    return prefix + secrets.token_hex(16)


def hash_api_key(raw_key: str) -> str:
    """
    Return the SHA-256 hex digest of the raw API key for storage.

    Args:
        raw_key: The plaintext API key.

    Returns:
        64-character hex string.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Auth service
# ---------------------------------------------------------------------------


class AuthService:
    """
    Stateless service class encapsulating all auth operations.

    An instance is constructed per-request inside the dependency and
    receives the database session via constructor injection.
    """

    def __init__(self, db: AsyncSession) -> None:
        """
        Args:
            db: The active async database session for this request.
        """
        self.db = db

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(self, payload: UserRegisterRequest) -> UserResponse:
        """
        Create a new user account.

        Validates uniqueness of the email, hashes the password, and
        persists the new ``User`` record.

        Args:
            payload: Registration request containing email and password.

        Returns:
            ``UserResponse`` for the newly created user.

        Raises:
            UserAlreadyExistsError: If the email is already registered.
        """
        # Check for existing user
        existing = await self.get_user_by_email(str(payload.email))
        if existing is not None:
            raise UserAlreadyExistsError()

        hashed = hash_password(payload.password.get_secret_value())
        user = User(
            email=str(payload.email),
            hashed_password=hashed,
            full_name=payload.full_name,
            role=UserRole.USER,
            is_active=True,
            is_verified=False,
        )
        self.db.add(user)
        await self.db.flush()  # get the user.id before creating subscription

        # Create a default free subscription
        subscription = Subscription(
            user_id=user.id,
            plan=SubscriptionPlan.FREE,
        )
        self.db.add(subscription)
        await self.db.commit()
        await self.db.refresh(user)
        return UserResponse.model_validate(user)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> TokenResponse:
        """
        Authenticate with email and password, returning a token pair.

        Args:
            email: The user's email address.
            password: The plaintext password.

        Returns:
            JWT access + refresh token pair.

        Raises:
            InvalidCredentialsError: If the email is not found or the
                password does not match.
        """
        user = await self.get_user_by_email(email)
        if user is None or not user.hashed_password:
            raise InvalidCredentialsError()
        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        return _build_token_response(user)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """
        Issue a new token pair from a valid refresh token.

        Args:
            refresh_token: The encoded refresh JWT.

        Returns:
            New JWT access + refresh token pair.

        Raises:
            TokenExpiredError: If the refresh token has expired.
            InvalidTokenError: If the token is malformed or not a refresh token.
        """
        claims = decode_token(refresh_token)
        if claims.get("type") != "refresh":
            raise InvalidTokenError()

        user_id_str = claims.get("sub")
        if not user_id_str:
            raise InvalidTokenError()

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError as exc:
            raise InvalidTokenError() from exc

        user = await self.get_user_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        return _build_token_response(user)

    # ------------------------------------------------------------------
    # User queries
    # ------------------------------------------------------------------

    async def get_user_by_id(self, user_id: uuid.UUID | str) -> User | None:
        """
        Fetch a user by their primary key.

        Args:
            user_id: UUID of the user to look up (UUID or str).

        Returns:
            The ``User`` ORM instance, or ``None`` if not found.
        """
        result = await self.db.execute(select(User).where(User.id == str(user_id)))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        """
        Fetch a user by email address.

        Args:
            email: The email address to look up.

        Returns:
            The ``User`` ORM instance, or ``None`` if not found.
        """
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def authenticate_from_token(self, token: str) -> User:
        """
        Resolve a ``User`` from a raw JWT string.

        Args:
            token: Encoded JWT access token.

        Returns:
            The authenticated ``User`` ORM instance.

        Raises:
            InvalidTokenError: On decode failure or if user not found.
            TokenExpiredError: If the token has expired.
        """
        claims = decode_token(token)
        if claims.get("type") != "access":
            raise InvalidTokenError()

        user_id_str = claims.get("sub")
        if not user_id_str:
            raise InvalidTokenError()

        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError as exc:
            raise InvalidTokenError() from exc

        user = await self.get_user_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        return user

    async def authenticate_from_api_key(self, raw_key: str) -> User:
        """
        Resolve a ``User`` from a raw API key string.

        Hashes the key and looks up the matching ``ApiKey`` record,
        then updates ``last_used_at``.

        Args:
            raw_key: The plaintext API key.

        Returns:
            The owning ``User`` ORM instance.

        Raises:
            ApiKeyInvalidError: If the key is not found, inactive, or expired.
        """
        key_hash = hash_api_key(raw_key)
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active.is_(True),
            )
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise ApiKeyInvalidError()

        # Check expiry
        now = datetime.now(timezone.utc)
        if api_key.expires_at is not None:
            expires_at = api_key.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < now:
                raise ApiKeyInvalidError()

        # Update last_used_at
        api_key.last_used_at = now
        await self.db.commit()

        user = await self.get_user_by_id(api_key.user_id)
        if user is None:
            raise ApiKeyInvalidError()
        return user

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    async def create_api_key(
        self,
        user: User,
        payload: ApiKeyCreateRequest,
    ) -> ApiKeyCreatedResponse:
        """
        Generate and persist a new API key for ``user``.

        The raw key is returned exactly once in the response and is not
        stored; only the SHA-256 hash is persisted.

        Args:
            user: The user who owns the new key.
            payload: Request containing the key name and optional TTL.

        Returns:
            ``ApiKeyCreatedResponse`` including the raw key (shown once).
        """
        raw_key = _generate_raw_api_key("tsc_")
        key_hash = hash_api_key(raw_key)
        key_prefix = raw_key[:12]

        expires_at: datetime | None = None
        if payload.expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

        api_key = ApiKey(
            user_id=user.id,
            name=payload.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            is_active=True,
            expires_at=expires_at,
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)

        return ApiKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            raw_key=raw_key,
            expires_at=api_key.expires_at,
            created_at=api_key.created_at,
            updated_at=api_key.updated_at,
        )

    async def revoke_api_key(self, user: User, key_id: uuid.UUID | str) -> None:
        """
        Soft-revoke an API key by setting ``is_active = False``.

        Args:
            user: The user who owns the key (used for ownership assertion).
            key_id: UUID of the ``ApiKey`` record to revoke (UUID or str).

        Raises:
            NotFoundError: If the key does not exist or belongs to another user.
        """
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.id == str(key_id),
                ApiKey.user_id == str(user.id),
            )
        )
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise NotFoundError()
        api_key.is_active = False
        await self.db.commit()

    async def list_api_keys(self, user: User) -> list[ApiKey]:
        """
        Return all active API keys for ``user``.

        Args:
            user: The user whose keys to list.

        Returns:
            List of ``ApiKey`` ORM instances.
        """
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.user_id == user.id,
                ApiKey.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Password management
    # ------------------------------------------------------------------

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """
        Verify the current password and replace it with a new hash.

        Args:
            user: The user changing their password.
            current_password: Plaintext of the existing password.
            new_password: Plaintext of the desired new password.

        Raises:
            InvalidCredentialsError: If ``current_password`` is wrong.
        """
        if not user.hashed_password or not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError()
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
