"""Utilities for creating user status mocks with Spotify data."""

import respx
from httpx import Response


def mock_spotify_track_playing(
    respx_mock: respx.MockRouter,
    track_name: str = "Test Track",
    artist_name: str = "Test Artist",
    album_name: str = "Test Album",
    track_id: str = "3qL63QvSTHvC4Uw8eEhz4z",
    artist_id: str = "1dfeR4HaWDbWqFHLkxsg1d",
    album_id: str = "4aawyAB9vmqN3uQ7FjRGTy",
    is_playing: bool = True,
) -> None:
    response_data = {
        "is_playing": is_playing,
        "currently_playing_type": "track",
        "item": {
            "id": track_id,
            "name": track_name,
            "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
            "artists": [
                {
                    "id": artist_id,
                    "name": artist_name,
                    "external_urls": {
                        "spotify": f"https://open.spotify.com/artist/{artist_id}"
                    },
                }
            ],
            "album": {
                "id": album_id,
                "name": album_name,
                "external_urls": {
                    "spotify": f"https://open.spotify.com/album/{album_id}"
                },
                "artists": [
                    {
                        "id": artist_id,
                        "name": artist_name,
                        "external_urls": {
                            "spotify": f"https://open.spotify.com/artist/{artist_id}"
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
                    {"url": "https://i.scdn.co/image/small", "width": 64, "height": 64},
                ],
            },
        },
        "context": {
            "type": "album",
            "uri": f"spotify:album:{album_id}",
        },
    }

    respx_mock.get("https://api.spotify.com/v1/me/player/currently-playing").mock(
        return_value=Response(200, json=response_data)
    )


def mock_spotify_nothing_playing(respx_mock: respx.MockRouter) -> None:
    """Mock Spotify API to return nothing currently playing.

    Args:
        respx_mock: The respx mock router
    """
    respx_mock.get("https://api.spotify.com/v1/me/player/currently-playing").mock(
        return_value=Response(204)
    )
