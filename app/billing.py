"""
Stripe billing service.

Handles:
    - Checkout session creation
    - Customer portal session creation
    - Webhook event processing (subscription lifecycle, payments)
    - Idempotent event storage in ``stripe_events``
    - Dead-letter queue (``webhook_dlq``) for unprocessable events

Import chain (no circularity):
    billing → database, models, schemas, exceptions, config
    (never imports from auth, ai, limits, tasks)
"""

from __future__ import annotations

import asyncio
import json as _json
import uuid
from datetime import datetime, timezone
from typing import Any

import stripe
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    BillingError,
    NotFoundError,
    WebhookSignatureError,
)
from app.models import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    StripeEvent,
    User,
    WebhookDLQ,
)
from app.schemas import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionResponse,
    SubscriptionResponse,
    WebhookAcknowledgeResponse,
)

# Initialise stripe at import time; key is fetched lazily so tests can patch it.
stripe.api_key = settings.stripe_secret_key.get_secret_value()


# ---------------------------------------------------------------------------
# Stripe price → plan mapping
# ---------------------------------------------------------------------------


def _build_price_to_plan() -> dict[str, SubscriptionPlan]:
    """Build the Stripe Price ID → SubscriptionPlan reverse mapping."""
    return {
        settings.stripe_price_solo: SubscriptionPlan.STARTER,
        settings.stripe_price_pro: SubscriptionPlan.PRO,
        settings.stripe_price_team: SubscriptionPlan.ENTERPRISE,
    }


def _build_plan_to_price() -> dict[SubscriptionPlan, str]:
    """Build the SubscriptionPlan → Stripe Price ID forward mapping."""
    return {
        SubscriptionPlan.STARTER: settings.stripe_price_solo,
        SubscriptionPlan.PRO: settings.stripe_price_pro,
        SubscriptionPlan.ENTERPRISE: settings.stripe_price_team,
    }


def price_id_to_plan(price_id: str) -> SubscriptionPlan:
    """
    Map a Stripe Price ID to an internal ``SubscriptionPlan`` enum value.

    Args:
        price_id: Stripe Price ID (``price_...``).

    Returns:
        The corresponding ``SubscriptionPlan``.

    Raises:
        BillingError: If the Price ID is not recognised.
    """
    mapping = _build_price_to_plan()
    plan = mapping.get(price_id)
    if plan is None:
        raise BillingError(message=f"Unknown Stripe price ID: {price_id!r}")
    return plan


def plan_to_price_id(plan: SubscriptionPlan) -> str:
    """
    Map an internal ``SubscriptionPlan`` to the corresponding Stripe Price ID.

    Args:
        plan: The plan tier to look up.

    Returns:
        Stripe Price ID string.

    Raises:
        BillingError: If the plan has no associated Price ID (e.g. FREE).
    """
    mapping = _build_plan_to_price()
    price_id = mapping.get(plan)
    if price_id is None:
        raise BillingError(message=f"Plan {plan!r} has no associated Stripe price.")
    return price_id


# ---------------------------------------------------------------------------
# Billing service
# ---------------------------------------------------------------------------


