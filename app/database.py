"""SQLAlchemy engine, session factory, Base, and helpers.

Provides both a synchronous session (used by main.py routes) and an
asynchronous session (used by auth.py, billing.py, limits.py, tasks.py,
and dependencies.py).

The async layer wraps the same underlying database URL using the
``aiosqlite`` driver for SQLite or ``asyncpg`` for PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()

_engine = None
_SessionLocal = None

_async_engine = None
_AsyncSessionLocal = None


# ---------------------------------------------------------------------------
# Sync engine (main.py)
# ---------------------------------------------------------------------------


def get_engine():
    """Return the (lazily-created) synchronous SQLAlchemy engine."""
    global _engine
    if _engine is None:
        from app.config import settings

        connect_args: dict = {}
        if settings.is_sqlite:
            connect_args = {"check_same_thread": False}

        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            echo=settings.debug,
        )

        if settings.is_sqlite:

            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):  # noqa: ANN001
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        logger.info("Database engine created: {url}", url=settings.database_url.split("?")[0])
    return _engine


def get_session_factory():
    """Return the (lazily-created) synchronous session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a transactional synchronous SQLAlchemy Session.

    Used by main.py routes directly.  The session is always closed at the end
    of the request regardless of success or failure; callers are responsible
    for commit/rollback.
    """
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Async engine (auth.py / billing.py / limits.py / tasks.py / dependencies.py)
# ---------------------------------------------------------------------------


def _make_async_url(sync_url: str) -> str:
    """
    Convert a synchronous DB URL to its async-driver equivalent.

    - ``sqlite:///...``            → ``sqlite+aiosqlite:///...``
    - ``postgresql://...``         → ``postgresql+asyncpg://...``
    - ``postgresql+psycopg2://...``→ ``postgresql+asyncpg://...``
    """
    if sync_url.startswith("sqlite"):
        return sync_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if sync_url.startswith("postgresql+psycopg2://"):
        return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # Fall through: return unchanged and let SQLAlchemy complain with a clear error.
    return sync_url


def get_async_engine():
    """Return the (lazily-created) async SQLAlchemy engine."""
    global _async_engine
    if _async_engine is None:
        from app.config import settings

        async_url = _make_async_url(settings.database_url)

        connect_args: dict = {}
        if "aiosqlite" in async_url:
            connect_args = {"check_same_thread": False}

        _async_engine = create_async_engine(
            async_url,
            connect_args=connect_args,
            echo=settings.debug,
        )
        logger.info("Async database engine created: {url}", url=async_url.split("?")[0])
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the (lazily-created) async session factory."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a transactional async SQLAlchemy session.

    Used by auth.py, billing.py, limits.py, tasks.py, and dependencies.py.
    """
    factory = get_async_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# DB init / dispose
# ---------------------------------------------------------------------------


def init_db() -> None:
    """
    Emit CREATE TABLE IF NOT EXISTS for all mapped models.

    Call once during application startup.  Imports app.models as a side-
    effect to ensure all model classes are registered with Base.metadata
    before the DDL is emitted.
    """
    from app import models  # noqa: F401 — registers all ORM models with Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")


def dispose_db() -> None:
    """Dispose of the engine connection pool (call on application shutdown)."""
    global _engine, _async_engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        logger.info("Synchronous database connections disposed")
    if _async_engine is not None:
        # Async engine disposal is a coroutine; schedule it fire-and-forget
        # since dispose_db is called from a sync context (lifespan shutdown).
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_async_engine.dispose())
            else:
                loop.run_until_complete(_async_engine.dispose())
        except Exception:
            pass
        _async_engine = None
        logger.info("Async database connections disposed")
