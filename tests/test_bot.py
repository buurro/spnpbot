import pytest
from pytest_mock import MockerFixture, MockType

from app import bot
from app.spotify.models import Album, Track
from app.user_service import UserNotLoggedInError


@pytest.fixture
def mock_playback_data(mocker: MockerFixture, test_track: Track):
    """Mock the playback data function to return test track."""

    async def mock_get_playback_data(user_id: int) -> tuple[Track | None, None]:
        return test_track, None

    mocker.patch("app.bot.get_playback_data", side_effect=mock_get_playback_data)
    return test_track


@pytest.mark.asyncio
async def test_inline_query(
    mock_inline_query: MockType, mock_playback_data: Track
) -> None:
    """Test inline query with currently playing track."""
    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()
    results = mock_inline_query.answer.call_args.kwargs["results"]
    assert len(results) > 0
    assert results[0].url == mock_playback_data.url


@pytest.mark.asyncio
async def test_inline_query_not_logged_in(
    mock_inline_query: MockType, mocker: MockerFixture
) -> None:
    """Test inline query when user is not logged in."""

    async def mock_raise_error(user_id: int) -> tuple[None, None]:
        raise UserNotLoggedInError()

    mocker.patch("app.bot.get_playback_data", side_effect=mock_raise_error)

    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()
    call_kwargs = mock_inline_query.answer.call_args.kwargs
    assert call_kwargs["results"] == []
    assert call_kwargs["button"] is not None
    assert call_kwargs["button"].text == "Login with Spotify"
    assert call_kwargs["button"].start_parameter == "login"
    assert call_kwargs["cache_time"] == 0


@pytest.mark.asyncio
async def test_start(mock_message: MockType) -> None:
    """Test /start command shows login button."""
    await bot.start(mock_message)

    mock_message.answer.assert_awaited_once()
    call_args = mock_message.answer.call_args
    assert "Welcome!" in call_args.args[0]
    assert "Spotify account" in call_args.args[0]
    assert call_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_inline_query_token_expired(
    mock_inline_query: MockType,
    mocker: MockerFixture,
    test_track: Track,
    telegram_user_id: int,
) -> None:
    """Test inline query when token is expired and needs refresh.

    The with_token_refresh decorator automatically handles token refresh,
    so we test that the decorator works correctly by verifying refresh is called.
    """
    # Mock the underlying Spotify client to raise SpotifyTokenExpiredError first
    call_count = 0

    async def mock_get_currently_playing():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            from app.spotify.errors import SpotifyTokenExpiredError

            raise SpotifyTokenExpiredError()
        # Return successful response on retry
        from app.spotify.models import CurrentlyPlayingResponse

        return CurrentlyPlayingResponse(
            is_playing=True,
            currently_playing_type="track",
            item=test_track,
            context=None,
        )

    mocker.patch(
        "app.user_service.get_user_spotify_client"
    ).return_value.get_currently_playing = mock_get_currently_playing
    mock_refresh = mocker.patch("app.user_service.refresh_user_spotify_token")

    await bot.inline_query(mock_inline_query)

    assert call_count == 2  # Called twice: first fails, second succeeds after refresh
    mock_refresh.assert_called_once_with(telegram_user_id)
    mock_inline_query.answer.assert_awaited_once()
    results = mock_inline_query.answer.call_args.kwargs["results"]
    assert len(results) > 0


@pytest.mark.asyncio
async def test_inline_query_no_track_found(
    mock_inline_query: MockType, mocker: MockerFixture
) -> None:
    """Test inline query when no track is playing or recently played."""

    async def mock_no_track(user_id: int) -> tuple[None, None]:
        return None, None

    mocker.patch("app.bot.get_playback_data", side_effect=mock_no_track)

    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()
    call_kwargs = mock_inline_query.answer.call_args.kwargs
    assert call_kwargs["results"] == []
    assert call_kwargs["cache_time"] == 0


@pytest.mark.asyncio
async def test_inline_query_with_album_context(
    mock_inline_query: MockType,
    mocker: MockerFixture,
    test_track: Track,
    test_album: Album,
) -> None:
    """Test inline query with album context."""

    async def mock_with_context(user_id: int) -> tuple[Track, Album]:
        return test_track, test_album

    mocker.patch("app.bot.get_playback_data", side_effect=mock_with_context)

    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()
    results = mock_inline_query.answer.call_args.kwargs["results"]
    assert len(results) == 2  # Track + Album context
    assert test_track.artist.name in results[0].title
    assert test_track.name in results[0].title
    assert test_album.artist.name in results[1].title
    assert test_album.name in results[1].title


