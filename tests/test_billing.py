"""
Billing endpoint integration tests.

Exercises the Stripe billing routes in app/main.py. The Stripe SDK is
mocked via the ``mock_stripe`` fixture so no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ===========================================================================
# Checkout
# ===========================================================================


class TestCheckout:
    def test_checkout_requires_auth(self, client: TestClient) -> None:
        """POST /billing/checkout without authentication returns 401."""
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
        self,
        client: TestClient,
        auth_headers: dict,
        mock_stripe: MagicMock,
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
        assert "session_id" in data

    def test_checkout_creates_stripe_customer_when_none(
        self,
        client: TestClient,
        auth_headers: dict,
        mock_stripe: MagicMock,
        registered_user,
    ) -> None:
        """Checkout creates a Stripe customer when user.stripe_customer_id is None."""
        resp = client.post(
            "/billing/checkout",
            json={
                "plan": "solo",
                "success_url": "https://example.com/ok",
                "cancel_url": "https://example.com/cancel",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Verify that Customer.create was called
        mock_stripe.Customer.create.assert_called_once()

    def test_checkout_invalid_plan_returns_error(
        self,
        client: TestClient,
        auth_headers: dict,
    ) -> None:
        """POST /billing/checkout with an unrecognised plan name returns 400 or 422."""
        resp = client.post(
            "/billing/checkout",
            json={
                "plan": "not_a_real_plan",
                "success_url": "https://example.com/ok",
                "cancel_url": "https://example.com/cancel",
            },
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    def test_checkout_all_valid_plans(
        self,
        client: TestClient,
        auth_headers: dict,
        mock_stripe: MagicMock,
    ) -> None:
        """All three paid plan tiers (solo, pro, team) are accepted by the checkout."""
        for plan in ("solo", "pro", "team"):
            resp = client.post(
                "/billing/checkout",
                json={
                    "plan": plan,
                    "success_url": "https://example.com/ok",
                    "cancel_url": "https://example.com/cancel",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200, f"Plan {plan} returned {resp.status_code}"


# ===========================================================================
# Webhook
# ===========================================================================


class TestWebhook:
    def test_webhook_missing_signature_returns_400(
        self, client: TestClient
    ) -> None:
        """POST /billing/webhook without stripe-signature header returns 400."""
        resp = client.post(
            "/billing/webhook",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_webhook_valid_signature_returns_200(
        self,
        client: TestClient,
        mock_stripe: MagicMock,
    ) -> None:
        """Valid webhook with properly mocked signature returns 200 and received=True."""
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_test_valid",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test",
                    "customer": "cus_nonexistent",
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
            headers={"stripe-signature": "t=12345,v1=fakesig"},
        )
        assert resp.status_code == 200
        assert resp.json()["received"] is True

    def test_webhook_idempotent_duplicate_event(
        self,
        client: TestClient,
        mock_stripe: MagicMock,
    ) -> None:
        """Receiving the same event ID twice is acknowledged both times (idempotent)."""
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_duplicate_test",
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_test", "metadata": {}}},
        }
        headers = {"stripe-signature": "t=1,v1=sig"}
        body = b'{"type":"checkout.session.completed"}'

        r1 = client.post("/billing/webhook", content=body, headers=headers)
        r2 = client.post("/billing/webhook", content=body, headers=headers)

        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_webhook_subscription_deleted_handled(
        self,
        client: TestClient,
        db_session: Session,
        registered_user,
        mock_stripe: MagicMock,
    ) -> None:
        """customer.subscription.deleted event is processed without error."""
        # Give the user a Stripe customer ID so the handler can find them
        registered_user.stripe_customer_id = "cus_test_delete"
        db_session.commit()

        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_sub_deleted",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_xxx",
                    "customer": "cus_test_delete",
                    "status": "canceled",
                    "items": {"data": [{"price": {"id": "price_solo_test"}}]},
                    "current_period_start": 1700000000,
                    "current_period_end": 1702678400,
                    "cancel_at_period_end": True,
                }
            },
        }
        resp = client.post(
            "/billing/webhook",
            content=b'{"type":"customer.subscription.deleted"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 200

        # User should be downgraded to free
        db_session.refresh(registered_user)
        assert registered_user.plan == "free"

    def test_webhook_payment_failed_event(
        self,
        client: TestClient,
        db_session: Session,
        registered_user,
        mock_stripe: MagicMock,
    ) -> None:
        """invoice.payment_failed event is dispatched without raising an unhandled error."""
        registered_user.stripe_customer_id = "cus_payment_failed"
        db_session.commit()

        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_pmt_failed",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_payment_failed",
                    "id": "in_test",
                }
            },
        }
        resp = client.post(
            "/billing/webhook",
            content=b'{"type":"invoice.payment_failed"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 200

    def test_webhook_unknown_event_type_acknowledged(
        self,
        client: TestClient,
        mock_stripe: MagicMock,
    ) -> None:
        """An unknown event type is acknowledged (200) without crashing."""
        mock_stripe.Webhook.construct_event.return_value = {
            "id": "evt_unknown_type",
            "type": "completely.unknown.event",
            "data": {"object": {}},
        }
        resp = client.post(
            "/billing/webhook",
            content=b'{"type":"completely.unknown.event"}',
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp.status_code == 200


# ===========================================================================
# Subscription
# ===========================================================================


class TestSubscription:
    def test_get_subscription_unauthenticated(self, client: TestClient) -> None:
        """GET /billing/subscription without authentication returns 401."""
        resp = client.get("/billing/subscription")
        assert resp.status_code == 401

    def test_get_subscription_returns_plan_info(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """GET /billing/subscription authenticated returns plan and status fields."""
        resp = client.get("/billing/subscription", headers=auth_headers)
        # App auto-creates a free subscription on first access
        assert resp.status_code == 200
        data = resp.json()
        assert "plan" in data
        assert "status" in data
        assert "id" in data

    def test_get_subscription_auto_creates_free(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        registered_user,
    ) -> None:
        """GET /billing/subscription for a user with no subscription auto-creates FREE."""
        from app.models import Subscription

        # Confirm there's no subscription for this user yet
        sub = (
            db_session.query(Subscription)
            .filter(Subscription.user_id == registered_user.id)
            .first()
        )
        assert sub is None

        resp = client.get("/billing/subscription", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"

        # Verify it was persisted
        db_session.expire_all()
        sub = (
            db_session.query(Subscription)
            .filter(Subscription.user_id == registered_user.id)
            .first()
        )
        assert sub is not None
        assert sub.plan == "free"
