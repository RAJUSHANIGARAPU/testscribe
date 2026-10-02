"""
Unit and integration tests for the usage gate layer (app.main internal helpers).

The actual usage logic lives inline in app/main.py as private helpers
(_check_usage_gate, _record_usage, _get_used_today). These tests exercise
that logic indirectly through the UsageDaily model and the /usage endpoint,
plus directly by manipulating UsageDaily rows.

The limits module (app/limits.py) is designed for an async variant of the app
and is not wired into the sync app/main.py. Tests here test the sync layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ===========================================================================
# PLAN_DAILY_LIMITS — values exported from app.main
# ===========================================================================


class TestPlanDailyLimits:
    def test_free_plan_limit_value(self) -> None:
        """PLAN_DAILY_LIMITS['free'] is exactly 5."""
        from app.main import PLAN_DAILY_LIMITS

        assert PLAN_DAILY_LIMITS["free"] == 5

    def test_solo_plan_limit_value(self) -> None:
        """PLAN_DAILY_LIMITS['solo'] is 50."""
        from app.main import PLAN_DAILY_LIMITS

        assert PLAN_DAILY_LIMITS["solo"] == 50

    def test_pro_plan_limit_value(self) -> None:
        """PLAN_DAILY_LIMITS['pro'] is 200."""
        from app.main import PLAN_DAILY_LIMITS

        assert PLAN_DAILY_LIMITS["pro"] == 200

    def test_team_plan_limit_value(self) -> None:
        """PLAN_DAILY_LIMITS['team'] is 1000."""
        from app.main import PLAN_DAILY_LIMITS

        assert PLAN_DAILY_LIMITS["team"] == 1000

    def test_free_limit_smallest(self) -> None:
        """Free plan limit is smaller than all paid plan limits."""
        from app.main import PLAN_DAILY_LIMITS

        free = PLAN_DAILY_LIMITS["free"]
        for plan in ("solo", "pro", "team"):
            assert free < PLAN_DAILY_LIMITS[plan], f"{plan} should exceed free limit"

    def test_all_limits_positive(self) -> None:
        """Every plan in PLAN_DAILY_LIMITS has a positive integer limit."""
        from app.main import PLAN_DAILY_LIMITS

        for plan, limit in PLAN_DAILY_LIMITS.items():
            assert isinstance(limit, int), f"{plan}: limit should be int"
            assert limit > 0, f"{plan}: limit should be positive"


# ===========================================================================
# _get_used_today helper
# ===========================================================================


class TestGetUsedToday:
    def test_returns_zero_with_no_usage_row(
        self, db_session: Session, registered_user
    ) -> None:
        """_get_used_today returns 0 when no UsageDaily row exists for today."""
        from app.main import _get_used_today

        count = _get_used_today(registered_user.id, db_session)
        assert count == 0

    def test_returns_count_from_existing_row(
        self, db_session: Session, registered_user
    ) -> None:
        """_get_used_today returns the stored count from today's UsageDaily row."""
        from app.main import _get_used_today
        from app.models import UsageDaily

        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=3,
            tokens_used=500,
        )
        db_session.add(row)
        db_session.commit()

        count = _get_used_today(registered_user.id, db_session)
        assert count == 3

    def test_ignores_other_user_rows(
        self, db_session: Session, registered_user
    ) -> None:
        """_get_used_today only counts rows belonging to the specified user."""
        import bcrypt

        from app.main import _get_used_today
        from app.models import UsageDaily, User

        # Create another user
        other = User(
            email="other@example.com",
            hashed_password=bcrypt.hashpw(b"Pass1word", bcrypt.gensalt()).decode(),
            plan="free",
            role="user",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=other.id,
            date=today,
            count=7,
            tokens_used=1000,
        )
        db_session.add(row)
        db_session.commit()

        # registered_user should still have 0
        count = _get_used_today(registered_user.id, db_session)
        assert count == 0

    def test_ignores_yesterday_row(
        self, db_session: Session, registered_user
    ) -> None:
        """_get_used_today does not count rows from previous days."""
        from app.main import _get_used_today
        from app.models import UsageDaily

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=yesterday,
            count=10,
            tokens_used=2000,
        )
        db_session.add(row)
        db_session.commit()

        count = _get_used_today(registered_user.id, db_session)
        assert count == 0


