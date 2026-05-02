"""Startup health verification."""
from loguru import logger
from app.config import settings


def verify_startup_config() -> list[str]:
    """
    Verify all required config is present at startup.
    Returns list of error strings; empty list = all good.
    Blocks server start if any Critical items are missing.
    """
    errors = []

    # Check JWT secret strength
    jwt_secret = settings.jwt_secret_key.get_secret_value()
    if len(jwt_secret) < 32:
        errors.append("CRITICAL: JWT_SECRET_KEY must be at least 32 characters")

    # Check Anthropic API key format
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    if not anthropic_key.startswith("sk-ant-"):
        errors.append("WARNING: ANTHROPIC_API_KEY does not look like a valid Anthropic key (should start with sk-ant-)")

    # Check Stripe keys
    stripe_key = settings.stripe_secret_key.get_secret_value()
    if not (stripe_key.startswith("sk_live_") or stripe_key.startswith("sk_test_")):
        errors.append("WARNING: STRIPE_SECRET_KEY does not look like a valid Stripe key")

    if not settings.stripe_price_solo.startswith("price_"):
        errors.append("WARNING: STRIPE_PRICE_SOLO should start with 'price_'")

    return errors


def run_startup_checks() -> None:
    """Run all startup checks. Log warnings; raise on critical errors."""
    errors = verify_startup_config()
    critical = [e for e in errors if e.startswith("CRITICAL")]
    warnings = [e for e in errors if e.startswith("WARNING")]

    for w in warnings:
        logger.warning(f"Startup check: {w}")

    if critical:
        for c in critical:
            logger.critical(f"Startup check FAILED: {c}")
        raise RuntimeError(f"Critical startup checks failed: {'; '.join(critical)}")

    logger.info("All startup checks passed")
