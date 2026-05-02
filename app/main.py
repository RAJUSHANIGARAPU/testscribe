"""
TestScribe — FastAPI application factory and all route handlers.

All routes are defined inline (no separate router files).
The lifespan context manager handles startup/shutdown.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Optional

import bcrypt
import jwt
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import dispose_db, get_db, init_db
from app.exceptions import (
    AppException,
    AuthenticationError,
    GenerationError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    SubscriptionRequiredError,
    TokenExpiredError,
    UsageLimitExceededError,
    UserAlreadyExistsError,
    WebhookSignatureError,
    register_exception_handlers,
)
from app.models import (
    ApiKey,
    Generation,
    RefreshToken,
    Subscription,
    StripeEvent,
    TaskQueue,
    UsageDaily,
    User,
    WebhookDLQ,
)
from app.schemas import (
    AdminStatsResponse,
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    CheckoutRequest,
    CheckoutResponse,
    CurrentMonthUsage,
    GenerateRequest,
    GenerateResponse,
    GenerationListItem,
    GenerationListResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SubscriptionResponse,
    TokenResponse,
    UsageHistoryItem,
    UsageResponse,
    UserResponse,
)

# ─── Templates ────────────────────────────────────────────────────────────

templates = Jinja2Templates(directory="app/templates")

# ─── Bearer scheme ────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)

# ─── Plan daily limits ────────────────────────────────────────────────────

PLAN_DAILY_LIMITS: dict[str, int] = {
    "free": 5,
    "solo": 50,
    "pro": 200,
    "team": 1000,
}

# ─── Password helpers ─────────────────────────────────────────────────────


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ─── JWT helpers ──────────────────────────────────────────────────────────


def _create_access_token(user_id: str, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": exp,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _create_refresh_token_str(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.PyJWTError:
        raise InvalidTokenError()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _build_token_response(user: User, db: Session) -> TokenResponse:
    access = _create_access_token(user.id, user.role)
    refresh_raw = _create_refresh_token_str(user.id)
    refresh_hash = _hash_token(refresh_raw)

    exp = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=exp,
    )
    db.add(db_token)
    db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_raw,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ─── Auth dependencies ────────────────────────────────────────────────────

DBSession = Annotated[Session, Depends(get_db)]


def _resolve_user(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
    x_api_key: str | None,
) -> User:
    """Resolve User from JWT bearer token or X-API-Key header."""
    if credentials and credentials.credentials:
        token = credentials.credentials
        claims = _decode_token(token)
        if claims.get("type") != "access":
            raise InvalidTokenError("Token is not an access token.")
        user_id = claims.get("sub")
        if not user_id:
            raise InvalidTokenError()
        user = db.get(User, user_id)
        if user is None:
            raise AuthenticationError("User not found.")
        return user

    if x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        api_key = (
            db.query(ApiKey)
            .filter(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active.is_(True),
            )
            .first()
        )
        if api_key is None:
            raise AuthenticationError("Invalid or revoked API key.")
        if api_key.expires_at:
            key_expires = api_key.expires_at
            if key_expires.tzinfo is None:
                key_expires = key_expires.replace(tzinfo=timezone.utc)
            if key_expires < datetime.now(timezone.utc):
                raise AuthenticationError("API key has expired.")
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()
        user = db.get(User, api_key.user_id)
        if user is None:
            raise AuthenticationError("User not found.")
        return user

    raise AuthenticationError("Authentication required.")


async def get_current_user(
    db: DBSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> User:
    return _resolve_user(db, credentials, x_api_key)


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_active:
        raise PermissionDeniedError("Account is inactive.")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]


def _require_admin(user: Annotated[User, Depends(get_current_active_user)]) -> User:
    if user.role != "admin":
        raise PermissionDeniedError("Admin access required.")
    return user


AdminUser = Annotated[User, Depends(_require_admin)]

# ─── Usage helpers ────────────────────────────────────────────────────────


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _get_used_today(user_id: str, db: Session) -> int:
    today = _today_utc()
    row = (
        db.query(UsageDaily)
        .filter(UsageDaily.user_id == user_id, UsageDaily.date == today)
        .first()
    )
    return row.count if row else 0


def _check_usage_gate(user: User, db: Session) -> None:
    limit = PLAN_DAILY_LIMITS.get(user.plan, 5)
    used = _get_used_today(user.id, db)
    if used >= limit:
        raise UsageLimitExceededError(
            f"Daily limit of {limit} generations reached for the {user.plan!r} plan. "
            "Upgrade your plan or wait until tomorrow."
        )


def _record_usage(user_id: str, tokens: int, db: Session) -> None:
    today = _today_utc()
    row = (
        db.query(UsageDaily)
        .filter(UsageDaily.user_id == user_id, UsageDaily.date == today)
        .first()
    )
    if row:
        row.count += 1
        row.tokens_used += tokens
    else:
        row = UsageDaily(
            user_id=user_id,
            date=today,
            count=1,
            tokens_used=tokens,
        )
        db.add(row)
    db.commit()


# ─── Stripe event handlers ────────────────────────────────────────────────


def _stripe_price_to_plan(price_id: str) -> str:
    mapping = {
        settings.stripe_price_solo: "solo",
        settings.stripe_price_pro: "pro",
        settings.stripe_price_team: "team",
    }
    return mapping.get(price_id, "free")


def _stripe_subscription_upsert(sub_obj: Any, db: Session) -> None:
    customer_id: str = sub_obj.get("customer", "")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if user is None:
        logger.warning(
            f"Stripe subscription event: no user found for customer {customer_id}"
        )
        return

    items_data = sub_obj.get("items", {}).get("data", [])
    price_id = items_data[0]["price"]["id"] if items_data else ""
    plan = _stripe_price_to_plan(price_id)

    stripe_sub_id: str = sub_obj.get("id", "")
    sub_status: str = sub_obj.get("status", "active")
    period_start = sub_obj.get("current_period_start")
    period_end = sub_obj.get("current_period_end")
    cancel_at_end: bool = sub_obj.get("cancel_at_period_end", False)

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db.add(sub)

    sub.stripe_subscription_id = stripe_sub_id
    sub.stripe_price_id = price_id
    sub.plan = plan
    sub.status = sub_status
    sub.cancel_at_period_end = cancel_at_end
    if period_start:
        sub.current_period_start = datetime.fromtimestamp(
            period_start, tz=timezone.utc
        )
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(
            period_end, tz=timezone.utc
        )

    user.plan = plan
    db.commit()
    logger.info(
        f"Subscription upserted: user={user.id} plan={plan} status={sub_status}"
    )


def _stripe_subscription_deleted(sub_obj: Any, db: Session) -> None:
    customer_id: str = sub_obj.get("customer", "")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if user is None:
        return
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        sub.plan = "free"
        sub.status = "canceled"
    user.plan = "free"
    db.commit()
    logger.info(f"Subscription deleted: user={user.id} → downgraded to free")


def _stripe_invoice_payment_failed(invoice_obj: Any, db: Session) -> None:
    customer_id: str = invoice_obj.get("customer", "")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if user is None:
        return
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        sub.status = "past_due"
        db.commit()
    logger.warning(f"Invoice payment failed: user={user.id}")


def _stripe_invoice_payment_succeeded(invoice_obj: Any, db: Session) -> None:
    customer_id: str = invoice_obj.get("customer", "")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if user is None:
        return
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub and sub.status == "past_due":
        sub.status = "active"
        db.commit()
    logger.info(f"Invoice payment succeeded: user={user.id}")


def _handle_stripe_event(event: Any, db: Session) -> None:
    event_type: str = event["type"]
    data_obj = event["data"]["object"]

    dispatch: dict[str, Any] = {
        "customer.subscription.created": _stripe_subscription_upsert,
        "customer.subscription.updated": _stripe_subscription_upsert,
        "customer.subscription.deleted": _stripe_subscription_deleted,
        "invoice.payment_failed": _stripe_invoice_payment_failed,
        "invoice.payment_succeeded": _stripe_invoice_payment_succeeded,
    }
    handler = dispatch.get(event_type)
    if handler:
        handler(data_obj, db)
    else:
        logger.debug(f"Unhandled Stripe event type: {event_type}")


# ─── Logging configuration ────────────────────────────────────────────────


def _configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
        enqueue=True,
    )


# ─── Lifespan ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    _configure_logging()
    logger.info(
        "TestScribe starting: env={env} db={db}",
        env=settings.app_env,
        db=settings.database_url.split("?")[0],
    )

    # Run structured startup checks (JWT strength, API key format, Stripe keys)
    from app.health import run_startup_checks
    run_startup_checks()

    # Belt-and-suspenders: also verify Anthropic API key is non-empty
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    if not anthropic_key:
        logger.critical("ANTHROPIC_API_KEY is not set — AI generation will not work")
        raise RuntimeError("ANTHROPIC_API_KEY is required but not set")
    logger.info("Anthropic API key present (prefix={}...)", anthropic_key[:10])

    init_db()
    app.state.start_time = time.time()
    logger.info("TestScribe ready")

    yield

    # Shutdown
    logger.info("TestScribe shutting down")
    dispose_db()
    logger.info("TestScribe shutdown complete")


# ─── App factory ──────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        description=(
            "AI-powered test case generation from user stories, "
            "requirements, and OpenAPI specs."
        ),
        version="1.0.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    application.state.start_time = time.time()

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    register_exception_handlers(application)

    # Static files (only if the directory exists at runtime)
    static_dir = "app/static"
    if os.path.isdir(static_dir):
        application.mount(
            "/static", StaticFiles(directory=static_dir), name="static"
        )

    _register_routes(application)
    return application


# ─── Route registration ───────────────────────────────────────────────────


def _register_routes(app: FastAPI) -> None:  # noqa: C901

    # ── HTML pages ────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
    async def demo(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("demo.html", {"request": request})

    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
    async def pricing(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("pricing.html", {"request": request})

    @app.get("/docs-page", response_class=HTMLResponse, include_in_schema=False)
    async def docs_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("docs.html", {"request": request})

    # ── Health ────────────────────────────────────────────────────────────

    @app.get("/health", tags=["health"])
    async def health(request: Request, db: DBSession) -> dict[str, Any]:
        db_ok = False
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:
            logger.error(f"Health DB check failed: {exc}")

        uptime = time.time() - getattr(request.app.state, "start_time", time.time())
        return {
            "status": "ok" if db_ok else "degraded",
            "db": "ok" if db_ok else "error",
            "version": "1.0.0",
            "uptime_seconds": int(uptime),
        }

    @app.get("/health/ready", tags=["health"])
    async def health_ready(db: DBSession) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:
            logger.error(f"Readiness probe failed: {exc}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        return {"status": "ready"}

    # ── Auth ──────────────────────────────────────────────────────────────

    @app.post(
        "/auth/register",
        response_model=TokenResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["auth"],
    )
    async def register(payload: RegisterRequest, db: DBSession) -> TokenResponse:
        existing = db.query(User).filter(User.email == str(payload.email)).first()
        if existing:
            raise UserAlreadyExistsError()

        user = User(
            email=str(payload.email),
            hashed_password=_hash_password(payload.password.get_secret_value()),
            full_name=payload.full_name,
            plan="free",
            role="user",
            is_active=True,
            is_verified=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"User registered: {user.email}")
        return _build_token_response(user, db)

    @app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    async def login(payload: LoginRequest, db: DBSession) -> TokenResponse:
        user = db.query(User).filter(User.email == str(payload.email)).first()
        if user is None or not user.hashed_password:
            raise InvalidCredentialsError()
        if not _verify_password(
            payload.password.get_secret_value(), user.hashed_password
        ):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise PermissionDeniedError("Account is inactive.")
        logger.info(f"User logged in: {user.email}")
        return _build_token_response(user, db)

    @app.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
    async def refresh_tokens(payload: RefreshRequest, db: DBSession) -> TokenResponse:
        claims = _decode_token(payload.refresh_token)
        if claims.get("type") != "refresh":
            raise InvalidTokenError("Token is not a refresh token.")

        token_hash = _hash_token(payload.refresh_token)
        db_token = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked.is_(False),
            )
            .first()
        )
        if db_token is None:
            raise InvalidTokenError("Refresh token not found or already revoked.")
        expires_at = db_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise TokenExpiredError()

        # Rotate: revoke consumed token
        db_token.revoked = True
        db.commit()

        user = db.get(User, claims.get("sub"))
        if user is None:
            raise AuthenticationError("User not found.")
        if not user.is_active:
            raise PermissionDeniedError("Account is inactive.")

        return _build_token_response(user, db)

    @app.post(
        "/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["auth"],
    )
    async def logout(payload: RefreshRequest, db: DBSession) -> Response:
        token_hash = _hash_token(payload.refresh_token)
        db_token = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )
        if db_token:
            db_token.revoked = True
            db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/auth/me", response_model=UserResponse, tags=["auth"])
    async def me(current_user: ActiveUser) -> UserResponse:
        return UserResponse.model_validate(current_user)

    # ── API Keys ──────────────────────────────────────────────────────────

    @app.get(
        "/api-keys",
        response_model=list[ApiKeyResponse],
        tags=["api-keys"],
    )
    async def list_api_keys(
        current_user: ActiveUser, db: DBSession
    ) -> list[ApiKeyResponse]:
        keys = (
            db.query(ApiKey)
            .filter(
                ApiKey.user_id == current_user.id,
                ApiKey.is_active.is_(True),
            )
            .order_by(ApiKey.created_at.desc())
            .all()
        )
        return [ApiKeyResponse.model_validate(k) for k in keys]

    @app.post(
        "/api-keys",
        response_model=ApiKeyCreatedResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["api-keys"],
    )
    async def create_api_key(
        payload: ApiKeyCreate,
        current_user: ActiveUser,
        db: DBSession,
    ) -> ApiKeyCreatedResponse:
        raw_key = "tsc_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]

        expires_at: Optional[datetime] = None
        if payload.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=payload.expires_in_days
            )

        api_key = ApiKey(
            user_id=current_user.id,
            name=payload.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            is_active=True,
            expires_at=expires_at,
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)

        return ApiKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            raw_key=raw_key,
            expires_at=api_key.expires_at,
            created_at=api_key.created_at,
            updated_at=api_key.updated_at,
        )

    @app.delete(
        "/api-keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["api-keys"],
    )
    async def revoke_api_key(
        key_id: str,
        current_user: ActiveUser,
        db: DBSession,
    ) -> Response:
        api_key = (
            db.query(ApiKey)
            .filter(
                ApiKey.id == key_id,
                ApiKey.user_id == current_user.id,
            )
            .first()
        )
        if api_key is None:
            raise NotFoundError("API key not found.")
        api_key.is_active = False
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── Generations ───────────────────────────────────────────────────────

    @app.post(
        "/generations",
        tags=["generations"],
    )
    async def create_generation(
        payload: GenerateRequest,
        current_user: ActiveUser,
        db: DBSession,
    ) -> Response:
        from app.ai import get_claude_client, plan_supports_format

        # 1. Usage gate
        _check_usage_gate(current_user, db)

        # 2. Plan format gate: free tier → gherkin only
        if not plan_supports_format(current_user.plan, payload.output_format):
            raise SubscriptionRequiredError(
                f"Output format '{payload.output_format}' requires a paid plan "
                "(Solo, Pro, or Team). Gherkin is available on all plans."
            )

        gen = Generation(
            user_id=current_user.id,
            input_type=payload.input_type,
            input_text=payload.input_text,
            output_format=payload.output_format,
            output_text=None,
            status="pending",
            model=settings.anthropic_model,
            via_api_key=False,
        )
        db.add(gen)
        db.commit()
        db.refresh(gen)

        is_long_input = len(payload.input_text) >= 3000

        if is_long_input:
            # 4. Async path: enqueue task, return 202
            task = TaskQueue(
                task_type="app.tasks.generate_tests",
                payload=json.dumps(
                    {"generation_id": gen.id, "user_id": current_user.id}
                ),
                priority=5,
            )
            db.add(task)
            db.commit()
            logger.info(
                f"Generation {gen.id} queued for background processing "
                f"(input_len={len(payload.input_text)})"
            )
            return Response(
                content=GenerateResponse.model_validate(gen).model_dump_json(),
                status_code=status.HTTP_202_ACCEPTED,
                media_type="application/json",
            )

        # 3. Sync path: call Claude directly
        client = get_claude_client()
        try:
            gen.status = "processing"
            db.commit()

            result = client.generate(
                input_type=payload.input_type,
                input_text=payload.input_text,
                output_format=payload.output_format,
                plan=current_user.plan,
            )

            gen.status = "completed"
            gen.output_text = result.output_text
            gen.prompt_tokens = result.prompt_tokens
            gen.completion_tokens = result.completion_tokens
            gen.total_tokens = result.total_tokens
            gen.latency_ms = result.latency_ms
            gen.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(gen)

            # 5. Record usage
            _record_usage(current_user.id, result.total_tokens, db)

        except AppException:
            gen.status = "failed"
            gen.error_message = "Generation failed."
            gen.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise
        except Exception as exc:
            gen.status = "failed"
            gen.error_message = str(exc)
            gen.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.error(f"Generation {gen.id} failed: {exc}")
            raise GenerationError(str(exc)) from exc

        return Response(
            content=GenerateResponse.model_validate(gen).model_dump_json(),
            status_code=status.HTTP_200_OK,
            media_type="application/json",
        )

    @app.get(
        "/generations/{gen_id}",
        response_model=GenerateResponse,
        tags=["generations"],
    )
    async def get_generation(
        gen_id: str,
        current_user: ActiveUser,
        db: DBSession,
    ) -> GenerateResponse:
        gen = (
            db.query(Generation)
            .filter(
                Generation.id == gen_id,
                Generation.user_id == current_user.id,
            )
            .first()
        )
        if gen is None:
            raise NotFoundError("Generation not found.")
        return GenerateResponse.model_validate(gen)

    @app.get(
        "/generations",
        response_model=GenerationListResponse,
        tags=["generations"],
    )
    async def list_generations(
        current_user: ActiveUser,
        db: DBSession,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> GenerationListResponse:
        offset = (page - 1) * page_size
        total: int = (
            db.query(func.count(Generation.id))
            .filter(Generation.user_id == current_user.id)
            .scalar()
            or 0
        )
        items = (
            db.query(Generation)
            .filter(Generation.user_id == current_user.id)
            .order_by(Generation.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return GenerationListResponse(
            items=[GenerationListItem.model_validate(g) for g in items],
            total=total,
            page=page,
            page_size=page_size,
            has_next=(offset + page_size) < total,
        )

    @app.delete(
        "/generations/{gen_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["generations"],
    )
    async def delete_generation(
        gen_id: str,
        current_user: ActiveUser,
        db: DBSession,
    ) -> Response:
        gen = (
            db.query(Generation)
            .filter(
                Generation.id == gen_id,
                Generation.user_id == current_user.id,
            )
            .first()
        )
        if gen is None:
            raise NotFoundError("Generation not found.")
        db.delete(gen)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── Usage ─────────────────────────────────────────────────────────────

    @app.get("/usage", response_model=UsageResponse, tags=["usage"])
    async def get_usage(current_user: ActiveUser, db: DBSession) -> UsageResponse:
        plan = current_user.plan
        daily_limit = PLAN_DAILY_LIMITS.get(plan, 5)
        used_today = _get_used_today(current_user.id, db)
        remaining_today = max(0, daily_limit - used_today)

        now = datetime.now(timezone.utc)
        month_start = date(now.year, now.month, 1)
        month_rows = (
            db.query(UsageDaily)
            .filter(
                UsageDaily.user_id == current_user.id,
                UsageDaily.date >= month_start,
            )
            .all()
        )
        total_gens = sum(r.count for r in month_rows)
        total_tokens = sum(r.tokens_used for r in month_rows)
        days_active = len(month_rows)

        cutoff = (now - timedelta(days=30)).date()
        history_rows = (
            db.query(UsageDaily)
            .filter(
                UsageDaily.user_id == current_user.id,
                UsageDaily.date >= cutoff,
            )
            .order_by(UsageDaily.date.desc())
            .all()
        )

        return UsageResponse(
            plan=plan,
            daily_limit=daily_limit,
            used_today=used_today,
            remaining_today=remaining_today,
            current_month=CurrentMonthUsage(
                total_generations=total_gens,
                total_tokens=total_tokens,
                days_active=days_active,
            ),
            daily_history=[
                UsageHistoryItem(
                    date=r.date,
                    count=r.count,
                    tokens_used=r.tokens_used,
                )
                for r in history_rows
            ],
        )

    # ── Billing ───────────────────────────────────────────────────────────

    @app.post(
        "/billing/checkout",
        response_model=CheckoutResponse,
        tags=["billing"],
    )
    async def billing_checkout(
        payload: CheckoutRequest,
        current_user: ActiveUser,
        db: DBSession,
    ) -> CheckoutResponse:
        import stripe  # type: ignore[import-untyped]

        stripe.api_key = settings.stripe_secret_key.get_secret_value()

        price_map: dict[str, str] = {
            "solo": settings.stripe_price_solo,
            "pro": settings.stripe_price_pro,
            "team": settings.stripe_price_team,
        }
        price_id = price_map.get(payload.plan)
        if not price_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown plan: {payload.plan}",
            )

        try:
            # Ensure Stripe customer exists
            if not current_user.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=current_user.email,
                    name=current_user.full_name or "",
                    metadata={"user_id": current_user.id},
                )
                current_user.stripe_customer_id = customer.id
                db.commit()

            session = stripe.checkout.Session.create(
                customer=current_user.stripe_customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=payload.success_url,
                cancel_url=payload.cancel_url,
                metadata={"user_id": current_user.id, "plan": payload.plan},
            )
        except stripe.StripeError as exc:
            logger.error(f"Stripe checkout session error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Billing service error. Please try again.",
            )

        return CheckoutResponse(
            session_id=session.id,
            checkout_url=session.url,
        )

    @app.get("/billing/portal", tags=["billing"])
    async def billing_portal(
        current_user: ActiveUser,
        db: DBSession,
    ) -> RedirectResponse:
        import stripe  # type: ignore[import-untyped]

        stripe.api_key = settings.stripe_secret_key.get_secret_value()

        if not current_user.stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No billing account found. Please subscribe first.",
            )

        try:
            session = stripe.billing_portal.Session.create(
                customer=current_user.stripe_customer_id,
                return_url=f"{settings.app_url}/dashboard",
            )
        except stripe.StripeError as exc:
            logger.error(f"Stripe portal session error: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Billing service error. Please try again.",
            )

        return RedirectResponse(url=session.url, status_code=status.HTTP_302_FOUND)

    @app.get(
        "/billing/subscription",
        response_model=SubscriptionResponse,
        tags=["billing"],
    )
    async def get_subscription(
        current_user: ActiveUser, db: DBSession
    ) -> SubscriptionResponse:
        sub = (
            db.query(Subscription)
            .filter(Subscription.user_id == current_user.id)
            .first()
        )
        if sub is None:
            # Create a free subscription record on demand
            sub = Subscription(
                user_id=current_user.id,
                plan="free",
                status="active",
            )
            db.add(sub)
            db.commit()
            db.refresh(sub)
        return SubscriptionResponse.model_validate(sub)

    @app.post("/billing/webhook", tags=["billing"])
    async def billing_webhook(
        request: Request,
        db: DBSession,
        stripe_signature: Annotated[
            str | None, Header(alias="stripe-signature")
        ] = None,
    ) -> dict[str, bool]:
        # IMPORTANT: read raw body BEFORE any parsing
        raw_body = await request.body()

        if not stripe_signature:
            raise WebhookSignatureError("Missing Stripe-Signature header.")

        import stripe  # type: ignore[import-untyped]

        stripe.api_key = settings.stripe_secret_key.get_secret_value()

        try:
            event = stripe.Webhook.construct_event(
                payload=raw_body,
                sig_header=stripe_signature,
                secret=settings.stripe_webhook_secret.get_secret_value(),
            )
        except stripe.SignatureVerificationError as exc:
            logger.warning(f"Stripe webhook signature verification failed: {exc}")
            raise WebhookSignatureError()
        except Exception as exc:
            logger.error(f"Stripe webhook parse error: {exc}")
            raise WebhookSignatureError("Invalid webhook payload.")

        event_id: str = event["id"]
        event_type: str = event["type"]

        # Idempotency: skip already-processed events
        if db.get(StripeEvent, event_id) is not None:
            logger.info(f"Stripe event {event_id} already processed — skipping")
            return {"received": True}

        # Record event for idempotency
        db.add(
            StripeEvent(
                stripe_event_id=event_id,
                event_type=event_type,
                payload=raw_body.decode("utf-8"),
            )
        )
        db.commit()

        # Dispatch to handler; failures go to DLQ
        try:
            _handle_stripe_event(event, db)
        except Exception as exc:
            logger.error(f"Stripe event handler failed for {event_id}: {exc}")
            db.add(
                WebhookDLQ(
                    source="stripe",
                    event_type=event_type,
                    payload=raw_body.decode("utf-8"),
                    error_message=str(exc),
                )
            )
            db.commit()

        return {"received": True}

    # ── Admin ─────────────────────────────────────────────────────────────

    @app.get(
        "/admin/stats",
        response_model=AdminStatsResponse,
        tags=["admin"],
    )
    async def admin_stats(
        _admin: AdminUser,
        db: DBSession,
    ) -> AdminStatsResponse:
        total_users: int = db.query(func.count(User.id)).scalar() or 0

        active_subs: int = (
            db.query(func.count(Subscription.id))
            .filter(
                Subscription.status == "active",
                Subscription.plan != "free",
            )
            .scalar()
            or 0
        )

        today = _today_utc()
        gens_today: int = (
            db.query(func.count(Generation.id))
            .filter(
                func.date(Generation.created_at) == today,
                Generation.status == "completed",
            )
            .scalar()
            or 0
        )

        gens_total: int = (
            db.query(func.count(Generation.id))
            .filter(Generation.status == "completed")
            .scalar()
            or 0
        )

        return AdminStatsResponse(
            total_users=total_users,
            active_subscriptions=active_subs,
            generations_today=gens_today,
            generations_total=gens_total,
            revenue_mtd_cents=0,  # computed from Stripe in production
        )


# ─── Module-level app instance ────────────────────────────────────────────

app: FastAPI = create_app()
