"""
Shared pytest fixtures for TestScribe.

Architecture notes:
    - The app (app/main.py) uses synchronous SQLAlchemy.
    - Models use plain String columns for plan/role (no Python Enum classes).
    - A fresh in-memory SQLite database is created per test so tests are
      completely isolated without needing savepoint juggling.
    - Settings are bootstrapped via os.environ before any app module is imported.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Environment bootstrap — must happen before ANY app import
# ---------------------------------------------------------------------------

_TEST_ENV: dict[str, str] = {
    "JWT_SECRET_KEY": "test-secret-key-for-testing-minimum-32-chars",
    "ANTHROPIC_API_KEY": "sk-ant-test-key-for-unit-tests-only",
    "STRIPE_SECRET_KEY": "sk_test_placeholder_key",
    "STRIPE_PUBLISHABLE_KEY": "pk_test_placeholder_key",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_placeholder",
    "STRIPE_PRICE_SOLO": "price_solo_test",
    "STRIPE_PRICE_PRO": "price_pro_test",
    "STRIPE_PRICE_TEAM": "price_team_test",
    "APP_ENV": "development",
    "LOG_LEVEL": "WARNING",
    "DEBUG": "false",
    "DATABASE_URL": "sqlite:///./testscribe.db",
}

for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

# ---------------------------------------------------------------------------
# Lazy imports after env is set
# ---------------------------------------------------------------------------

from app import database as _db_module  # noqa: E402
from app.database import Base, get_db  # noqa: E402


def _make_engine():
    """
    Create a fresh named in-memory SQLite engine with all tables.

    Uses a unique database name per call with the shared-cache URI syntax
    so that all connections within the same process see the same data.
    The ?cache=shared&mode=memory URI ensures multiple connections share
    one in-process database instance.
    """
    import uuid
    import app.models  # noqa: F401 — registers all ORM classes with Base

    db_name = f"testscribe_{uuid.uuid4().hex}"
    url = f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine


# ---------------------------------------------------------------------------
# Per-test fresh engine + session
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    """
    Create a fresh in-memory SQLite engine with all tables for each test.

    Yields:
        SQLAlchemy Engine connected to a clean in-memory SQLite database.
    """
    engine = _make_engine()

    # Redirect the app's global engine so init_db() in lifespan is a no-op
    _db_module._engine = engine

    yield engine

    engine.dispose()
    _db_module._engine = None
    _db_module._SessionLocal = None


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Yield a database session for the test (for direct model manipulation).

    Also sets the app's session factory to the same factory so that requests
    through the TestClient use sessions from the same in-memory DB.
    The session yielded here is used for test-side fixture setup only.

    Yields:
        SQLAlchemy Session bound to the test engine.
    """
    factory = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    _db_module._SessionLocal = factory
    session = factory()

    yield session

    session.close()
    _db_module._SessionLocal = None


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """
    Return a synchronous TestClient backed by the per-test in-memory DB.

    Each request through the client gets its own short-lived session from
    the same session factory (pointing at the test engine).  This avoids
    SQLAlchemy threading / identity-map conflicts while still keeping all
    data in the single in-memory database.

    ``dispose_db`` is patched out so the lifespan shutdown does not destroy
    the test engine while the test is still running, and the background
    workers are not started.

    Yields:
        TestClient wrapping the fully configured FastAPI app.
    """
    from app.main import create_app

    # db_session's factory is already set on _db_module by db_session fixture.
    # We override get_db to create a new session per request from that factory.
    factory = _db_module._SessionLocal

    def _override_db():
        request_session = factory()
        try:
            yield request_session
        finally:
            request_session.close()

    application = create_app()
    application.dependency_overrides[get_db] = _override_db

    # Prevent the app's lifespan shutdown from disposing our test engine, and
    # keep the background workers off: they use the async engine, which is not
    # pointed at the per-test database. Worker behaviour is tested directly in
    # tests/test_tasks.py.
    with patch("app.main.dispose_db"), \
         patch("app.main.start_all_workers"), \
         patch("app.main.stop_all_workers"):
        with TestClient(application, raise_server_exceptions=False) as test_client:
            yield test_client


