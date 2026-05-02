"""
Custom exception hierarchy and global FastAPI exception handlers.

All application-level exceptions inherit from ``AppException`` so that
the global handler can serialise them uniformly.  HTTP status codes are
declared on the exception class, keeping route code clean.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------


class AppException(Exception):
    """
    Root of the TestScribe exception hierarchy.

    All custom exceptions should subclass this so they are caught by
    the global handler and serialised to a consistent JSON body:
    ``{"code": "...", "message": "...", "details": {...}}``.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            message: Human-readable description (overrides ``default_message``).
            code: Machine-readable error code (overrides ``default_code``).
            details: Optional structured context forwarded to the response body.
        """
        self.message = message if message is not None else self.default_message
        self.code = code if code is not None else self.default_code
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the standard error response dict."""
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


# ---------------------------------------------------------------------------
# Auth exceptions
# ---------------------------------------------------------------------------


class AuthenticationError(AppException):
    """Raised when credentials are missing or invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "AUTHENTICATION_FAILED"
    default_message = "Authentication required."


class InvalidCredentialsError(AuthenticationError):
    """Raised when email/password do not match any account."""

    default_code = "INVALID_CREDENTIALS"
    default_message = "Incorrect email or password."


class TokenExpiredError(AuthenticationError):
    """Raised when a JWT or refresh token has expired."""

    default_code = "TOKEN_EXPIRED"
    default_message = "Your session has expired. Please log in again."


class InvalidTokenError(AuthenticationError):
    """Raised when a JWT cannot be decoded or verified."""

    default_code = "INVALID_TOKEN"
    default_message = "The provided token is invalid."


class ApiKeyInvalidError(AuthenticationError):
    """Raised when an API key is not found, inactive, or expired."""

    default_code = "API_KEY_INVALID"
    default_message = "The API key is invalid or has been revoked."


class PermissionDeniedError(AppException):
    """Raised when the authenticated user lacks the required permission."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "PERMISSION_DENIED"
    default_message = "You do not have permission to perform this action."


# ---------------------------------------------------------------------------
# Resource exceptions
# ---------------------------------------------------------------------------


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    default_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


class ConflictError(AppException):
    """Raised when a resource already exists or a state conflict occurs."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "CONFLICT"
    default_message = "A conflict occurred with the current state of the resource."


class UserAlreadyExistsError(ConflictError):
    """Raised during registration when the email is already taken."""

    default_code = "EMAIL_TAKEN"
    default_message = "An account with this email address already exists."


# ---------------------------------------------------------------------------
# Billing / usage exceptions
# ---------------------------------------------------------------------------


class UsageLimitExceededError(AppException):
    """Raised when a user has exhausted their plan's daily generation quota."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "USAGE_LIMIT_EXCEEDED"
    default_message = "You have reached your daily generation limit."


class SubscriptionRequiredError(AppException):
    """Raised when an action requires an active paid subscription."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "SUBSCRIPTION_REQUIRED"
    default_message = "An active subscription is required to perform this action."


class BillingError(AppException):
    """Raised for unexpected Stripe API errors."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "BILLING_ERROR"
    default_message = "A billing error occurred. Please try again later."


class WebhookSignatureError(AppException):
    """Raised when a Stripe webhook payload signature is invalid."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "WEBHOOK_SIGNATURE_INVALID"
    default_message = "Webhook signature verification failed."


# ---------------------------------------------------------------------------
# AI / generation exceptions
# ---------------------------------------------------------------------------


class GenerationError(AppException):
    """Raised when Claude API call fails for any reason."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "GENERATION_FAILED"
    default_message = "Test generation failed. Please try again."


class CircuitOpenError(GenerationError):
    """Raised when the Claude circuit breaker is in the OPEN state."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "AI_SERVICE_UNAVAILABLE"
    default_message = "The AI service is temporarily unavailable. Please try again shortly."


class GenerationRateLimitError(AppException):
    """Raised when the upstream Anthropic API returns a rate-limit response."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "AI_RATE_LIMIT"
    default_message = "AI request rate limit reached. Please wait before retrying."


class InvalidSourceCodeError(AppException):
    """Raised when the submitted source code fails pre-validation."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "INVALID_SOURCE_CODE"
    default_message = "The submitted source code could not be processed."


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Serialise ``AppException`` and its subclasses to a uniform JSON body.

    Args:
        request: The incoming FastAPI request.
        exc: The raised ``AppException`` instance.

    Returns:
        JSONResponse with the exception's status code and error body.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Convert Pydantic v2 ``RequestValidationError`` to the standard error shape.

    Args:
        request: The incoming FastAPI request.
        exc: The Pydantic validation error.

    Returns:
        422 JSONResponse with a list of field-level error details.
    """
    errors = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []))
        errors.append({"field": loc, "message": error.get("msg", ""), "type": error.get("type", "")})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "errors": errors,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for exceptions that are not ``AppException`` subtypes.

    Logs the full traceback and returns a generic 500 response so that
    internal details are never leaked to the client.

    Args:
        request: The incoming FastAPI request.
        exc: The unhandled exception.

    Returns:
        500 JSONResponse with a generic error body.
    """
    logger.exception(
        "Unhandled exception on {} {}: {}",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Attach all custom exception handlers to the FastAPI application.

    Called once from the app factory in ``app.main``.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
