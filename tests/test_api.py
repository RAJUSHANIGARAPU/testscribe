"""
API endpoint integration tests.

Each test exercises one specific behaviour through the full HTTP
request/response cycle using the synchronous FastAPI TestClient.
External services (Anthropic, Stripe) are mocked via conftest fixtures.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ===========================================================================
# HEALTH TESTS
# ===========================================================================


def test_health_ok(client: TestClient) -> None:
    """GET /health returns HTTP 200 with status='ok' when DB is reachable."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert "version" in data


def test_health_ready(client: TestClient) -> None:
    """GET /health/ready returns HTTP 200 with status='ready' when DB is reachable."""
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


# ===========================================================================
# AUTH — REGISTRATION
# ===========================================================================


def test_register_success(client: TestClient) -> None:
    """POST /auth/register with valid data returns 201 and a JWT token pair."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "StrongPass1",
            "full_name": "New User",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert isinstance(data["expires_in"], int)


def test_register_duplicate_email(client: TestClient, registered_user) -> None:
    """POST /auth/register with an already-registered email returns 409."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "testuser@example.com",
            "password": "AnotherPass1",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "EMAIL_TAKEN"


def test_register_weak_password_no_uppercase(client: TestClient) -> None:
    """POST /auth/register with a password missing an uppercase letter returns 422."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "password": "nouppercase1",
        },
    )
    assert resp.status_code == 422


def test_register_weak_password_no_digit(client: TestClient) -> None:
    """POST /auth/register with a password missing a digit returns 422."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "password": "NoDigitPassword",
        },
    )
    assert resp.status_code == 422


def test_register_weak_password_too_short(client: TestClient) -> None:
    """POST /auth/register with a password shorter than 8 characters returns 422."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "password": "Ab1",
        },
    )
    assert resp.status_code == 422


def test_register_invalid_email(client: TestClient) -> None:
    """POST /auth/register with a malformed email address returns 422."""
    resp = client.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": "StrongPass1",
        },
    )
    assert resp.status_code == 422


# ===========================================================================
# AUTH — LOGIN
# ===========================================================================


def test_login_success(client: TestClient, registered_user) -> None:
    """POST /auth/login with valid credentials returns access_token and refresh_token."""
    resp = client.post(
        "/auth/login",
        json={"email": "testuser@example.com", "password": "TestPass1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient, registered_user) -> None:
    """POST /auth/login with the wrong password returns 401."""
    resp = client.post(
        "/auth/login",
        json={"email": "testuser@example.com", "password": "WrongPass1"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_email(client: TestClient) -> None:
    """POST /auth/login with an unregistered email returns 401."""
    resp = client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "TestPass1"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


# ===========================================================================
# AUTH — REFRESH TOKEN
# ===========================================================================


def test_refresh_invalid_token(client: TestClient) -> None:
    """POST /auth/refresh with a garbage token returns 401."""
    resp = client.post(
        "/auth/refresh",
        json={"refresh_token": "completely.invalid.token"},
    )
    assert resp.status_code == 401


def test_refresh_access_token_as_refresh(client: TestClient, registered_user) -> None:
    """POST /auth/refresh with an access token (wrong type) returns 401."""
    login_resp = client.post(
        "/auth/login",
        json={"email": "testuser@example.com", "password": "TestPass1"},
    )
    access_token = login_resp.json()["access_token"]

    resp = client.post(
        "/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert resp.status_code == 401


# ===========================================================================
# AUTH — /auth/me
# ===========================================================================


def test_get_me_authenticated(client: TestClient, auth_headers: dict) -> None:
    """GET /auth/me with a valid JWT returns 200 and the user's email."""
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "testuser@example.com"
    assert data["plan"] == "free"
    assert data["is_active"] is True


def test_get_me_unauthenticated(client: TestClient) -> None:
    """GET /auth/me without any credentials returns 401."""
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_get_me_bad_token(client: TestClient) -> None:
    """GET /auth/me with a malformed bearer token returns 401."""
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    assert resp.status_code == 401


# ===========================================================================
# API KEYS
# ===========================================================================