@pytest.mark.asyncio
async def test_queue_callback(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test successful queue callback."""
    from unittest.mock import AsyncMock

    mock_callback_query.data = "queue;track123"

    # Mock spotify client
    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(return_value=True)
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_client.add_to_queue.assert_called_once_with("track123")
    mock_callback_query.answer.assert_awaited_once_with("Added to your queue!")


@pytest.mark.asyncio
async def test_queue_callback_not_logged_in(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback when user is not logged in."""
    mock_callback_query.data = "queue;track123"

    # Mock no spotify client
    mocker.patch("app.user_service.get_user_spotify_client", return_value=None)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "Please log in with Spotify first!", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_no_active_device(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback when no active device found."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyApiError

    mock_callback_query.data = "queue;track123"

    # Mock spotify client that raises API error
    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(
        side_effect=SpotifyApiError("No active device found", 404)
    )
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "No active device found", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_premium_required(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback when Spotify Premium is required."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyApiError

    mock_callback_query.data = "queue;track123"

    # Mock spotify client that raises API error
    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(
        side_effect=SpotifyApiError("Player command failed: Premium required", 403)
    )
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "This requires Spotify Premium", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_token_expired(
    mock_callback_query: MockType, mocker: MockerFixture, telegram_user_id: int
) -> None:
    """Test queue callback when token is expired and needs refresh.

    The with_token_refresh decorator automatically handles token refresh.
    """

    from app.spotify.errors import SpotifyTokenExpiredError

    mock_callback_query.data = "queue;track123"

    # Mock spotify client that raises token expired error first, then succeeds
    call_count = 0

    async def mock_add_to_queue(track_id: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SpotifyTokenExpiredError()
        return True

    mock_client = mocker.Mock()
    mock_client.add_to_queue = mock_add_to_queue
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)
    mock_refresh = mocker.patch("app.user_service.refresh_user_spotify_token")

    await bot.queue_callback(mock_callback_query)

    assert call_count == 2  # Called twice: first fails, second succeeds
    mock_refresh.assert_called_once_with(telegram_user_id)
    mock_callback_query.answer.assert_awaited_once_with("Added to your queue!")


@pytest.mark.asyncio
async def test_help(mock_message: MockType, mocker: MockerFixture) -> None:
    """Test /help command shows inline mode instructions."""
    # Mock bot.get_me()
    from aiogram.types import User as TelegramUser

    mock_user = mocker.Mock(spec=TelegramUser)
    mock_user.username = "test_bot"
    mocker.patch.object(bot.bot, "get_me", return_value=mock_user)

    await bot.help(mock_message)

    mock_message.answer.assert_awaited_once()
    call_args = mock_message.answer.call_args
    assert call_args is not None
    assert "How to use test_bot" in call_args.args[0]


@pytest.mark.asyncio
async def test_logout_success(mock_message: MockType, mocker: MockerFixture) -> None:
    """Test /logout command when user is logged in."""
    mock_logout = mocker.patch("app.bot.logout_user", return_value=True)

    await bot.logout(mock_message)

    mock_logout.assert_called_once_with(mock_message.from_user.id)
    mock_message.answer.assert_awaited_once()
    call_args = mock_message.answer.call_args
    assert "Successfully logged out" in call_args.args[0]
    assert "disconnected" in call_args.args[0]


@pytest.mark.asyncio
async def test_logout_not_logged_in(
    mock_message: MockType, mocker: MockerFixture
) -> None:
    """Test /logout command when user is not logged in."""
    mock_logout = mocker.patch("app.bot.logout_user", return_value=False)

    await bot.logout(mock_message)

    mock_logout.assert_called_once_with(mock_message.from_user.id)
    mock_message.answer.assert_awaited_once()
    call_args = mock_message.answer.call_args
    assert "not currently logged in" in call_args.args[0]


@pytest.mark.asyncio
async def test_inline_query_expired(
    mock_inline_query: MockType, mock_playback_data: Track, mocker: MockerFixture
) -> None:
    """Test inline query when query expires before response."""
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import AnswerInlineQuery

    mock_inline_query.answer.side_effect = TelegramBadRequest(
        method=AnswerInlineQuery(
            inline_query_id="test",
            results=[],
        ),
        message="Bad Request: query is too old and response timeout expired or query ID is invalid",
    )

    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_inline_query_with_playlist_context(
    mock_inline_query: MockType,
    mocker: MockerFixture,
    test_track: Track,
) -> None:
    """Test inline query with playlist context (non-Album)."""
    from app.spotify.models import ExternalUrl, Image, Playlist

    test_playlist = Playlist(
        id="playlist123",
        name="Test Playlist",
        external_urls=ExternalUrl(spotify="https://open.spotify.com/playlist/123"),
        images=[
            Image(
                url="https://example.com/playlist.jpg",
                width=300,
                height=300,
            )
        ],
    )

    async def mock_with_playlist(user_id: int) -> tuple[Track, Playlist]:
        return test_track, test_playlist

    mocker.patch("app.bot.get_playback_data", side_effect=mock_with_playlist)

    await bot.inline_query(mock_inline_query)

    mock_inline_query.answer.assert_awaited_once()
    results = mock_inline_query.answer.call_args.kwargs["results"]
    assert len(results) == 2
    assert results[1].title == test_playlist.name


@pytest.mark.asyncio
async def test_queue_callback_restricted_device(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback when device is restricted."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyApiError

    mock_callback_query.data = "queue;track123"

    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(
        side_effect=SpotifyApiError("Restricted device", 403)
    )
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "Your device is not supported", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_generic_error(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback with generic Spotify API error."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyApiError

    mock_callback_query.data = "queue;track123"

    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(
        side_effect=SpotifyApiError("Some other error", 500)
    )
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "An error occurred", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_unexpected_exception(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback with unexpected exception."""
    from unittest.mock import AsyncMock

    mock_callback_query.data = "queue;track123"

    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(side_effect=RuntimeError("Unexpected error"))
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "An error occurred. Please try again.", show_alert=True
    )


@pytest.mark.asyncio
async def test_inline_query_cache_hit(
    mock_inline_query: MockType,
    mocker: MockerFixture,
    test_track: Track,
    telegram_user_id: int,
) -> None:
    """Test inline query cache hit scenario."""
    # Pre-populate the cache
    bot._inline_query_cache[telegram_user_id] = (test_track, None)

    # Mock get_playback_data to ensure it's not called on cache hit
    mock_get_playback = mocker.patch("app.bot.get_playback_data")

    await bot.inline_query(mock_inline_query)

    # Verify cache was used and get_playback_data was not called
    mock_get_playback.assert_not_called()
    mock_inline_query.answer.assert_awaited_once()
    results = mock_inline_query.answer.call_args.kwargs["results"]
    assert len(results) > 0
    assert results[0].url == test_track.url


@pytest.mark.asyncio
async def test_help_no_user(mocker: MockerFixture) -> None:
    """Test /help command when message has no user (edge case)."""
    from aiogram import types

    # Create message with no user
    message = mocker.Mock(spec=types.Message)
    message.from_user = None
    message.answer = mocker.AsyncMock()

    # Should log error and return early without calling answer
    await bot.help(message)

    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_no_user(mocker: MockerFixture) -> None:
    """Test /start command when message has no user (edge case)."""
    from aiogram import types

    # Create message with no user
    message = mocker.Mock(spec=types.Message)
    message.from_user = None
    message.answer = mocker.AsyncMock()

    # Should log error and return early without calling answer
    await bot.start(message)

    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_logout_no_user(mocker: MockerFixture) -> None:
    """Test /logout command when message has no user (edge case)."""
    from aiogram import types

    # Create message with no user
    message = mocker.Mock(spec=types.Message)
    message.from_user = None
    message.answer = mocker.AsyncMock()

    # Should log error and return early without calling answer
    await bot.logout(message)

    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_no_data(mock_callback_query: MockType) -> None:
    """Test callback query without data (edge case)."""
    # Set data to None
    mock_callback_query.data = None

    # Should log error and return early without calling answer
    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_query_other_telegram_error(
    mock_inline_query: MockType, mock_playback_data: Track, mocker: MockerFixture
) -> None:
    """Test inline query with non-expired TelegramBadRequest error (should raise)."""
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import AnswerInlineQuery

    mock_inline_query.answer.side_effect = TelegramBadRequest(
        method=AnswerInlineQuery(
            inline_query_id="test",
            results=[],
        ),
        message="Some other error",
    )

    # Should raise the exception since it's not a "query is too old" error
    with pytest.raises(TelegramBadRequest, match="Some other error"):
        await bot.inline_query(mock_inline_query)


@pytest.mark.asyncio
async def test_queue_callback_invalid_refresh_token(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback with invalid refresh token."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyInvalidRefreshTokenError

    mock_callback_query.data = "queue;track123"

    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(side_effect=SpotifyInvalidRefreshTokenError())
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "Your Spotify session expired. Please log in again.", show_alert=True
    )


@pytest.mark.asyncio
async def test_queue_callback_token_revoked(
    mock_callback_query: MockType, mocker: MockerFixture
) -> None:
    """Test queue callback with revoked token."""
    from unittest.mock import AsyncMock

    from app.spotify.errors import SpotifyTokenRevokedError

    mock_callback_query.data = "queue;track123"

    mock_client = mocker.Mock()
    mock_client.add_to_queue = AsyncMock(side_effect=SpotifyTokenRevokedError())
    mocker.patch("app.user_service.get_user_spotify_client", return_value=mock_client)

    await bot.queue_callback(mock_callback_query)

    mock_callback_query.answer.assert_awaited_once_with(
        "Your Spotify session expired. Please log in again.", show_alert=True
    )
