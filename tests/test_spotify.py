"""Tests for Spotify functionality."""

from datetime import datetime, timedelta, timezone

import pytest
import respx
from httpx import Response

from app.spotify.api import SpotifyClient
from app.spotify.auth import get_token, refresh_token
from app.spotify.errors import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyInvalidRefreshTokenError,
    SpotifyTokenError,
    SpotifyTokenExpiredError,
    SpotifyTokenRevokedError,
)
from app.spotify.models import Context
from tests.mock_utils import (
    mock_spotify_nothing_playing,
    mock_spotify_podcast_playing,
    mock_spotify_track_playing,
)


@pytest.fixture
def spotify_client() -> SpotifyClient:
    """Create a SpotifyClient with test credentials."""
    # Clear the shared cache before each test to ensure isolation
    SpotifyClient._cache.clear()

    return SpotifyClient(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_currently_playing(spotify_client: SpotifyClient) -> None:
    mock_spotify_track_playing(
        respx.mock,
        track_name="Bohemian Rhapsody",
        artist_name="Queen",
        album_name="A Night at the Opera",
        track_id="3z8h0TU7ReDPLIbEnYhWZb",
    )

    result = await spotify_client.get_currently_playing()

    assert result is not None
    assert result.is_playing is True
    assert result.currently_playing_type == "track"
    assert result.item is not None
    assert result.item.name == "Bohemian Rhapsody"
    assert result.item.artists[0].name == "Queen"
    assert result.item.album.name == "A Night at the Opera"
    assert result.item.url == "https://open.spotify.com/track/3z8h0TU7ReDPLIbEnYhWZb"


@pytest.mark.asyncio
@respx.mock
async def test_get_currently_playing_paused(spotify_client: SpotifyClient) -> None:
    """Test getting a currently playing track that is paused."""
    mock_spotify_track_playing(
        respx.mock,
        track_name="Stairway to Heaven",
        artist_name="Led Zeppelin",
        album_name="Led Zeppelin IV",
        is_playing=False,
    )

    result = await spotify_client.get_currently_playing()

    assert result is not None
    assert result.is_playing is False
    assert result.currently_playing_type == "track"
    assert result.item is not None
    assert result.item.name == "Stairway to Heaven"


@pytest.mark.asyncio
@respx.mock
async def test_get_currently_playing_podcast(spotify_client: SpotifyClient) -> None:
    mock_spotify_podcast_playing(
        respx.mock,
        episode_name="The Future of AI",
        show_name="Tech Talks Daily",
        episode_id="1a2b3c4d5e6f",
        show_id="9z8y7x6w5v",
    )

    result = await spotify_client.get_currently_playing()

    assert result is not None
    assert result.is_playing is True
    assert result.currently_playing_type == "episode"
    assert result.item is not None
    assert result.item.name == "The Future of AI"
    assert result.item.show.name == "Tech Talks Daily"
    assert result.item.url == "https://open.spotify.com/episode/1a2b3c4d5e6f"


@pytest.mark.asyncio
@respx.mock
async def test_get_currently_playing_nothing(spotify_client: SpotifyClient) -> None:
    mock_spotify_nothing_playing(respx.mock)

    result = await spotify_client.get_currently_playing()

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_get_currently_playing_with_context(
    spotify_client: SpotifyClient,
) -> None:
    """Test getting currently playing track with album context."""
    mock_spotify_track_playing(
        respx.mock,
        track_name="Come Together",
        artist_name="The Beatles",
        album_name="Abbey Road",
        track_id="2EqlS6tkEnglzr7tkKAAYD",
        album_id="0ETFjACtuP2ADo6LFhL6HN",
    )

    result = await spotify_client.get_currently_playing()

    assert result is not None
    assert result.context is not None
    assert result.context.type == "album"
    assert result.context.uri == "spotify:album:0ETFjACtuP2ADo6LFhL6HN"


@pytest.mark.asyncio
@respx.mock
async def test_get_album(spotify_client: SpotifyClient) -> None:
    album_data = {
        "id": "0ETFjACtuP2ADo6LFhL6HN",
        "name": "Abbey Road",
        "external_urls": {
            "spotify": "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"
        },
        "artists": [
            {
                "id": "3WrFJ7ztbogyGnTHbHJFl2",
                "name": "The Beatles",
                "external_urls": {
                    "spotify": "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
                },
            }
        ],
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    respx.mock.get("https://api.spotify.com/v1/albums/0ETFjACtuP2ADo6LFhL6HN").mock(
        return_value=Response(200, json=album_data)
    )

    result = await spotify_client.get_album("0ETFjACtuP2ADo6LFhL6HN")

    assert result is not None
    assert result.name == "Abbey Road"
    assert result.artists[0].name == "The Beatles"
    assert result.url == "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"


@pytest.mark.asyncio
@respx.mock
async def test_get_artist(spotify_client: SpotifyClient) -> None:
    artist_data = {
        "id": "3WrFJ7ztbogyGnTHbHJFl2",
        "name": "The Beatles",
        "external_urls": {
            "spotify": "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
        },
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    respx.mock.get("https://api.spotify.com/v1/artists/3WrFJ7ztbogyGnTHbHJFl2").mock(
        return_value=Response(200, json=artist_data)
    )

    result = await spotify_client.get_artist("3WrFJ7ztbogyGnTHbHJFl2")

    assert result is not None
    assert result.name == "The Beatles"
    assert result.url == "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"


@pytest.mark.asyncio
@respx.mock
async def test_get_playlist_radio_without_image_dimensions(
    spotify_client: SpotifyClient,
) -> None:
    """Test handling of Radio playlists without image width/height.

    Radio playlists don't include width/height in their image data.
    Example: https://open.spotify.com/playlist/37i9dQZF1E8Ojcj5ESVwfA
    """
    playlist_data = {
        "id": "37i9dQZF1E8Ojcj5ESVwfA",
        "name": "Song Radio",
        "external_urls": {
            "spotify": "https://open.spotify.com/playlist/37i9dQZF1E8Ojcj5ESVwfA"
        },
        "images": [
            {
                "url": "https://i.scdn.co/image/ab67706f00000002abc123",
                "width": None,
                "height": None,
            }
        ],
    }
    respx.mock.get(
        "https://api.spotify.com/v1/playlists/37i9dQZF1E8Ojcj5ESVwfA",
        params={"fields": "id,name,external_urls,images"},
    ).mock(return_value=Response(200, json=playlist_data))

    result = await spotify_client.get_playlist("37i9dQZF1E8Ojcj5ESVwfA")

    assert result is not None
    assert result.name == "Song Radio"
    assert result.thumbnail.url == "https://i.scdn.co/image/ab67706f00000002abc123"
    assert result.thumbnail.width is None
    assert result.thumbnail.height is None


@pytest.mark.asyncio
@respx.mock
async def test_get_playlist(spotify_client: SpotifyClient) -> None:
    playlist_data = {
        "id": "37i9dQZF1DXcBWIGoYBM5M",
        "name": "Today's Top Hits",
        "external_urls": {
            "spotify": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        },
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    route = respx.mock.get(
        "https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M",
        params={"fields": "id,name,external_urls,images"},
    ).mock(return_value=Response(200, json=playlist_data))

    result = await spotify_client.get_playlist("37i9dQZF1DXcBWIGoYBM5M")

    assert result is not None
    assert result.name == "Today's Top Hits"
    assert result.url == "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_album_not_found(spotify_client: SpotifyClient) -> None:
    respx.mock.get("https://api.spotify.com/v1/albums/invalid").mock(
        return_value=Response(404, json={"error": "not found"})
    )

    result = await spotify_client.get_album("invalid")

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_get_album_invalid_response(spotify_client: SpotifyClient) -> None:
    """Test handling of invalid JSON response."""
    respx.mock.get("https://api.spotify.com/v1/albums/invalid").mock(
        return_value=Response(200, json={"invalid": "data"})
    )

    result = await spotify_client.get_album("invalid")

    assert result is None


@pytest.mark.asyncio
async def test_get_album_token_expired_before_request() -> None:
    """Test token expiration check before making request."""
    expired_client = SpotifyClient(
        access_token="test_token",
        refresh_token="test_refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    with pytest.raises(SpotifyTokenExpiredError):
        await expired_client.get_album("0ETFjACtuP2ADo6LFhL6HN")


@pytest.mark.asyncio
@respx.mock
async def test_get_album_token_expired_in_response(
    spotify_client: SpotifyClient,
) -> None:
    """Test token expiration detected from 401 response."""
    respx.mock.get("https://api.spotify.com/v1/albums/test").mock(
        return_value=Response(
            401, json={"error": {"message": "The access token expired"}}
        )
    )

    with pytest.raises(SpotifyTokenExpiredError):
        await spotify_client.get_album("test")


@pytest.mark.asyncio
@respx.mock
async def test_get_context_details_album(spotify_client: SpotifyClient) -> None:
    album_data = {
        "id": "0ETFjACtuP2ADo6LFhL6HN",
        "name": "Abbey Road",
        "external_urls": {
            "spotify": "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"
        },
        "artists": [
            {
                "id": "3WrFJ7ztbogyGnTHbHJFl2",
                "name": "The Beatles",
                "external_urls": {
                    "spotify": "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
                },
            }
        ],
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    respx.mock.get("https://api.spotify.com/v1/albums/0ETFjACtuP2ADo6LFhL6HN").mock(
        return_value=Response(200, json=album_data)
    )

    context = Context(type="album", uri="spotify:album:0ETFjACtuP2ADo6LFhL6HN")
    result = await spotify_client.get_context_details(context)

    assert result is not None
    assert result.name == "Abbey Road"


@pytest.mark.asyncio
@respx.mock
async def test_get_context_details_artist(spotify_client: SpotifyClient) -> None:
    artist_data = {
        "id": "3WrFJ7ztbogyGnTHbHJFl2",
        "name": "The Beatles",
        "external_urls": {
            "spotify": "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2"
        },
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    respx.mock.get("https://api.spotify.com/v1/artists/3WrFJ7ztbogyGnTHbHJFl2").mock(
        return_value=Response(200, json=artist_data)
    )

    context = Context(type="artist", uri="spotify:artist:3WrFJ7ztbogyGnTHbHJFl2")
    result = await spotify_client.get_context_details(context)

    assert result is not None
    assert result.name == "The Beatles"


@pytest.mark.asyncio
@respx.mock
async def test_get_context_details_playlist(spotify_client: SpotifyClient) -> None:
    playlist_data = {
        "id": "37i9dQZF1DXcBWIGoYBM5M",
        "name": "Today's Top Hits",
        "external_urls": {
            "spotify": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        },
        "images": [
            {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640}
        ],
    }
    respx.mock.get(
        "https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M",
        params={"fields": "id,name,external_urls,images"},
    ).mock(return_value=Response(200, json=playlist_data))

    context = Context(type="playlist", uri="spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
    result = await spotify_client.get_context_details(context)

    assert result is not None
    assert result.name == "Today's Top Hits"


@pytest.mark.asyncio
@respx.mock
async def test_get_context_details_collection(spotify_client: SpotifyClient) -> None:
    """Test handling of collection context type (e.g., Liked Songs)."""
    context = Context(type="collection", uri="spotify:collection:tracks")
    result = await spotify_client.get_context_details(context)

    # Collections are not retrievable via API, should return None
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_get_context_details_unknown_type(spotify_client: SpotifyClient) -> None:
    """Test handling of unknown context type."""
    context = Context(type="unknown", uri="spotify:unknown:123")
    result = await spotify_client.get_context_details(context)

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_success_200(spotify_client: SpotifyClient) -> None:
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(200)
    )

    result = await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")

    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_success_204(spotify_client: SpotifyClient) -> None:
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(204)
    )

    result = await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")

    assert result is True


@pytest.mark.asyncio
async def test_add_to_queue_token_expired_before_request() -> None:
    """Test token expiration check before making request."""
    expired_client = SpotifyClient(
        access_token="test_token",
        refresh_token="test_refresh",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    with pytest.raises(SpotifyTokenExpiredError):
        await expired_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_token_expired_in_response(
    spotify_client: SpotifyClient,
) -> None:
    """Test token expiration detected from 401 response."""
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(
            401, json={"error": {"message": "The access token expired"}}
        )
    )

    with pytest.raises(SpotifyTokenExpiredError):
        await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_error_dict_format(spotify_client: SpotifyClient) -> None:
    """Test error handling with dict error format."""
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(
            403,
            json={
                "error": {"message": "Player command failed: No active device found"}
            },
        )
    )

    with pytest.raises(SpotifyApiError) as exc_info:
        await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")

    error = exc_info.value
    assert isinstance(error, SpotifyApiError)
    assert "No active device found" in error.message
    assert error.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_error_string_format(spotify_client: SpotifyClient) -> None:
    """Test error handling with string error format."""
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(400, json={"error": "invalid request"})
    )

    with pytest.raises(SpotifyApiError) as exc_info:
        await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")

    error = exc_info.value
    assert isinstance(error, SpotifyApiError)
    assert error.message == "invalid request"
    assert error.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_add_to_queue_error_unparseable(spotify_client: SpotifyClient) -> None:
    """Test error handling with unparseable response."""
    respx.mock.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(500, text="Internal Server Error")
    )

    with pytest.raises(SpotifyApiError) as exc_info:
        await spotify_client.add_to_queue("3z8h0TU7ReDPLIbEnYhWZb")

    error = exc_info.value
    assert isinstance(error, SpotifyApiError)
    assert error.message == "An error occurred"
    assert error.status_code == 500


@pytest.mark.asyncio
@respx.mock
async def test_get_token_success() -> None:
    token_data = {
        "access_token": "test_access_token",
        "token_type": "Bearer",
        "scope": "user-read-currently-playing",
        "expires_in": 3600,
        "refresh_token": "test_refresh_token",
    }
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json=token_data)
    )

    result = await get_token("auth_code_123")

    assert result.access_token == "test_access_token"
    assert result.refresh_token == "test_refresh_token"
    assert result.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_get_token_error_response() -> None:
    """Test handling of error response from token endpoint."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(SpotifyAuthError) as exc_info:
        await get_token("invalid_code")

    assert "could not log you in" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_token_invalid_json_response() -> None:
    """Test handling of invalid JSON response from token endpoint."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json={"invalid": "response"})
    )

    with pytest.raises(SpotifyAuthError) as exc_info:
        await get_token("auth_code")

    assert "could not log you in" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_success() -> None:
    token_data = {
        "access_token": "new_access_token",
        "token_type": "Bearer",
        "scope": "user-read-currently-playing",
        "expires_in": 3600,
    }
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json=token_data)
    )

    result = await refresh_token("old_refresh_token")

    assert result.access_token == "new_access_token"
    assert result.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_error_response() -> None:
    """Test handling of unrecognized 400 error response from refresh endpoint."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(SpotifyTokenError) as exc_info:
        await refresh_token("invalid_refresh_token")

    assert "invalid_grant" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_invalid_json_response() -> None:
    """Test handling of invalid JSON response from refresh endpoint."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(200, json={"invalid": "response"})
    )

    with pytest.raises(SpotifyAuthError) as exc_info:
        await refresh_token("refresh_token")

    assert "could not refresh token" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_invalid_refresh_token_error() -> None:
    """Test handling of invalid refresh token error."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(400, json={"error_description": "Invalid refresh token"})
    )

    with pytest.raises(SpotifyInvalidRefreshTokenError):
        await refresh_token("invalid_refresh_token")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_revoked_error() -> None:
    """Test handling of revoked refresh token error."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(400, json={"error_description": "Refresh token revoked"})
    )

    with pytest.raises(SpotifyTokenRevokedError):
        await refresh_token("revoked_refresh_token")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_bad_request_with_json_decode_error() -> None:
    """Test handling of 400 error with invalid JSON."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(400, text="Not JSON")
    )

    with pytest.raises(SpotifyTokenError, match="Not JSON"):
        await refresh_token("test_refresh_token")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_non_200_non_400_error() -> None:
    """Test handling of non-200, non-400 status codes."""
    respx.mock.post("https://accounts.spotify.com/api/token").mock(
        return_value=Response(500, text="Server error")
    )

    with pytest.raises(SpotifyTokenError, match="could not refresh token"):
        await refresh_token("test_refresh_token")
