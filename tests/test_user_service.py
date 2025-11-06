"""Tests for utility functions."""

from datetime import datetime, timezone

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import User
from app.spotify.api import SpotifyClient
from app.spotify.models import Album, Track
from app.user_service import (
    UserNotLoggedInError,
    get_playback_data,
    get_user_spotify_client,
    logout_user,
    refresh_user_spotify_token,
)


@pytest.mark.asyncio
async def test_get_user_spotify_client_exists(
    test_user: User, telegram_user_id: int
) -> None:
    """Test getting Spotify client for existing user."""
    client = await get_user_spotify_client(telegram_user_id)

    assert client is not None
    assert isinstance(client, SpotifyClient)
    assert client._access_token == "test_access_token"
    assert client._refresh_token == "test_refresh_token"


@pytest.mark.asyncio
async def test_get_user_spotify_client_not_exists(test_db: AsyncEngine) -> None:
    """Test getting Spotify client for non-existent user."""
    client = await get_user_spotify_client(99999)
    assert client is None


@pytest.mark.asyncio
async def test_refresh_user_spotify_token(
    test_user: User, test_db: AsyncEngine, telegram_user_id: int, mocker: MockerFixture
) -> None:
    """Test refreshing user Spotify token."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User
    from app.spotify.models import RefreshTokenResponse

    mock_response = RefreshTokenResponse(
        access_token="new_access_token",
        token_type="Bearer",
        scope="user-read-currently-playing",
        expires_in=3600,
    )
    mocker.patch("app.user_service.refresh_token", return_value=mock_response)

    await refresh_user_spotify_token(telegram_user_id)

    # Verify token was updated
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, telegram_user_id)
        assert user is not None
        assert user.spotify_access_token == "new_access_token"
        assert user.spotify_expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_refresh_user_spotify_token_user_not_found(test_db: AsyncEngine) -> None:
    """Test refreshing token for non-existent user."""
    # Should not raise an error, just return
    await refresh_user_spotify_token(99999)


@pytest.mark.asyncio
async def test_refresh_user_spotify_token_invalid_token(
    test_user: User, test_db: AsyncEngine, telegram_user_id: int, mocker: MockerFixture
) -> None:
    """Test that invalid refresh tokens are handled and cleared."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User
    from app.spotify.errors import SpotifyInvalidRefreshTokenError

    # Mock refresh_token to raise invalid token error
    mocker.patch(
        "app.user_service.refresh_token",
        side_effect=SpotifyInvalidRefreshTokenError(),
    )

    # Should raise the exception
    with pytest.raises(SpotifyInvalidRefreshTokenError):
        await refresh_user_spotify_token(telegram_user_id)

    # Verify tokens were cleared
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, telegram_user_id)
        assert user is not None
        assert user.spotify_access_token == ""
        assert user.spotify_refresh_token == ""


@pytest.mark.asyncio
async def test_refresh_user_spotify_token_revoked_token(
    test_user: User, test_db: AsyncEngine, telegram_user_id: int, mocker: MockerFixture
) -> None:
    """Test that revoked refresh tokens are handled and cleared."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User
    from app.spotify.errors import SpotifyTokenRevokedError

    # Mock refresh_token to raise revoked token error
    mocker.patch(
        "app.user_service.refresh_token",
        side_effect=SpotifyTokenRevokedError(),
    )

    # Should raise the exception
    with pytest.raises(SpotifyTokenRevokedError):
        await refresh_user_spotify_token(telegram_user_id)

    # Verify tokens were cleared
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, telegram_user_id)
        assert user is not None
        assert user.spotify_access_token == ""
        assert user.spotify_refresh_token == ""


@pytest.mark.asyncio
async def test_get_playback_data_no_client(
    telegram_user_id: int, mocker: MockerFixture
) -> None:
    """Test get_playback_data when user has no Spotify client."""
    mocker.patch("app.user_service.get_user_spotify_client", return_value=None)

    with pytest.raises(UserNotLoggedInError):
        await get_playback_data(telegram_user_id)


@pytest.mark.asyncio
async def test_get_playback_data_currently_playing(
    telegram_user_id: int, test_track: Track, test_album: Album, mocker: MockerFixture
) -> None:
    """Test get_playback_data with currently playing track."""
    from unittest.mock import AsyncMock

    from app.spotify.models import Context, CurrentlyPlayingResponse

    context = Context(type="album", uri=f"spotify:album:{test_album.id}")

    # Mock client
    mock_client = mocker.MagicMock()
    mock_client.get_currently_playing = AsyncMock(
        return_value=CurrentlyPlayingResponse(
            is_playing=True,
            currently_playing_type="track",
            item=test_track,
            context=context,
        )
    )
    mock_client.get_recently_played = AsyncMock()
    mock_client.get_context_details = AsyncMock(return_value=test_album)
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    result_track, result_context = await get_playback_data(telegram_user_id)

    assert result_track is not None
    assert result_track.name == test_track.name
    assert result_context is not None
    assert result_context.name == test_album.name


@pytest.mark.asyncio
async def test_get_playback_data_recently_played_fallback(
    telegram_user_id: int, test_track: Track, mocker: MockerFixture
) -> None:
    """Test get_playback_data falls back to recently played."""
    from unittest.mock import AsyncMock

    from app.spotify.models import PlayedItem, RecentlyPlayedResponse

    # Mock client - nothing currently playing, but has recently played
    mock_client = mocker.MagicMock()
    mock_client.get_currently_playing = AsyncMock(return_value=None)
    mock_client.get_recently_played = AsyncMock(
        return_value=RecentlyPlayedResponse(
            items=[PlayedItem(track=test_track, context=None)]
        )
    )
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    result_track, result_context = await get_playback_data(telegram_user_id)

    assert result_track is not None
    assert result_track.name == test_track.name
    assert result_context is None


@pytest.mark.asyncio
async def test_get_playback_data_nothing_playing(
    telegram_user_id: int, mocker: MockerFixture
) -> None:
    """Test get_playback_data when nothing is playing."""
    from unittest.mock import AsyncMock

    # Mock client - nothing currently or recently playing
    mock_client = mocker.MagicMock()
    mock_client.get_currently_playing = AsyncMock(return_value=None)
    mock_client.get_recently_played = AsyncMock(return_value=None)
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    result_track, result_context = await get_playback_data(telegram_user_id)

    assert result_track is None
    assert result_context is None


@pytest.mark.asyncio
async def test_logout_user_success(
    test_user: User, test_db: AsyncEngine, telegram_user_id: int
) -> None:
    """Test logging out an existing user."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

    # Verify user exists before logout
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, telegram_user_id)
        assert user is not None

    # Logout user
    result = await logout_user(telegram_user_id)
    assert result is True

    # Verify user was deleted
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, telegram_user_id)
        assert user is None


@pytest.mark.asyncio
async def test_logout_user_not_found(test_db: AsyncEngine) -> None:
    """Test logging out a non-existent user."""
    result = await logout_user(99999)
    assert result is False