class BillingService:
    """
    Encapsulates all Stripe-related operations.

    Constructed per-request with an injected async database session.
    The Stripe SDK is called synchronously inside ``asyncio.to_thread``
    wrappers (Stripe's Python SDK is sync-only).
    """

    def __init__(self, db: AsyncSession) -> None:
        """
        Args:
            db: The active async database session.
        """
        self.db = db

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    async def create_checkout_session(
        self,
        user: User,
        payload: CheckoutSessionRequest,
    ) -> CheckoutSessionResponse:
        """
        Create a Stripe Checkout Session for upgrading to a paid plan.

        If the user has no Stripe Customer record yet, one is created and
        saved to ``user.stripe_customer_id``.

        Args:
            user: The authenticated user initiating the upgrade.
            payload: Checkout request containing plan, success URL, cancel URL.

        Returns:
            ``CheckoutSessionResponse`` with the session ID and hosted URL.

        Raises:
            BillingError: On any Stripe API error.
        """
        try:
            price_id = plan_to_price_id(payload.plan)
            customer_id = await self._get_or_create_stripe_customer(user)

            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                customer=customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=payload.success_url,
                cancel_url=payload.cancel_url,
                metadata={"user_id": str(user.id)},
            )
        except stripe.StripeError as exc:
            raise BillingError(message=str(exc)) from exc

        return CheckoutSessionResponse(
            session_id=session.id,
            checkout_url=session.url,
        )

    async def _get_or_create_stripe_customer(self, user: User) -> str:
        """
        Return the existing Stripe Customer ID for ``user``, or create one.

        Args:
            user: The user to look up or register in Stripe.

        Returns:
            Stripe Customer ID string (``cus_...``).

        Raises:
            BillingError: If the Stripe API call fails.
        """
        if user.stripe_customer_id:
            return user.stripe_customer_id

        try:
            customer = await asyncio.to_thread(
                stripe.Customer.create,
                email=user.email,
                metadata={"user_id": str(user.id)},
            )
        except stripe.StripeError as exc:
            raise BillingError(message=str(exc)) from exc

        user.stripe_customer_id = customer.id
        await self.db.commit()
        return customer.id

    # ------------------------------------------------------------------
    # Billing portal
    # ------------------------------------------------------------------

    async def create_portal_session(
        self,
        user: User,
        return_url: str,
    ) -> PortalSessionResponse:
        """
        Create a Stripe Customer Portal session for the user to manage
        their subscription, payment method, and invoices.

        Args:
            user: The authenticated user requesting portal access.
            return_url: URL to redirect the user to after they close the portal.

        Returns:
            ``PortalSessionResponse`` with the portal URL.

        Raises:
            BillingError: If the user has no Stripe Customer ID or the API fails.
        """
        if not user.stripe_customer_id:
            raise BillingError(message="No Stripe customer found for this user.")

        try:
            portal = await asyncio.to_thread(
                stripe.billing_portal.Session.create,
                customer=user.stripe_customer_id,
                return_url=return_url,
            )
        except stripe.StripeError as exc:
            raise BillingError(message=str(exc)) from exc

        return PortalSessionResponse(portal_url=portal.url)

    # ------------------------------------------------------------------
    # Subscription queries
    # ------------------------------------------------------------------

    async def get_subscription(self, user: User) -> SubscriptionResponse:
        """
        Return the current subscription state for ``user``.

        Creates a FREE subscription record if none exists.

        Args:
            user: The user whose subscription to retrieve.

        Returns:
            ``SubscriptionResponse`` with current plan and status.
        """
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if subscription is None:
            subscription = Subscription(
                user_id=user.id,
                plan=SubscriptionPlan.FREE,
                status=SubscriptionStatus.ACTIVE,
            )
            self.db.add(subscription)
            await self.db.commit()
            await self.db.refresh(subscription)

        return SubscriptionResponse.model_validate(subscription)

    # ------------------------------------------------------------------
    # Webhook processing
    # ------------------------------------------------------------------

    async def process_webhook(
        self,
        raw_body: bytes,
        stripe_signature: str,
    ) -> WebhookAcknowledgeResponse:
        """
        Verify and dispatch an incoming Stripe webhook event.

        Processing steps:
            1. Verify the ``Stripe-Signature`` header.
            2. Check ``stripe_events`` for idempotency (skip if already seen).
            3. Insert the event ID into ``stripe_events``.
            4. Dispatch to the appropriate handler method.
            5. On handler failure, write to ``webhook_dlq`` and re-raise.

        Args:
            raw_body: Raw request body bytes (must not be parsed before this call).
            stripe_signature: Value of the ``Stripe-Signature`` HTTP header.

        Returns:
            ``WebhookAcknowledgeResponse`` with ``received=True``.

        Raises:
            WebhookSignatureError: If signature verification fails.
        """
        try:
            event = await asyncio.to_thread(
                stripe.Webhook.construct_event,
                raw_body,
                stripe_signature,
                settings.stripe_webhook_secret.get_secret_value(),
            )
        except stripe.SignatureVerificationError as exc:
            raise WebhookSignatureError() from exc
        except Exception as exc:
            raise WebhookSignatureError(message=str(exc)) from exc

        # Idempotency check — skip already-processed events
        if await self._is_duplicate_event(event["id"]):
            logger.info("Duplicate Stripe event {id} — skipping", id=event["id"])
            return WebhookAcknowledgeResponse(received=True)

        # Persist for idempotency before handling (so retries see it)
        await self._record_event(event)

        event_type: str = event["type"]
        handlers = {
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "invoice.payment_succeeded": self._handle_invoice_payment_succeeded,
        }

        handler = handlers.get(event_type)
        if handler is None:
            logger.info("Unhandled Stripe event type: {type}", type=event_type)
            return WebhookAcknowledgeResponse(received=True)

        try:
            await handler(event)
        except Exception as exc:
            logger.exception("Stripe webhook handler failed for event {id}: {err}", id=event["id"], err=exc)
            await self._write_dlq(event, exc)
            raise

        return WebhookAcknowledgeResponse(received=True)

    async def _is_duplicate_event(self, stripe_event_id: str) -> bool:
        """
        Check whether a Stripe event has already been processed.

        Args:
            stripe_event_id: The Stripe event ID (``evt_...``).

        Returns:
            ``True`` if the event is already in ``stripe_events``.
        """
        result = await self.db.execute(
            select(StripeEvent).where(StripeEvent.stripe_event_id == stripe_event_id)
        )
        return result.scalar_one_or_none() is not None

    async def _record_event(self, event: stripe.Event) -> None:
        """
        Persist a ``StripeEvent`` record for idempotency tracking.

        Args:
            event: The verified Stripe event object.
        """
        stripe_event = StripeEvent(
            stripe_event_id=event["id"],
            event_type=event["type"],
            # StripeEvent.payload is a Text column — serialize to JSON string
            payload=_json.dumps(dict(event)),
        )
        self.db.add(stripe_event)
        await self.db.commit()

    async def _write_dlq(
        self,
        event: stripe.Event,
        error: Exception,
    ) -> None:
        """
        Write an unprocessable event to the ``webhook_dlq`` table.

        Args:
            event: The Stripe event that could not be processed.
            error: The exception raised during processing.
        """
        dlq_entry = WebhookDLQ(
            source="stripe",
            event_type=event["type"],
            # WebhookDLQ.payload is a Text column — serialize to JSON string
            payload=_json.dumps(dict(event)),
            error_message=str(error),
            attempt_count=1,
        )
        self.db.add(dlq_entry)
        try:
            await self.db.commit()
        except Exception as exc:
            logger.exception("Failed to write DLQ entry: {}", exc)

    # ------------------------------------------------------------------
    # Subscription lifecycle handlers
    # ------------------------------------------------------------------

    async def _handle_subscription_created(self, event: stripe.Event) -> None:
        """
        Handle ``customer.subscription.created``.

        Creates or upserts the ``Subscription`` record for the affected user.

        Args:
            event: Verified Stripe event with subscription data in ``event.data.object``.
        """
        stripe_sub = event["data"]["object"]
        user = await self._find_user_by_stripe_customer(stripe_sub["customer"])
        if user is None:
            logger.warning("No user found for Stripe customer {cid}", cid=stripe_sub["customer"])
            return
        await self._upsert_subscription(user, stripe_sub)

    async def _handle_subscription_updated(self, event: stripe.Event) -> None:
        """
        Handle ``customer.subscription.updated``.

        Syncs plan, status, and billing-period fields to the local record.

        Args:
            event: Verified Stripe event with updated subscription data.
        """
        stripe_sub = event["data"]["object"]
        user = await self._find_user_by_stripe_customer(stripe_sub["customer"])
        if user is None:
            logger.warning("No user found for Stripe customer {cid}", cid=stripe_sub["customer"])
            return
        await self._upsert_subscription(user, stripe_sub)

    async def _handle_subscription_deleted(self, event: stripe.Event) -> None:
        """
        Handle ``customer.subscription.deleted``.

        Downgrades the user to the FREE plan and marks the subscription
        as canceled.

        Args:
            event: Verified Stripe event with deleted subscription data.
        """
        stripe_sub = event["data"]["object"]
        user = await self._find_user_by_stripe_customer(stripe_sub["customer"])
        if user is None:
            return

        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        if subscription is not None:
            subscription.plan = SubscriptionPlan.FREE
            subscription.status = SubscriptionStatus.CANCELED
            subscription.stripe_subscription_id = None
            subscription.stripe_price_id = None
            subscription.cancel_at_period_end = False
            await self.db.commit()

    async def _handle_invoice_payment_failed(self, event: stripe.Event) -> None:
        """
        Handle ``invoice.payment_failed``.

        Marks the subscription status as ``PAST_DUE``.

        Args:
            event: Verified Stripe event with invoice data.
        """
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        if not customer_id:
            return

        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return

        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        if subscription is not None:
            subscription.status = SubscriptionStatus.PAST_DUE
            await self.db.commit()

    async def _handle_invoice_payment_succeeded(self, event: stripe.Event) -> None:
        """
        Handle ``invoice.payment_succeeded``.

        Ensures subscription status is set back to ``ACTIVE`` after
        a successful payment following a past-due period.

        Args:
            event: Verified Stripe event with invoice data.
        """
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        if not customer_id:
            return

        user = await self._find_user_by_stripe_customer(customer_id)
        if user is None:
            return

        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        if subscription is not None and subscription.status == SubscriptionStatus.PAST_DUE:
            subscription.status = SubscriptionStatus.ACTIVE
            await self.db.commit()

    async def _find_user_by_stripe_customer(self, customer_id: str) -> User | None:
        """
        Look up a ``User`` by their Stripe Customer ID.

        Args:
            customer_id: The Stripe Customer ID (``cus_...``).

        Returns:
            The ``User`` ORM instance, or ``None`` if not found.
        """
        result = await self.db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def _upsert_subscription(
        self,
        user: User,
        stripe_sub: Any,
    ) -> None:
        """
        Insert or update the local ``Subscription`` record from a Stripe subscription object.

        Args:
            user: The subscription owner.
            stripe_sub: The Stripe Subscription object (dict) from the event payload.
        """
        # Determine plan from the first item's price
        items = stripe_sub.get("items", {}).get("data", [])
        price_id: str | None = None
        if items:
            price_id = items[0].get("price", {}).get("id")

        plan = SubscriptionPlan.FREE
        if price_id:
            try:
                plan = price_id_to_plan(price_id)
            except Exception:
                logger.warning("Unknown price ID {pid} — defaulting to FREE", pid=price_id)

        # Map Stripe status to internal status
        stripe_status_str = stripe_sub.get("status", "active")
        status_map = {
            "active": SubscriptionStatus.ACTIVE,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
            "trialing": SubscriptionStatus.TRIALING,
            "incomplete": SubscriptionStatus.INCOMPLETE,
            "unpaid": SubscriptionStatus.UNPAID,
        }
        status = status_map.get(stripe_status_str, SubscriptionStatus.ACTIVE)

        # Period timestamps
        period_start: datetime | None = None
        period_end: datetime | None = None
        raw_start = stripe_sub.get("current_period_start")
        raw_end = stripe_sub.get("current_period_end")
        if raw_start:
            period_start = datetime.fromtimestamp(raw_start, tz=timezone.utc)
        if raw_end:
            period_end = datetime.fromtimestamp(raw_end, tz=timezone.utc)

        cancel_at_period_end: bool = stripe_sub.get("cancel_at_period_end", False)

        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if subscription is None:
            subscription = Subscription(
                user_id=user.id,
                stripe_subscription_id=stripe_sub.get("id"),
                stripe_price_id=price_id,
                plan=plan,
                status=status,
                current_period_start=period_start,
                current_period_end=period_end,
                cancel_at_period_end=cancel_at_period_end,
            )
            self.db.add(subscription)
        else:
            subscription.stripe_subscription_id = stripe_sub.get("id")
            subscription.stripe_price_id = price_id
            subscription.plan = plan
            subscription.status = status
            subscription.current_period_start = period_start
            subscription.current_period_end = period_end
            subscription.cancel_at_period_end = cancel_at_period_end

        await self.db.commit()
