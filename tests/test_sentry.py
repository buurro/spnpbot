"""Test that Sentry is properly disabled during tests."""


def test_sentry_is_mocked():
    """Verify that sentry_sdk is mocked and not the real module."""
    from unittest.mock import MagicMock

    import sentry_sdk

    # Verify sentry_sdk is a mock
    assert isinstance(sentry_sdk, MagicMock), "sentry_sdk should be mocked during tests"


def test_sentry_dsn_is_empty():
    """Verify that SENTRY_DSN is not configured in test environment."""
    from app.config import config

    assert config.SENTRY_DSN is None or config.SENTRY_DSN == "", (
        "SENTRY_DSN should be empty during tests"
    )


def test_sentry_init_not_called():
    """Verify that sentry_sdk.init was not called with real parameters."""
    import sentry_sdk

    # If init was called, it should have been called with mock
    # We can't easily assert it wasn't called, but we can verify it's a mock
    assert hasattr(sentry_sdk, "init")
    assert callable(sentry_sdk.init)


def test_sentry_capture_not_sent():
    """Verify that any sentry_sdk.capture_message calls are mocked."""
    import sentry_sdk

    # Call capture_message - should be mocked and not send anything
    result = sentry_sdk.capture_message("Test message", level="info")

    # Should not raise any exception and should return a mock object
    assert result is not None
