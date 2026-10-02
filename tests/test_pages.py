"""
Tests for the server-rendered HTML pages and the app lifespan wiring.

Every page used to return HTTP 500: base.html called the Flask-only
``get_flashed_messages()`` and dashboard.html expected server-side context
(user, usage, api_keys, csrf_token) that the route never supplied.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

HTML_PAGES = ["/", "/demo", "/dashboard", "/pricing", "/docs-page"]


@pytest.mark.parametrize("path", HTML_PAGES)
def test_html_page_returns_200(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["content-type"].startswith("text/html")
    assert "<html" in resp.text


def test_dashboard_loads_data_from_the_api(client: TestClient) -> None:
    """The dashboard is a static shell that fetches its data with the stored token."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    for endpoint in ("/auth/me", "/usage", "/generations?", "/api-keys"):
        assert endpoint in resp.text
    # The old form posted to routes that do not exist.
    assert "/settings/api-keys" not in resp.text


def test_lifespan_starts_and_stops_background_workers(db_session) -> None:
    from app.main import create_app

    with patch("app.main.dispose_db"), \
         patch("app.main.start_all_workers") as start, \
         patch("app.main.stop_all_workers") as stop:
        with TestClient(create_app()):
            start.assert_awaited_once()
            stop.assert_not_awaited()
        stop.assert_awaited_once()