# ===========================================================================
# _check_usage_gate helper
# ===========================================================================


class TestCheckUsageGate:
    def test_passes_when_under_limit(
        self, db_session: Session, registered_user
    ) -> None:
        """_check_usage_gate does not raise when used_today < daily_limit."""
        from app.main import _check_usage_gate

        # No usage rows → used_today = 0, limit = 5 for free → should pass
        _check_usage_gate(registered_user, db_session)  # must not raise

    def test_raises_when_at_limit(
        self, db_session: Session, registered_user
    ) -> None:
        """_check_usage_gate raises UsageLimitExceededError when used_today >= limit."""
        from app.exceptions import UsageLimitExceededError
        from app.main import _check_usage_gate, PLAN_DAILY_LIMITS
        from app.models import UsageDaily

        limit = PLAN_DAILY_LIMITS[registered_user.plan]
        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=limit,  # exactly at limit
            tokens_used=1000,
        )
        db_session.add(row)
        db_session.commit()

        with pytest.raises(UsageLimitExceededError):
            _check_usage_gate(registered_user, db_session)

    def test_raises_when_over_limit(
        self, db_session: Session, registered_user
    ) -> None:
        """_check_usage_gate raises when used_today exceeds the plan cap."""
        from app.exceptions import UsageLimitExceededError
        from app.main import _check_usage_gate, PLAN_DAILY_LIMITS
        from app.models import UsageDaily

        limit = PLAN_DAILY_LIMITS[registered_user.plan]
        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=limit + 3,  # over the limit
            tokens_used=5000,
        )
        db_session.add(row)
        db_session.commit()

        with pytest.raises(UsageLimitExceededError):
            _check_usage_gate(registered_user, db_session)

    def test_error_code_is_usage_limit_exceeded(
        self, db_session: Session, registered_user
    ) -> None:
        """The raised exception carries the USAGE_LIMIT_EXCEEDED error code."""
        from app.exceptions import UsageLimitExceededError
        from app.main import _check_usage_gate, PLAN_DAILY_LIMITS
        from app.models import UsageDaily

        limit = PLAN_DAILY_LIMITS[registered_user.plan]
        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=limit,
            tokens_used=100,
        )
        db_session.add(row)
        db_session.commit()

        with pytest.raises(UsageLimitExceededError) as exc_info:
            _check_usage_gate(registered_user, db_session)

        assert exc_info.value.code == "USAGE_LIMIT_EXCEEDED"

    def test_higher_plan_allows_more_generations(
        self, db_session: Session, registered_user
    ) -> None:
        """A user upgraded to 'pro' can make more than 5 generations per day."""
        from app.main import _check_usage_gate
        from app.models import UsageDaily

        registered_user.plan = "pro"
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        # Use 10 generations — would exceed free limit but not pro (200)
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=10,
            tokens_used=2000,
        )
        db_session.add(row)
        db_session.commit()

        _check_usage_gate(registered_user, db_session)  # must not raise


# ===========================================================================
# _record_usage helper
# ===========================================================================


