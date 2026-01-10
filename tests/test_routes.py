"""Tests for routes.py endpoints."""

import time
from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.config import config
from app.encryption import create_state
from app.main import app
from app.spotify.auth import SpotifyAuthError
from app.spotify.models import TokenResponse


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def telegram_update_data() -> dict:
    """Create test Telegram update data."""
    return {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "from": {
                "id": 12345,
                "is_bot": False,
                "first_name": "Test",
            },
            "chat": {
                "id": 12345,
                "type": "private",
            },
            "date": 1234567890,
            "text": "/start",
        },
    }


def test_telegram_webhook_valid_token(
    client: TestClient,
    telegram_update_data: dict,
    mocker: MockerFixture,
) -> None:
    """Test telegram webhook with valid secret token."""
    mock_feed = mocker.patch("app.routes.dp.feed_update", new_callable=AsyncMock)

    response = client.post(
        config.BOT_WEBHOOK_PATH,
        json=telegram_update_data,
        headers={"X-Telegram-Bot-Api-Secret-Token": config.BOT_WEBHOOK_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_feed.assert_awaited_once()


def test_telegram_webhook_invalid_token(
    client: TestClient,
    telegram_update_data: dict,
    mocker: MockerFixture,
) -> None:
    """Test telegram webhook with invalid secret token returns 401."""
    mock_feed = mocker.patch("app.routes.dp.feed_update", new_callable=AsyncMock)

    response = client.post(
        config.BOT_WEBHOOK_PATH,
        json=telegram_update_data,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid secret token"}
    mock_feed.assert_not_awaited()


def test_telegram_webhook_missing_token(
    client: TestClient,
    telegram_update_data: dict,
    mocker: MockerFixture,
) -> None:
    """Test telegram webhook with missing secret token returns 422."""
    mock_feed = mocker.patch("app.routes.dp.feed_update", new_callable=AsyncMock)

    response = client.post(
        config.BOT_WEBHOOK_PATH,
        json=telegram_update_data,
        headers={},
    )

    assert response.status_code == 422
    mock_feed.assert_not_awaited()


@pytest.mark.parametrize(
    ("params_override", "mock_setup"),
    [
        ({"error": "access_denied"}, None),  # Error parameter
        ({}, None),  # Missing code (empty override keeps only state)
        (
            {"code": "invalid_code"},
            lambda m: m.patch(
                "app.routes.get_token", side_effect=SpotifyAuthError("Invalid code")
            ),
        ),  # Auth error
    ],
)
def test_spotify_callback_error_scenarios(
    client: TestClient,
    mocker: MockerFixture,
    params_override: dict,
    mock_setup: Callable | None,
) -> None:
    """Test various Spotify callback error scenarios that redirect to Telegram."""
    state = create_state("12345")

    # Mock bot.get_me()
    mock_bot_info = mocker.MagicMock()
    mock_bot_info.username = "testbot"
    mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)

    # Apply additional mocking if needed
    if mock_setup:
        mock_setup(mocker)

    # Build params - always include state, override with specific params
    params = {"state": state}
    params.update(params_override)

    # Call the endpoint
    response = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params=params,
        follow_redirects=False,
    )

    # All error scenarios should redirect to Telegram
    assert response.status_code == 307
    assert response.headers["location"] == "https://t.me/testbot"


@pytest.mark.parametrize(
    "is_expired",
    [True, False],
)
def test_spotify_callback_invalid_state_scenarios(
    client: TestClient, mocker: MockerFixture, is_expired: bool
) -> None:
    """Test callback with expired or invalid state parameter."""
    from app.encryption import STATE_EXPIRATION_SECONDS, encrypt

    # Mock bot.get_me()
    mock_bot_info = mocker.MagicMock()
    mock_bot_info.username = "testbot"
    mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)

    # Generate the state
    if is_expired:
        # Create an expired state
        old_timestamp = int(time.time()) - STATE_EXPIRATION_SECONDS - 100
        state = encrypt(f"12345:{old_timestamp}")
    else:
        # Invalid state
        state = "invalid_state_data"

    # Call the endpoint
    response = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params={"code": "test_code", "state": state},
        follow_redirects=False,
    )

    # Should redirect to Telegram without processing
    assert response.status_code == 307
    assert response.headers["location"] == "https://t.me/testbot"


def test_health_check(client: TestClient) -> None:
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_spotify_callback_send_message_error(
    client: TestClient, mocker: MockerFixture
) -> None:
    """Test that callback succeeds even if sending welcome message fails."""
    # Create valid state with timestamp
    state = create_state("12345")

    # Mock bot.get_me()
    mock_bot_info = mocker.MagicMock()
    mock_bot_info.username = "testbot"
    mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)

    # Mock bot.send_message() to raise exception
    mock_send_message = mocker.patch(
        "app.routes.bot.send_message",
        new_callable=AsyncMock,
        side_effect=Exception("Bot blocked by user"),
    )

    # Mock get_token
    mock_token = TokenResponse(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        token_type="Bearer",
        scope="user-read-currently-playing",
        expires_in=3600,
    )
    mocker.patch("app.routes.get_token", return_value=mock_token)

    # Mock database session
    mock_session = mocker.MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.merge = AsyncMock()
    mock_session.commit = AsyncMock()
    mocker.patch("app.routes.get_session", return_value=mock_session)

    # Call the endpoint - should succeed despite send_message error
    response = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params={"code": "test_code", "state": state},
        follow_redirects=False,
    )

    # Assertions - should still redirect successfully
    assert response.status_code == 307  # Redirect
    assert response.headers["location"] == "https://t.me/testbot"
    mock_session.merge.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    mock_send_message.assert_awaited_once()
