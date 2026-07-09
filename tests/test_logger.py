import logging

import pytest
from rich.logging import RichHandler

from app.logger import configure_uvicorn_loggers, should_use_rich_logs


@pytest.mark.parametrize(
    "use_rich, expected_handler",
    [(True, RichHandler), (False, logging.StreamHandler)],
)
def test_configure_uvicorn_loggers(monkeypatch, use_rich, expected_handler) -> None:
    """Test configure_uvicorn_loggers function."""
    monkeypatch.setattr("app.logger.should_use_rich_logs", lambda: use_rich)

    # Create a test logger with handlers
    test_logger = logging.getLogger("uvicorn.access")
    test_logger.handlers.clear()
    test_handler = logging.StreamHandler()
    test_logger.addHandler(test_handler)

    # Call configure_uvicorn_loggers
    configure_uvicorn_loggers()

    # Verify handlers were replaced with the expected handler type
    assert len(test_logger.handlers) == 1
    assert type(test_logger.handlers[0]) is expected_handler


def test_should_use_rich_logs_is_false_without_tty(monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert should_use_rich_logs() is False