class TestRecordUsage:
    def test_creates_new_daily_row(
        self, db_session: Session, registered_user
    ) -> None:
        """_record_usage inserts a new UsageDaily row on first call today."""
        from app.main import _record_usage
        from app.models import UsageDaily

        _record_usage(registered_user.id, 300, db_session)

        today = datetime.now(timezone.utc).date()
        row = (
            db_session.query(UsageDaily)
            .filter(
                UsageDaily.user_id == registered_user.id,
                UsageDaily.date == today,
            )
            .first()
        )
        assert row is not None
        assert row.count == 1
        assert row.tokens_used == 300

    def test_increments_existing_row(
        self, db_session: Session, registered_user
    ) -> None:
        """_record_usage increments count and tokens on an existing row."""
        from app.main import _record_usage
        from app.models import UsageDaily

        _record_usage(registered_user.id, 100, db_session)
        _record_usage(registered_user.id, 200, db_session)

        today = datetime.now(timezone.utc).date()
        row = (
            db_session.query(UsageDaily)
            .filter(
                UsageDaily.user_id == registered_user.id,
                UsageDaily.date == today,
            )
            .first()
        )
        assert row is not None
        assert row.count == 2
        assert row.tokens_used == 300

    def test_accumulates_tokens_correctly(
        self, db_session: Session, registered_user
    ) -> None:
        """Multiple _record_usage calls accumulate token counts correctly."""
        from app.main import _record_usage
        from app.models import UsageDaily

        for tokens in (50, 75, 125):
            _record_usage(registered_user.id, tokens, db_session)

        today = datetime.now(timezone.utc).date()
        row = (
            db_session.query(UsageDaily)
            .filter(
                UsageDaily.user_id == registered_user.id,
                UsageDaily.date == today,
            )
            .first()
        )
        assert row.count == 3
        assert row.tokens_used == 250

    def test_isolated_per_user(
        self, db_session: Session, registered_user
    ) -> None:
        """_record_usage does not affect UsageDaily rows of other users."""
        import bcrypt

        from app.main import _record_usage
        from app.models import UsageDaily, User

        other = User(
            email="isolated@example.com",
            hashed_password=bcrypt.hashpw(b"Iso1ated", bcrypt.gensalt()).decode(),
            plan="free",
            role="user",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()

        _record_usage(registered_user.id, 500, db_session)

        today = datetime.now(timezone.utc).date()
        other_row = (
            db_session.query(UsageDaily)
            .filter(
                UsageDaily.user_id == other.id,
                UsageDaily.date == today,
            )
            .first()
        )
        assert other_row is None


# ===========================================================================
# Usage endpoint via HTTP
# ===========================================================================


class TestUsageEndpoint:
    def test_usage_response_structure(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """GET /usage returns all required top-level keys."""
        resp = client.get("/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "free"
        assert data["daily_limit"] == 5
        assert "used_today" in data
        assert "remaining_today" in data
        assert "current_month" in data
        assert "daily_history" in data

    def test_usage_remaining_decreases_after_generation(
        self,
        client: TestClient,
        auth_headers: dict,
        registered_user,
        db_session: Session,
        mock_anthropic,
    ) -> None:
        """remaining_today decreases by 1 after a successful generation."""
        before = client.get("/usage", headers=auth_headers).json()["remaining_today"]

        client.post(
            "/generations",
            json={
                "input_type": "user_story",
                "input_text": "As a user I want to log in so that I can access my account.",
                "output_format": "gherkin",
            },
            headers=auth_headers,
        )

        after = client.get("/usage", headers=auth_headers).json()["remaining_today"]
        assert after == before - 1

    def test_usage_current_month_totals_include_generations(
        self,
        client: TestClient,
        auth_headers: dict,
        registered_user,
        db_session: Session,
        mock_anthropic,
    ) -> None:
        """current_month.total_generations increases after generating."""
        before = (
            client.get("/usage", headers=auth_headers)
            .json()["current_month"]["total_generations"]
        )

        client.post(
            "/generations",
            json={
                "input_type": "user_story",
                "input_text": "As a user I want to log in so that I can access my account.",
                "output_format": "gherkin",
            },
            headers=auth_headers,
        )

        after = (
            client.get("/usage", headers=auth_headers)
            .json()["current_month"]["total_generations"]
        )
        assert after == before + 1

    def test_usage_unauthenticated(self, client: TestClient) -> None:
        """GET /usage without authentication returns 401."""
        resp = client.get("/usage")
        assert resp.status_code == 401

    def test_usage_time_travel_resets_daily_count(
        self,
        client: TestClient,
        auth_headers: dict,
        registered_user,
        db_session: Session,
    ) -> None:
        """Mocking today's date to tomorrow shows 0 used_today (different date key)."""
        from app.models import UsageDaily

        # Seed usage for today
        today = datetime.now(timezone.utc).date()
        row = UsageDaily(
            user_id=registered_user.id,
            date=today,
            count=3,
            tokens_used=300,
        )
        db_session.add(row)
        db_session.commit()

        # Mock tomorrow
        tomorrow = today + timedelta(days=1)
        with patch("app.main._today_utc", return_value=tomorrow):
            resp = client.get("/usage", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["used_today"] == 0
