"""Tests for main.py lifespan and app initialization."""

from unittest.mock import AsyncMock

import pytest

from app.config import config


@pytest.fixture
def mock_bot(mocker):
    """Mock the bot instance."""
    mock = mocker.patch("app.main.bot")
    mock.set_webhook = AsyncMock()
    mock.set_my_commands = AsyncMock()
    mock.delete_webhook = AsyncMock()
    mock.delete_my_commands = AsyncMock()
    return mock


@pytest.fixture
def mock_configure_uvicorn_loggers(mocker):
    """Mock the configure_uvicorn_loggers function."""
    return mocker.patch("app.main.configure_uvicorn_loggers")


@pytest.mark.asyncio
async def test_lifespan_startup_sets_webhook(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan sets webhook on startup."""
    mocker.patch("app.main.config.ENVIRONMENT", "production")

    from app.main import lifespan, app

    async with lifespan(app):
        pass

    mock_bot.set_webhook.assert_awaited_once_with(
        f"{config.APP_URL}{config.BOT_WEBHOOK_PATH}",
        allowed_updates=["message", "inline_query", "callback_query"],
        secret_token=config.BOT_WEBHOOK_SECRET,
    )


@pytest.mark.asyncio
async def test_lifespan_startup_sets_bot_commands(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan sets bot commands on startup."""
    mocker.patch("app.main.config.ENVIRONMENT", "production")

    from app.main import lifespan, app

    async with lifespan(app):
        pass

    mock_bot.set_my_commands.assert_awaited_once()
    call_args = mock_bot.set_my_commands.call_args[0][0]

    # Verify all three commands are registered
    assert len(call_args) == 3

    commands = {cmd.command: cmd.description for cmd in call_args}
    assert commands["start"] == "Start the bot"
    assert commands["help"] == "How to use inline mode and login"
    assert commands["logout"] == "Disconnect your Spotify account"


@pytest.mark.asyncio
async def test_lifespan_startup_configures_uvicorn_loggers(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan configures uvicorn loggers on startup."""
    mocker.patch("app.main.config.ENVIRONMENT", "production")

    from app.main import lifespan, app

    async with lifespan(app):
        pass

    mock_configure_uvicorn_loggers.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_shutdown_cleans_up_in_development(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan cleans up webhook and commands in development mode."""
    mocker.patch("app.main.config.ENVIRONMENT", "development")

    from app.main import lifespan, app

    async with lifespan(app):
        pass

    # In development, should delete commands and webhook on shutdown
    mock_bot.delete_my_commands.assert_awaited_once()
    mock_bot.delete_webhook.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_shutdown_skips_cleanup_in_production(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan does NOT clean up webhook and commands in production."""
    mocker.patch("app.main.config.ENVIRONMENT", "production")

    from app.main import lifespan, app

    async with lifespan(app):
        pass

    # In production, should NOT delete commands and webhook
    mock_bot.delete_my_commands.assert_not_awaited()
    mock_bot.delete_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifespan_cleanup_on_exception(
    mock_bot, mock_configure_uvicorn_loggers, mocker
):
    """Test that lifespan still cleans up if an exception occurs during app runtime."""
    mocker.patch("app.main.config.ENVIRONMENT", "development")

    from app.main import lifespan, app

    with pytest.raises(RuntimeError, match="Test error"):
        async with lifespan(app):
            raise RuntimeError("Test error")

    # Should still clean up even after exception
    mock_bot.delete_my_commands.assert_awaited_once()
    mock_bot.delete_webhook.assert_awaited_once()
