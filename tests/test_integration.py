"""Integration tests for complete user journeys.

These tests verify end-to-end flows with real database interactions
and mocked external services (Telegram API, Spotify API).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import respx
from httpx import Response
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import config
from app.db import get_session
from app.encryption import create_state
from app.models import User
from app.spotify.models import TokenResponse


# =============================================================================
# OAuth Flow Integration Tests
# =============================================================================


class TestOAuthFlowIntegration:
    """Test the complete OAuth login flow from start to finish."""

    @pytest.mark.asyncio
    async def test_complete_oauth_flow(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test complete OAuth flow: /start -> callback -> user in DB -> welcome message.

        This test verifies the entire login journey:
        1. User sends /start command and receives login button
        2. User authorizes on Spotify and is redirected back
        3. User is stored in the database
        4. Welcome message is sent to the user
        """
        telegram_user_id = 12345

        # Step 1: Simulate /start command
        from app import bot as bot_module

        mock_message = mocker.Mock()
        mock_message.from_user = mocker.Mock(id=telegram_user_id)
        mock_message.answer = mocker.AsyncMock()

        # Mock bot.get_me for building login URL
        mock_bot_info = mocker.MagicMock()
        mock_bot_info.username = "testbot"
        mocker.patch.object(bot_module.bot, "get_me", return_value=mock_bot_info)

        await bot_module.start(mock_message)

        # Verify /start sent a message with login button
        mock_message.answer.assert_awaited_once()
        call_kwargs = mock_message.answer.call_args.kwargs
        assert "reply_markup" in call_kwargs
        assert "Spotify" in call_kwargs["reply_markup"].inline_keyboard[0][0].text

        # Step 2: Simulate Spotify OAuth callback
        state = create_state(str(telegram_user_id))

        # Mock Spotify token exchange
        mock_token = TokenResponse(
            access_token="integration_test_access_token",
            refresh_token="integration_test_refresh_token",
            token_type="Bearer",
            scope="user-read-currently-playing",
            expires_in=3600,
        )
        mocker.patch("app.routes.get_token", return_value=mock_token)

        # Mock bot for sending welcome message
        mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)
        mock_send_message = mocker.patch(
            "app.routes.bot.send_message", new_callable=AsyncMock
        )

        # Call the callback endpoint
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.get(
            config.SPOTIFY_CALLBACK_PATH,
            params={"code": "test_auth_code", "state": state},
            follow_redirects=False,
        )

        # Step 3: Verify redirect to Telegram
        assert response.status_code == 307
        assert response.headers["location"] == "https://t.me/testbot"

        # Step 4: Verify user is stored in database
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            assert user is not None
            assert user.telegram_id == telegram_user_id
            # Note: Tokens are decrypted when loaded from DB
            assert user.spotify_access_token == "integration_test_access_token"
            assert user.spotify_refresh_token == "integration_test_refresh_token"

        # Step 5: Verify welcome message was sent
        mock_send_message.assert_awaited_once()
        call_args = mock_send_message.call_args
        assert call_args.kwargs["chat_id"] == telegram_user_id
        assert "Successfully logged in" in call_args.kwargs["text"]

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()

    @pytest.mark.asyncio
    async def test_oauth_flow_updates_existing_user(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test that re-authenticating updates an existing user's tokens."""
        telegram_user_id = 54321

        # Create existing user with old tokens
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            existing_user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="old_access_token",
                spotify_refresh_token="old_refresh_token",
                spotify_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            session.add(existing_user)
            await session.commit()

        # Setup mocks for OAuth callback
        state = create_state(str(telegram_user_id))

        mock_token = TokenResponse(
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            token_type="Bearer",
            scope="user-read-currently-playing",
            expires_in=3600,
        )
        mocker.patch("app.routes.get_token", return_value=mock_token)

        mock_bot_info = mocker.MagicMock()
        mock_bot_info.username = "testbot"
        mocker.patch("app.routes.bot.get_me", return_value=mock_bot_info)
        mocker.patch("app.routes.bot.send_message", new_callable=AsyncMock)

        # Perform OAuth callback
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.get(
            config.SPOTIFY_CALLBACK_PATH,
            params={"code": "new_auth_code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code == 307

        # Verify tokens were updated
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            assert user is not None
            assert user.spotify_access_token == "new_access_token"
            assert user.spotify_refresh_token == "new_refresh_token"
            assert user.spotify_expires_at > datetime.now(timezone.utc)

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()


# =============================================================================
# Inline Query Flow Integration Tests
# =============================================================================


class TestInlineQueryFlowIntegration:
    """Test the complete inline query flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_complete_inline_query_flow(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test complete inline query flow: query -> Spotify API -> results returned.

        This test verifies:
        1. User sends inline query
        2. Bot fetches currently playing track from Spotify
        3. Results are formatted and returned to user
        """
        telegram_user_id = 11111

        # Create user with valid Spotify tokens
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="valid_access_token",
                spotify_refresh_token="valid_refresh_token",
                spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(user)
            await session.commit()

        # Mock Spotify API - currently playing
        spotify_response = {
            "is_playing": True,
            "currently_playing_type": "track",
            "item": {
                "id": "track123",
                "name": "Integration Test Song",
                "external_urls": {"spotify": "https://open.spotify.com/track/track123"},
                "artists": [
                    {
                        "id": "artist123",
                        "name": "Integration Artist",
                        "external_urls": {
                            "spotify": "https://open.spotify.com/artist/artist123"
                        },
                    }
                ],
                "album": {
                    "id": "album123",
                    "name": "Integration Album",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/album/album123"
                    },
                    "artists": [
                        {
                            "id": "artist123",
                            "name": "Integration Artist",
                            "external_urls": {
                                "spotify": "https://open.spotify.com/artist/artist123"
                            },
                        }
                    ],
                    "images": [
                        {
                            "url": "https://i.scdn.co/image/large",
                            "width": 640,
                            "height": 640,
                        },
                        {
                            "url": "https://i.scdn.co/image/medium",
                            "width": 300,
                            "height": 300,
                        },
                        {
                            "url": "https://i.scdn.co/image/small",
                            "width": 64,
                            "height": 64,
                        },
                    ],
                },
            },
            "context": None,
        }
        respx.get("https://api.spotify.com/v1/me/player/currently-playing").mock(
            return_value=Response(200, json=spotify_response)
        )

        # Create mock inline query
        from app import bot as bot_module
        from app.bot import _inline_query_cache

        _inline_query_cache.clear()

        mock_telegram_user = mocker.Mock(id=telegram_user_id)
        mock_inline_query = mocker.Mock(
            id="query123",
            from_user=mock_telegram_user,
            query="",
            offset="",
        )
        mock_inline_query.answer = mocker.AsyncMock()

        # Execute inline query handler
        await bot_module.inline_query(mock_inline_query)

        # Verify results were sent
        mock_inline_query.answer.assert_awaited_once()
        call_args = mock_inline_query.answer.call_args

        results = call_args.kwargs.get("results") or call_args.args[0]
        assert len(results) >= 1

        # Verify the track result
        track_result = results[0]
        assert "Integration Artist" in track_result.title
        assert "Integration Test Song" in track_result.title
        assert track_result.url == "https://open.spotify.com/track/track123"

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()

    @pytest.mark.asyncio
    @respx.mock
    async def test_inline_query_with_context_flow(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test inline query returns both track and album context."""
        telegram_user_id = 22222

        # Create user
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="valid_access_token",
                spotify_refresh_token="valid_refresh_token",
                spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(user)
            await session.commit()

        # Mock Spotify API - currently playing with album context
        spotify_response = {
            "is_playing": True,
            "currently_playing_type": "track",
            "item": {
                "id": "track456",
                "name": "Context Test Song",
                "external_urls": {"spotify": "https://open.spotify.com/track/track456"},
                "artists": [
                    {
                        "id": "artist456",
                        "name": "Context Artist",
                        "external_urls": {
                            "spotify": "https://open.spotify.com/artist/artist456"
                        },
                    }
                ],
                "album": {
                    "id": "album456",
                    "name": "Context Album",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/album/album456"
                    },
                    "artists": [
                        {
                            "id": "artist456",
                            "name": "Context Artist",
                            "external_urls": {
                                "spotify": "https://open.spotify.com/artist/artist456"
                            },
                        }
                    ],
                    "images": [
                        {
                            "url": "https://i.scdn.co/image/large",
                            "width": 640,
                            "height": 640,
                        },
                        {
                            "url": "https://i.scdn.co/image/small",
                            "width": 64,
                            "height": 64,
                        },
                    ],
                },
            },
            "context": {
                "type": "album",
                "uri": "spotify:album:album456",
            },
        }
        respx.get("https://api.spotify.com/v1/me/player/currently-playing").mock(
            return_value=Response(200, json=spotify_response)
        )

        # Mock album details endpoint
        album_response = {
            "id": "album456",
            "name": "Context Album",
            "external_urls": {"spotify": "https://open.spotify.com/album/album456"},
            "artists": [
                {
                    "id": "artist456",
                    "name": "Context Artist",
                    "external_urls": {
                        "spotify": "https://open.spotify.com/artist/artist456"
                    },
                }
            ],
            "images": [
                {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640},
                {"url": "https://i.scdn.co/image/small", "width": 64, "height": 64},
            ],
        }
        respx.get("https://api.spotify.com/v1/albums/album456").mock(
            return_value=Response(200, json=album_response)
        )

        # Create and execute inline query
        from app import bot as bot_module
        from app.bot import _inline_query_cache

        _inline_query_cache.clear()

        mock_telegram_user = mocker.Mock(id=telegram_user_id)
        mock_inline_query = mocker.Mock(
            id="query456",
            from_user=mock_telegram_user,
            query="",
            offset="",
        )
        mock_inline_query.answer = mocker.AsyncMock()

        await bot_module.inline_query(mock_inline_query)

        # Verify results include both track and album
        mock_inline_query.answer.assert_awaited_once()
        call_args = mock_inline_query.answer.call_args
        results = call_args.kwargs.get("results") or call_args.args[0]

        assert len(results) == 2  # Track + Album context

        # First result should be the track
        assert "Context Test Song" in results[0].title

        # Second result should be the album
        assert "Context Album" in results[1].title

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()


# =============================================================================
# Queue Flow Integration Tests
# =============================================================================


class TestQueueFlowIntegration:
    """Test the complete add-to-queue flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_complete_queue_flow(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test complete queue flow: button click -> Spotify API -> confirmation.

        This test verifies:
        1. User clicks "Add to queue" button
        2. Bot calls Spotify API to add track to queue
        3. Success confirmation is shown to user
        """
        telegram_user_id = 33333
        track_id = "trackToQueue123"

        # Create user with valid Spotify tokens
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="queue_test_token",
                spotify_refresh_token="queue_test_refresh",
                spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(user)
            await session.commit()

        # Mock Spotify API - add to queue endpoint
        respx.post(
            "https://api.spotify.com/v1/me/player/queue",
            params={"uri": f"spotify:track:{track_id}"},
        ).mock(return_value=Response(204))

        # Create mock callback query
        from app import bot as bot_module

        mock_telegram_user = mocker.Mock(id=telegram_user_id)
        mock_callback_query = mocker.Mock()
        mock_callback_query.from_user = mock_telegram_user
        mock_callback_query.data = f"queue;{track_id}"
        mock_callback_query.answer = mocker.AsyncMock()

        # Execute callback handler
        await bot_module.queue_callback(mock_callback_query)

        # Verify success message was sent
        mock_callback_query.answer.assert_awaited_once()
        call_args = mock_callback_query.answer.call_args
        response_text = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        )
        assert "queue" in response_text.lower()

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()

    @pytest.mark.asyncio
    @respx.mock
    async def test_queue_flow_no_active_device(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test queue flow when user has no active Spotify device."""
        telegram_user_id = 44444
        track_id = "trackNoDevice"

        # Create user
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="no_device_token",
                spotify_refresh_token="no_device_refresh",
                spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(user)
            await session.commit()

        # Mock Spotify API - no active device error
        respx.post(
            "https://api.spotify.com/v1/me/player/queue",
            params={"uri": f"spotify:track:{track_id}"},
        ).mock(
            return_value=Response(
                404,
                json={"error": {"message": "No active device found", "status": 404}},
            )
        )

        # Create mock callback query
        from app import bot as bot_module

        mock_telegram_user = mocker.Mock(id=telegram_user_id)
        mock_callback_query = mocker.Mock()
        mock_callback_query.from_user = mock_telegram_user
        mock_callback_query.data = f"queue;{track_id}"
        mock_callback_query.answer = mocker.AsyncMock()

        # Execute callback handler
        await bot_module.queue_callback(mock_callback_query)

        # Verify error message mentions no active device
        mock_callback_query.answer.assert_awaited_once()
        call_args = mock_callback_query.answer.call_args
        response_text = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        )
        assert "No active device" in response_text

        # Cleanup
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            if user:
                await session.delete(user)
                await session.commit()

    @pytest.mark.asyncio
    async def test_queue_flow_user_not_logged_in(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test queue flow when user is not logged in."""
        telegram_user_id = 55555  # User not in database
        track_id = "trackNotLoggedIn"

        # Create mock callback query
        from app import bot as bot_module

        mock_telegram_user = mocker.Mock(id=telegram_user_id)
        mock_callback_query = mocker.Mock()
        mock_callback_query.from_user = mock_telegram_user
        mock_callback_query.data = f"queue;{track_id}"
        mock_callback_query.answer = mocker.AsyncMock()

        # Execute callback handler
        await bot_module.queue_callback(mock_callback_query)

        # Verify message asks user to log in
        mock_callback_query.answer.assert_awaited_once()
        call_args = mock_callback_query.answer.call_args
        response_text = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        )
        assert "log in" in response_text.lower() or "login" in response_text.lower()


# =============================================================================
# Logout Flow Integration Tests
# =============================================================================


class TestLogoutFlowIntegration:
    """Test the complete logout flow."""

    @pytest.mark.asyncio
    async def test_complete_logout_flow(
        self,
        test_db: AsyncEngine,
        mocker: MockerFixture,
    ) -> None:
        """Test complete logout flow: command -> user deleted -> confirmation."""
        telegram_user_id = 66666

        # Create user
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            user = User(
                telegram_id=telegram_user_id,
                spotify_access_token="logout_test_token",
                spotify_refresh_token="logout_test_refresh",
                spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(user)
            await session.commit()

        # Verify user exists
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            assert user is not None

        # Create mock message for /logout command
        from app import bot as bot_module

        mock_message = mocker.Mock()
        mock_message.from_user = mocker.Mock(id=telegram_user_id)
        mock_message.answer = mocker.AsyncMock()

        # Execute logout handler
        await bot_module.logout(mock_message)

        # Verify confirmation message
        mock_message.answer.assert_awaited_once()
        call_args = mock_message.answer.call_args
        response_text = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
        )
        assert (
            "logged out" in response_text.lower()
            or "disconnected" in response_text.lower()
        )

        # Verify user was deleted from database
        async with get_session() as session:
            user = await session.get(User, telegram_user_id)
            assert user is None
