"""Test that Sentry is properly disabled during tests."""


def test_sentry_is_mocked() -> None:
    """Verify that sentry_sdk is mocked and not the real module."""
    from unittest.mock import MagicMock

    import sentry_sdk

    # Verify sentry_sdk is a mock
    assert isinstance(sentry_sdk, MagicMock), "sentry_sdk should be mocked during tests"


def test_sentry_dsn_is_empty() -> None:
    """Verify that SENTRY_DSN is not configured in test environment."""
    from app.config import config

    assert config.SENTRY_DSN is None or config.SENTRY_DSN == "", (
        "SENTRY_DSN should be empty during tests"
    )


def test_sentry_capture_not_sent() -> None:
    """Verify that any sentry_sdk.capture_message calls are mocked."""
    import sentry_sdk

    # Call capture_message - should be mocked and not send anything
    result = sentry_sdk.capture_message("Test message", level="info")

    # Should not raise any exception and should return a mock object
    assert result is not None