def test_create_api_key(client: TestClient, auth_headers: dict) -> None:
    """POST /api-keys authenticated returns 201 with a key starting 'tsc_'."""
    resp = client.post(
        "/api-keys",
        json={"name": "CI pipeline"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "raw_key" in data
    assert data["raw_key"].startswith("tsc_")
    assert data["name"] == "CI pipeline"
    assert "key_prefix" in data
    assert "id" in data


def test_create_api_key_unauthenticated(client: TestClient) -> None:
    """POST /api-keys without auth returns 401."""
    resp = client.post("/api-keys", json={"name": "test"})
    assert resp.status_code == 401


def test_list_api_keys(client: TestClient, auth_headers: dict) -> None:
    """GET /api-keys after creating a key returns a list containing that key."""
    # Create a key first
    client.post("/api-keys", json={"name": "test key"}, headers=auth_headers)

    resp = client.get("/api-keys", headers=auth_headers)
    assert resp.status_code == 200
    keys = resp.json()
    assert isinstance(keys, list)
    assert len(keys) >= 1
    # raw_key should NOT be returned in the list
    assert all("raw_key" not in k for k in keys)
    assert all("key_prefix" in k for k in keys)


def test_delete_api_key(client: TestClient, auth_headers: dict) -> None:
    """DELETE /api-keys/{id} for an owned key returns 204 and the key disappears."""
    create_resp = client.post(
        "/api-keys",
        json={"name": "to-be-deleted"},
        headers=auth_headers,
    )
    key_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/api-keys/{key_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Key should no longer appear in the list
    list_resp = client.get("/api-keys", headers=auth_headers)
    ids = [k["id"] for k in list_resp.json()]
    assert key_id not in ids


def test_api_key_auth(client: TestClient, auth_headers: dict) -> None:
    """X-API-Key header with a valid key authenticates the user on GET /auth/me."""
    create_resp = client.post(
        "/api-keys",
        json={"name": "api-auth-test"},
        headers=auth_headers,
    )
    raw_key = create_resp.json()["raw_key"]

    resp = client.get("/auth/me", headers={"X-API-Key": raw_key})
    assert resp.status_code == 200
    assert resp.json()["email"] == "testuser@example.com"


def test_api_key_invalid(client: TestClient) -> None:
    """X-API-Key with an invalid key returns 401."""
    resp = client.get("/auth/me", headers={"X-API-Key": "tsc_totally_fake_key"})
    assert resp.status_code == 401


def test_delete_nonexistent_api_key(client: TestClient, auth_headers: dict) -> None:
    """DELETE /api-keys/{id} for a non-existent key returns 404."""
    import uuid

    resp = client.delete(f"/api-keys/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# GENERATIONS
# ===========================================================================


def test_generate_gherkin(client: TestClient, auth_headers: dict, mock_anthropic: MagicMock) -> None:
    """POST /generations with user_story + gherkin format returns 200 with Feature: in output."""
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["output_format"] == "gherkin"
    assert data["output_text"] is not None
    assert "Feature:" in data["output_text"]


def test_generate_requires_auth(client: TestClient) -> None:
    """POST /generations without authentication returns 401."""
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in.",
            "output_format": "gherkin",
        },
    )
    assert resp.status_code == 401


def test_generate_tabular_requires_paid_plan(client: TestClient, auth_headers: dict) -> None:
    """POST /generations with tabular format on free plan returns 402."""
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "tabular",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 402
    assert resp.json()["code"] == "SUBSCRIPTION_REQUIRED"


def test_generate_pytest_requires_paid_plan(client: TestClient, auth_headers: dict) -> None:
    """POST /generations with pytest format on free plan returns 402."""
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "pytest",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 402


def test_generate_free_tier_daily_limit(
    client: TestClient,
    registered_user,
    auth_headers: dict,
    db_session: Session,
    mock_anthropic: MagicMock,
) -> None:
    """POST /generations returns 429 once the free user has used their daily quota."""
    from app.models import UsageDaily
    from datetime import date

    # Directly insert a usage_daily row that exhausts the free daily limit (5)
    today = datetime.now(timezone.utc).date()
    row = UsageDaily(
        user_id=registered_user.id,
        date=today,
        count=5,  # free plan daily limit
        tokens_used=1000,
    )
    db_session.add(row)
    db_session.commit()

    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "USAGE_LIMIT_EXCEEDED"


def test_get_generation(
    client: TestClient, auth_headers: dict, mock_anthropic: MagicMock
) -> None:
    """GET /generations/{id} returns the generation record created by the user."""
    # Create one generation first
    create_resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    gen_id = create_resp.json()["id"]

    resp = client.get(f"/generations/{gen_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == gen_id
    assert data["output_format"] == "gherkin"


def test_get_generation_not_found(client: TestClient, auth_headers: dict) -> None:
    """GET /generations/{id} for a non-existent ID returns 404."""
    import uuid

    resp = client.get(f"/generations/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_list_generations(
    client: TestClient, auth_headers: dict, mock_anthropic: MagicMock
) -> None:
    """GET /generations returns a paginated list that grows after two creates."""
    for _ in range(2):
        client.post(
            "/generations",
            json={
                "input_type": "user_story",
                "input_text": "As a user I want to log in so that I can access my account.",
                "output_format": "gherkin",
            },
            headers=auth_headers,
        )

    resp = client.get("/generations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


def test_delete_generation(
    client: TestClient, auth_headers: dict, mock_anthropic: MagicMock
) -> None:
    """DELETE /generations/{id} removes the record and subsequent GET returns 404."""
    create_resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "As a user I want to log in so that I can access my account.",
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    gen_id = create_resp.json()["id"]

    del_resp = client.delete(f"/generations/{gen_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_resp = client.get(f"/generations/{gen_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_generate_input_too_short(client: TestClient, auth_headers: dict) -> None:
    """POST /generations with input_text shorter than 10 characters returns 422."""
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": "short",
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_generate_long_input_returns_202(
    client: TestClient, auth_headers: dict, mock_anthropic: MagicMock
) -> None:
    """POST /generations with input >= 3000 chars returns 202 (queued path)."""
    long_input = "A" * 3001
    resp = client.post(
        "/generations",
        json={
            "input_type": "user_story",
            "input_text": long_input,
            "output_format": "gherkin",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"


# ===========================================================================
# USAGE
# ===========================================================================


def test_usage_endpoint(client: TestClient, auth_headers: dict) -> None:
    """GET /usage returns plan, daily_limit, used_today, remaining_today and current_month."""
    resp = client.get("/usage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "free"
    assert "daily_limit" in data
    assert "used_today" in data
    assert "remaining_today" in data
    assert "current_month" in data
    month = data["current_month"]
    assert "total_generations" in month
    assert "total_tokens" in month
    assert "days_active" in month


def test_usage_unauthenticated(client: TestClient) -> None:
    """GET /usage without auth returns 401."""
    resp = client.get("/usage")
    assert resp.status_code == 401


# ===========================================================================
# BILLING
# ===========================================================================


def test_checkout_requires_auth(client: TestClient) -> None:
    """POST /billing/checkout without auth returns 401."""
    resp = client.post(
        "/billing/checkout",
        json={
            "plan": "solo",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
    )
    assert resp.status_code == 401


def test_checkout_creates_session(
    client: TestClient, auth_headers: dict, mock_stripe: MagicMock
) -> None:
    """POST /billing/checkout authenticated returns a Stripe checkout URL."""
    resp = client.post(
        "/billing/checkout",
        json={
            "plan": "solo",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "checkout_url" in data
    assert "stripe.com" in data["checkout_url"]


def test_checkout_invalid_plan(client: TestClient, auth_headers: dict) -> None:
    """POST /billing/checkout with an unknown plan name returns 400 or 422."""
    resp = client.post(
        "/billing/checkout",
        json={
            "plan": "invalid_plan",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (400, 422)


def test_get_subscription_authenticated(client: TestClient, auth_headers: dict) -> None:
    """GET /billing/subscription authenticated returns subscription plan info."""
    resp = client.get("/billing/subscription", headers=auth_headers)
    # App auto-creates a free subscription on first access
    assert resp.status_code == 200
    data = resp.json()
    assert "plan" in data
    assert "status" in data


def test_get_subscription_unauthenticated(client: TestClient) -> None:
    """GET /billing/subscription without auth returns 401."""
    resp = client.get("/billing/subscription")
    assert resp.status_code == 401


def test_webhook_missing_signature(client: TestClient) -> None:
    """POST /billing/webhook without stripe-signature header returns 400."""
    resp = client.post(
        "/billing/webhook",
        content=b'{"type":"test.event"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_webhook_valid_signature(
    client: TestClient,
    mock_stripe: MagicMock,
) -> None:
    """POST /billing/webhook with a mocked valid signature returns 200 received=true."""
    mock_stripe.Webhook.construct_event.return_value = {
        "id": "evt_webhook_valid",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test",
                "customer": "cus_test_nomatch",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_solo_test"}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702678400,
                "cancel_at_period_end": False,
            }
        },
    }
    resp = client.post(
        "/billing/webhook",
        content=b'{"type":"customer.subscription.updated"}',
        headers={"stripe-signature": "t=12345,v1=fakehmac"},
    )
    assert resp.status_code == 200
    assert resp.json()["received"] is True


def test_webhook_idempotent_duplicate(
    client: TestClient,
    mock_stripe: MagicMock,
) -> None:
    """Sending the same webhook event twice is acknowledged both times (idempotency)."""
    event_body = b'{"type":"checkout.session.completed"}'
    headers = {"stripe-signature": "t=12345,v1=fakehmac2"}

    # Send twice
    r1 = client.post("/billing/webhook", content=event_body, headers=headers)
    r2 = client.post("/billing/webhook", content=event_body, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