# ---------------------------------------------------------------------------
# Mock Anthropic
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic() -> Generator[MagicMock, None, None]:
    """
    Patch ``anthropic.Anthropic`` used inside ``app.ai.ClaudeClient`` so
    that no real API calls are made during tests.

    Also resets the ``ClaudeClient`` singleton so the mocked Anthropic class
    is used when ``get_claude_client()`` is called by the generation route.

    The mock returns a minimal Message-like object with:
        - content[0].text → a valid Gherkin Feature block
        - usage.input_tokens = 150, usage.output_tokens = 80

    Yields:
        MagicMock instance (the already-constructed client mock, not the class).
    """
    import app.ai as ai_module

    # Reset singleton so the route's get_claude_client() creates a fresh one
    ai_module._client_instance = None

    with patch("app.ai.anthropic.Anthropic") as mock_class:
        instance = MagicMock()
        instance.messages.create.return_value = MagicMock(
            content=[
                MagicMock(
                    text=(
                        "Feature: User Login\n\n"
                        "  @smoke @happy-path\n"
                        "  Scenario: Successful login with valid credentials\n"
                        "    Given a registered user with email \"test@example.com\"\n"
                        "    When the user submits valid credentials\n"
                        "    Then the user is redirected to the dashboard"
                    )
                )
            ],
            usage=MagicMock(input_tokens=150, output_tokens=80),
        )
        mock_class.return_value = instance
        yield instance

    # Reset singleton after test so it doesn't leak a mock-backed client
    ai_module._client_instance = None


# ---------------------------------------------------------------------------
# Mock Stripe
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stripe() -> Generator[MagicMock, None, None]:
    """
    Patch the ``stripe`` module imported inside app/main.py route handlers.

    Pre-configured stubs:
        - ``stripe.Customer.create``                  → fake customer
        - ``stripe.checkout.Session.create``          → fake session (url, id)
        - ``stripe.billing_portal.Session.create``    → fake portal
        - ``stripe.Webhook.construct_event``          → passthrough dict
        - ``stripe.StripeError``                      → base Exception
        - ``stripe.SignatureVerificationError``       → base Exception

    Yields:
        MagicMock representing the patched stripe module.
    """
    # Stripe is imported locally inside route handlers with `import stripe`.
    # We patch the module-level `stripe` in sys.modules so all local imports
    # within the request handlers get the mock.
    with patch("stripe.Customer") as mock_customer, \
         patch("stripe.checkout") as mock_checkout, \
         patch("stripe.billing_portal") as mock_portal, \
         patch("stripe.Webhook") as mock_webhook:

        mock = MagicMock()
        mock.Customer = mock_customer
        mock.checkout = mock_checkout
        mock.billing_portal = mock_portal
        mock.Webhook = mock_webhook

        mock_customer.create.return_value = MagicMock(id="cus_test123")
        mock_checkout.Session.create.return_value = MagicMock(
            id="cs_test_session",
            url="https://checkout.stripe.com/test",
        )
        mock_portal.Session.create.return_value = MagicMock(
            url="https://billing.stripe.com/test"
        )
        mock_webhook.construct_event.return_value = {
            "id": "evt_test123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": "test-user-id"},
                    "customer": "cus_test",
                }
            },
        }
        yield mock


# ---------------------------------------------------------------------------
# Registered test user
# ---------------------------------------------------------------------------


@pytest.fixture
def registered_user(db_session: Session):
    """
    Create and persist a standard test user with plan='free'.

    The user has:
        email       = testuser@example.com
        password    = TestPass1
        full_name   = Test User
        plan        = free
        role        = user
        is_active   = True

    Returns:
        Persisted User ORM instance.
    """
    from app.models import User

    hashed = bcrypt.hashpw(b"TestPass1", bcrypt.gensalt()).decode()
    user = User(
        email="testuser@example.com",
        hashed_password=hashed,
        full_name="Test User",
        plan="free",
        role="user",
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers(registered_user) -> dict[str, str]:
    """
    Return ``Authorization: Bearer <token>`` headers for the registered user.

    Generates the JWT directly (without an HTTP call) to avoid any
    session-state side effects from the login handler.

    Returns:
        Dict suitable for use as HTTP headers in TestClient requests.
    """
    from app.main import _create_access_token

    token = _create_access_token(registered_user.id, registered_user.role)
    return {"Authorization": f"Bearer {token}"}
