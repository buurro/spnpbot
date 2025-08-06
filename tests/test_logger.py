import logging


def test_configure_uvicorn_loggers() -> None:
    """Test configure_uvicorn_loggers function."""
    from app.logger import configure_uvicorn_loggers

    # Create a test logger with handlers
    test_logger = logging.getLogger("uvicorn.access")
    test_handler = logging.StreamHandler()
    test_logger.addHandler(test_handler)

    # Verify handler exists
    assert len(test_logger.handlers) > 0

    # Call configure_uvicorn_loggers
    configure_uvicorn_loggers()

    # Verify handlers were replaced with RichHandler
    assert len(test_logger.handlers) > 0
    from rich.logging import RichHandler

    assert any(isinstance(h, RichHandler) for h in test_logger.handlers)


def test_configure_uvicorn_loggers_no_handlers() -> None:
    """Test configure_uvicorn_loggers when logger has no handlers."""
    from app.logger import configure_uvicorn_loggers

    # Create a fresh logger without handlers
    test_logger = logging.getLogger("uvicorn.access.test")
    test_logger.handlers.clear()

    # Should not raise error when no handlers exist
    configure_uvicorn_loggers()

    # Original logger should still work
    assert test_logger is not None
