import base64
from json import JSONDecodeError
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError

from app.config import config
from app.logger import get_logger
from app.spotify.models import RefreshTokenResponse, TokenResponse

from .errors import (
    SpotifyAuthError,
    SpotifyInvalidRefreshTokenError,
    SpotifyTokenError,
)

logger = get_logger(__name__)


def get_login_url(state: str) -> str:
    scopes = [
        "user-read-recently-played",
        "user-read-playback-state",
        "user-read-currently-playing",
        "user-modify-playback-state",
    ]

    url = "https://accounts.spotify.com/authorize"
    params = {
        "response_type": "code",
        "client_id": config.SPOTIFY_CLIENT_ID,
        "scope": " ".join(scopes),
        "redirect_uri": config.APP_URL + config.SPOTIFY_CALLBACK_PATH,
        "state": state,
    }

    url += "?" + urlencode(params)

    return url


def _get_auth_header() -> str:
    auth_info = base64.b64encode(
        (config.SPOTIFY_CLIENT_ID + ":" + config.SPOTIFY_CLIENT_SECRET).encode()
    ).decode()
    return f"Basic {auth_info}"


async def get_token(authorization_code: str) -> TokenResponse:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": config.APP_URL + config.SPOTIFY_CALLBACK_PATH,
            },
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "Authorization": _get_auth_header(),
            },
        )

        if r.status_code != 200:
            logger.error("Failed to get token: %s", r.text)
            raise SpotifyAuthError("could not log you in :c")

        try:
            token_response = TokenResponse.model_validate_json(r.text)
        except ValidationError:
            logger.exception("Invalid token response")
            raise SpotifyAuthError("could not log you in :c")

        return token_response


async def refresh_token(refresh_token: str) -> RefreshTokenResponse:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "Authorization": _get_auth_header(),
            },
        )

        if r.status_code == 400:
            try:
                error_response = r.json()
            except JSONDecodeError:
                logger.error("Failed to refresh token: %s", r.text)
                raise SpotifyTokenError(r.text) from None

            error = error_response.get("error")
            description = error_response.get("error_description")
            logger.error("Failed to refresh token: %s (%s)", error, description)

            # Match on `error`, not `error_description`: Spotify changes the
            # free-text wording without notice ("Refresh token expired" showed
            # up unannounced and escaped every handler). Any invalid_grant on a
            # refresh means the same thing: the token is dead, re-auth needed.
            if error == "invalid_grant":
                raise SpotifyInvalidRefreshTokenError(r.text)
            raise SpotifyTokenError(r.text)

        if r.status_code != 200:
            logger.error("Failed to refresh token: %s", r.text)
            raise SpotifyTokenError("could not refresh token")

        try:
            token_response = RefreshTokenResponse.model_validate_json(r.text)
        except ValidationError:
            logger.exception("Invalid token response: %s", r.text)
            raise SpotifyAuthError("could not refresh token")

        return token_response
