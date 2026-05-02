"""
Custom ASGI middleware components.

Middleware is applied in the order it is added to the app in ``app.main``.
Execution order (outermost first):
    RequestIDMiddleware → SecurityHeadersMiddleware → LoggingMiddleware → route handler
"""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Paths excluded from access-log noise
_SKIP_LOG_PATHS: frozenset[str] = frozenset({"/health", "/health/ready"})


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assign a unique ``X-Request-ID`` header to every request/response pair.

    If the incoming request already carries an ``X-Request-ID`` header it
    is preserved; otherwise a new UUID v4 is generated.  The ID is stored
    on ``request.state.request_id`` so downstream handlers can reference
    it in log statements without re-reading the header.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        """
        Args:
            app: The ASGI application to wrap.
            header_name: HTTP header name to use (default: ``X-Request-ID``).
        """
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Extract or generate a request ID, attach it to state, and echo it
        back on the outgoing response.

        Args:
            request: The incoming HTTP request.
            call_next: Callable that forwards the request down the stack.

        Returns:
            Response with ``X-Request-ID`` header set.
        """
        request_id = request.headers.get(self.header_name) or str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Append security-related HTTP response headers to every response.

    Headers applied:
        - ``X-Content-Type-Options: nosniff``
        - ``X-Frame-Options: DENY``
        - ``X-XSS-Protection: 1; mode=block``
        - ``Referrer-Policy: strict-origin-when-cross-origin``
        - ``Content-Security-Policy`` (configurable, sensible default)
        - ``Strict-Transport-Security`` (only in non-development environments)
        - ``Permissions-Policy``
    """

    _DEFAULT_CSP = "default-src 'none'; frame-ancestors 'none'"

    def __init__(
        self,
        app: ASGIApp,
        csp: str | None = None,
        hsts_max_age: int = 31_536_000,
        environment: str = "development",
    ) -> None:
        """
        Args:
            app: The ASGI application to wrap.
            csp: Override Content-Security-Policy value; uses a safe default when None.
            hsts_max_age: HSTS ``max-age`` in seconds (default: 1 year).
            environment: Current deployment environment; HSTS is skipped in development.
        """
        super().__init__(app)
        self.csp = csp if csp is not None else self._DEFAULT_CSP
        self.hsts_max_age = hsts_max_age
        self.environment = environment

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Forward the request then inject security headers into the response.

        Args:
            request: The incoming HTTP request.
            call_next: Callable that forwards the request down the stack.

        Returns:
            Response enriched with security headers.
        """
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = self.csp
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if self.environment != "development":
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )
        # Strip headers that reveal implementation details
        response.headers.pop("server", None)
        response.headers.pop("x-powered-by", None)
        return response


# ---------------------------------------------------------------------------
# Logging / timing middleware
# ---------------------------------------------------------------------------


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Emit a structured log line for every HTTP request with timing and
    correlation metadata.

    Log fields emitted:
        - ``request_id`` – from ``request.state.request_id``
        - ``method`` – HTTP verb
        - ``path`` – URL path (query string excluded)
        - ``status_code`` – response status
        - ``duration_ms`` – wall-clock time from request arrival to response start
        - ``user_agent`` – ``User-Agent`` header value
        - ``ip`` – client IP (respects ``X-Forwarded-For`` behind a proxy)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Time the request/response cycle and emit a log record on completion.

        Args:
            request: The incoming HTTP request.
            call_next: Callable that forwards the request down the stack.

        Returns:
            The unmodified response from downstream handlers.
        """
        if request.url.path in _SKIP_LOG_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        request_id = getattr(request.state, "request_id", "-")
        logger.info(
            "{method} {path} → {status} ({duration}ms) [{rid}] ip={ip} ua={ua}",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration=duration_ms,
            rid=request_id,
            ip=self._get_client_ip(request),
            ua=request.headers.get("user-agent", "-"),
        )
        return response

    def _get_client_ip(self, request: Request) -> str:
        """
        Resolve the real client IP, honouring ``X-Forwarded-For`` when present.

        Args:
            request: The incoming HTTP request.

        Returns:
            Dotted-decimal IPv4 or hex IPv6 address string.
        """
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first (leftmost) address — the original client
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "-"


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_middleware(app: FastAPI, environment: str = "development") -> None:
    """
    Attach all custom middleware to the FastAPI application.

    Note: Starlette applies middleware in reverse registration order, so
    the first middleware added here will be the outermost layer at runtime.
    This function adds them in outermost-first order.

    Args:
        app: The FastAPI application instance.
        environment: Deployment environment string forwarded to
            ``SecurityHeadersMiddleware``.
    """
    # Registration order = outermost first (Starlette reverses internally).
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, environment=environment)
    app.add_middleware(LoggingMiddleware)
