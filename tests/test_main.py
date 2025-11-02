"""Tests for main.py endpoints."""

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.config import config
from app.db import get_session
from app.encryption import create_state
from app.main import app
from app.models import User
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


@pytest.mark.parametrize(
    ("secret_token", "expected_ok", "should_call_feed"),
    [
        (config.BOT_WEBHOOK_SECRET, True, True),  # Valid secret
        ("wrong_secret", False, False),  # Invalid secret
        (None, False, False),  # Missing secret
    ],
)
def test_telegram_webhook(
    client: TestClient,
    telegram_update_data: dict,
    mocker: MockerFixture,
    secret_token: str | None,
    expected_ok: bool,
    should_call_feed: bool,
) -> None:
    """Test telegram webhook endpoint with various secret token scenarios."""
    # Mock the dispatcher
    mock_feed = mocker.patch("app.routes.dp.feed_update", new_callable=AsyncMock)

    # Build headers
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret_token} if secret_token else {}

    # Call the endpoint
    response = client.post(
        config.BOT_WEBHOOK_PATH,
        json=telegram_update_data,
        headers=headers,
    )

    # Assertions
    assert response.status_code == 200
    assert response.json() == {"ok": expected_ok}

    if should_call_feed:
        mock_feed.assert_awaited_once()
    else:
        mock_feed.assert_not_awaited()


def test_spotify_callback_success(client: TestClient, mocker: MockerFixture) -> None:
    # Create valid state with timestamp
    state = create_state("12345")

    # Mock bot.get_me()
    mock_bot_info = mocker.MagicMock()
    mock_bot_info.username = "testbot"
    mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)

    # Mock bot.send_message()
    mock_send_message = mocker.patch(
        "app.routes.bot.send_message", new_callable=AsyncMock
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

    # Mock database session (async context manager)
    mock_session = mocker.MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.merge = AsyncMock()
    mock_session.commit = AsyncMock()
    mocker.patch("app.routes.get_session", return_value=mock_session)

    # Call the endpoint
    response = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params={"code": "test_code", "state": state},
        follow_redirects=False,
    )

    # Assertions
    assert response.status_code == 307  # Redirect
    assert response.headers["location"] == "https://t.me/testbot"
    mock_session.merge.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    mock_send_message.assert_awaited_once_with(
        chat_id=12345,
        text="✅ Successfully logged in with Spotify!\n\n"
        "Use inline mode to share your currently playing Spotify track! "
        "Just type @testbot (followed by a space) in any chat.",
    )


def test_spotify_callback_duplicate_login(
    client: TestClient, mocker: MockerFixture
) -> None:
    """Test that logging in twice with the same user doesn't cause duplicate key error."""
    # Create valid state with timestamp
    state = create_state("12345")

    # Mock bot.get_me()
    mock_bot_info = mocker.MagicMock()
    mock_bot_info.username = "testbot"
    mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)

    # Mock bot.send_message()
    mock_send_message = mocker.patch(
        "app.routes.bot.send_message", new_callable=AsyncMock
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

    # Mock database session (async context manager)
    mock_session = mocker.MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.merge = AsyncMock()
    mock_session.commit = AsyncMock()
    mocker.patch("app.routes.get_session", return_value=mock_session)

    # Call the endpoint twice to simulate duplicate login
    response1 = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params={"code": "test_code", "state": state},
        follow_redirects=False,
    )

    response2 = client.get(
        config.SPOTIFY_CALLBACK_PATH,
        params={"code": "test_code_2", "state": state},
        follow_redirects=False,
    )

    # Both should succeed
    assert response1.status_code == 307  # Redirect
    assert response1.headers["location"] == "https://t.me/testbot"
    assert response2.status_code == 307  # Redirect
    assert response2.headers["location"] == "https://t.me/testbot"

    # Merge should be called twice (once for each login)
    assert mock_session.merge.await_count == 2
    assert mock_session.commit.await_count == 2
    assert mock_send_message.await_count == 2


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


@pytest.mark.asyncio
async def test_spotify_callback_duplicate_user_integration(test_db: None) -> None:
    """Integration test: verify merge handles duplicate user login without UniqueViolation."""
    telegram_id = 99999

    # Create initial user
    user1 = User(
        telegram_id=telegram_id,
        spotify_access_token="initial_token",
        spotify_refresh_token="initial_refresh",
        spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async with get_session() as session:
        await session.merge(user1)
        await session.commit()

    # Login again with the same telegram_id (simulating duplicate login)
    user2 = User(
        telegram_id=telegram_id,
        spotify_access_token="updated_token",
        spotify_refresh_token="updated_refresh",
        spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    # This should not raise UniqueViolation error
    async with get_session() as session:
        await session.merge(user2)
        await session.commit()

    # Verify the user was updated, not duplicated
    async with get_session() as session:
        user = await session.get(User, telegram_id)
        assert user is not None
        assert user.spotify_access_token == "updated_token"
        assert user.spotify_refresh_token == "updated_refresh"


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
