from datetime import datetime, timezone
from typing import Any

import httpx
from cachetools import TTLCache
from pydantic import BaseModel, ValidationError

from app.logger import get_logger
from app.spotify.errors import SpotifyApiError, SpotifyTokenExpiredError

from .models import (
    Album,
    Artist,
    Context,
    Contextable,
    CurrentlyPlayingResponse,
    Playlist,
    RecentlyPlayedResponse,
)

logger = get_logger(__name__)


class SpotifyClient(httpx.AsyncClient):
    _access_token: str
    _refresh_token: str
    _expires_at: datetime

    # Shared cache across all instances - caches public Spotify data (albums, artists, playlists)
    _cache: TTLCache[str, BaseModel] = TTLCache(maxsize=100, ttl=300)

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at

        super().__init__(
            headers={"Authorization": f"Bearer {access_token}"},
            base_url="https://api.spotify.com/v1",
        )

    def _check_token_expiration(self) -> None:
        """Check if the access token has expired and raise if so."""
        if self._expires_at <= datetime.now(timezone.utc):
            raise SpotifyTokenExpiredError()

    async def _common_get[T: BaseModel](
        self,
        endpoint: str,
        model: type[T],
        id: str | None = None,
        params: dict[str, Any] | None = None,
        cacheable: bool = False,
    ) -> T | None:
        self._check_token_expiration()

        cache_key = f"{endpoint}/{id or ''}{f'?{params}' if params else ''}"

        if cacheable and cache_key in self._cache:
            logger.debug("Cache hit for %s", cache_key)
            cached_result = self._cache[cache_key]
            if isinstance(cached_result, model):
                return cached_result

        r = await self.get(
            f"{endpoint}" + (f"/{id}" if id else ""),
            params=params,
        )

        logger.debug("Spotify API GET %s - %d", r.url, r.status_code)
        logger.debug("Response: %s", r.text)

        if r.status_code == 401 and "expired" in r.text.lower():
            raise SpotifyTokenExpiredError()

        if r.status_code != 200:
            return None

        try:
            result = model.model_validate_json(r.text)

            if cacheable:
                self._cache[cache_key] = result
            return result
        except ValidationError:
            logger.exception("Failed to parse Spotify API response for %s", r.url)
            return None

    async def get_album(self, id: str) -> Album | None:
        return await self._common_get("/albums", Album, id, cacheable=True)

    async def get_artist(self, id: str) -> Artist | None:
        return await self._common_get("/artists", Artist, id, cacheable=True)

    async def get_playlist(self, id: str) -> Playlist | None:
        fields = "id,name,external_urls,images"
        return await self._common_get(
            "/playlists", Playlist, id, cacheable=True, params={"fields": fields}
        )

    async def get_currently_playing(self) -> CurrentlyPlayingResponse | None:
        return await self._common_get(
            "/me/player/currently-playing", CurrentlyPlayingResponse
        )

    async def get_recently_played(
        self, limit: int = 1
    ) -> RecentlyPlayedResponse | None:
        return await self._common_get(
            "/me/player/recently-played",
            RecentlyPlayedResponse,
            params={"limit": limit},
        )

    async def get_context_details(self, context: Context) -> Contextable | None:
        logger.debug("Fetching context details for: %s", context)
        id = context.uri.split(":")[-1]
        out = None
        match context.type:
            case "album":
                out = await self.get_album(id)
            case "artist":
                out = await self.get_artist(id)
            case "playlist":
                out = await self.get_playlist(id)
            case "collection":
                # Collections are things like "Liked Songs" which are not retrievable via API
                pass
            case _:
                logger.error("Unknown context type for: %s", context)
                return None

        return out

    async def add_to_queue(self, track_id: str) -> bool:
        self._check_token_expiration()

        uri = f"spotify:track:{track_id}"
        r = await self.post("/me/player/queue", params={"uri": uri})

        logger.debug("Spotify API POST %s - %d", r.url, r.status_code)
        logger.debug("Response: %s", r.text)

        if r.status_code == 401 and "expired" in r.text.lower():
            raise SpotifyTokenExpiredError()

        if r.status_code in (200, 204):
            return True

        # Parse error message from response
        error_message = "An error occurred"
        try:
            error_data = r.json()
            if "error" in error_data:
                if isinstance(error_data["error"], dict):
                    error_message = error_data["error"].get("message", error_message)
                else:
                    error_message = str(error_data["error"])
        except ValueError, KeyError:
            # Failed to parse error response, use default message
            pass

        raise SpotifyApiError(error_message, r.status_code)
