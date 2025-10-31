import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import ParamSpec, TypeVar

from app.logger import logger
from app.spotify.api import SpotifyClient
from app.spotify.auth import refresh_token
from app.spotify.errors import (
    SpotifyInvalidRefreshTokenError,
    SpotifyTokenExpiredError,
    SpotifyTokenRevokedError,
)
from app.spotify.models import Contextable, Track

from .db import get_session
from .models import User

P = ParamSpec("P")
T = TypeVar("T")


class UserNotLoggedInError(Exception):
    """Raised when a user is not logged in with Spotify."""


def with_token_refresh(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]:
    """Decorator that automatically refreshes Spotify token on expiration and retries.

    The decorated function must be async and take a user_id parameter (int).
    If a SpotifyTokenExpiredError is raised, the token will be refreshed
    and the function will be retried once.

    If the refresh token is invalid or revoked (SpotifyInvalidRefreshTokenError
    or SpotifyTokenRevokedError), the user's tokens are cleared and the exception
    is propagated to notify the caller that re-authentication is needed.

    Args:
        func: The async function to decorate

    Returns:
        The decorated function with automatic token refresh
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await func(*args, **kwargs)
        except SpotifyTokenExpiredError:
            # Extract user_id from args or kwargs
            user_id = kwargs.get("user_id") or (args[0] if args else None)
            if user_id is None:
                raise ValueError(
                    "with_token_refresh decorator requires user_id parameter"
                )

            if not isinstance(user_id, int):
                raise TypeError(
                    f"with_token_refresh decorator expects user_id to be int, got {type(user_id)}"
                )
            logger.warning("spotify token expired for user %d, refreshing", user_id)

            try:
                await refresh_user_spotify_token(user_id)
            except (SpotifyInvalidRefreshTokenError, SpotifyTokenRevokedError):
                # Token cannot be refreshed, user needs to re-authenticate
                # The exception is already logged in refresh_user_spotify_token
                raise

            # Retry once after refresh
            return await func(*args, **kwargs)

    return wrapper


async def get_user_spotify_client(telegram_id: int) -> SpotifyClient | None:
    async with get_session() as session:
        user = await session.get(User, telegram_id)
        if not user:
            return None
        return SpotifyClient(
            access_token=user.spotify_access_token,
            refresh_token=user.spotify_refresh_token,
            expires_at=user.spotify_expires_at,
        )


async def refresh_user_spotify_token(telegram_id: int) -> None:
    async with get_session() as session:
        user = await session.get(User, telegram_id)
        if not user:
            return

        try:
            response = await refresh_token(user.spotify_refresh_token)
        except (SpotifyInvalidRefreshTokenError, SpotifyTokenRevokedError) as e:
            logger.error(
                "Failed to refresh token for user %d: %s. Clearing tokens.",
                telegram_id,
                type(e).__name__,
            )
            # Clear the user's Spotify tokens as they need to re-authenticate
            user.spotify_access_token = ""
            user.spotify_refresh_token = ""
            user.spotify_expires_at = datetime.now(timezone.utc)
            session.add(user)
            await session.commit()
            raise

        user.spotify_access_token = response.access_token
        user.spotify_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=response.expires_in
        )
        session.add(user)
        await session.commit()


@with_token_refresh
async def get_playback_data(user_id: int) -> tuple[Track | None, Contextable | None]:
    spotify_client = await get_user_spotify_client(user_id)
    if not spotify_client:
        logger.warning("no spotify client for user %d", user_id)
        raise UserNotLoggedInError()

    # Start both calls concurrently, but await currently_playing first
    currently_playing_task = asyncio.create_task(
        spotify_client.get_currently_playing(),
    )

    recently_played_task = asyncio.create_task(
        spotify_client.get_recently_played(limit=1),
    )
    # Suppress exceptions from background task to avoid unawaited warnings
    recently_played_task.add_done_callback(lambda t: t.exception())

    status = await currently_playing_task

    if not status or not status.track:
        logger.debug(
            "no track currently playing for user %d. using recently played", user_id
        )
        recently_played = await recently_played_task
        if not recently_played or not recently_played.items:
            logger.info("no recently played tracks for user %d", user_id)
            return None, None

        status = recently_played.items[0]
    else:
        # Cancel the recently_played task since we don't need it
        recently_played_task.cancel()

    context = None
    if status.context:
        context = await spotify_client.get_context_details(status.context)

    return status.track, context


@with_token_refresh
async def add_track_to_queue(user_id: int, track_id: str) -> bool:
    spotify_client = await get_user_spotify_client(user_id)
    if not spotify_client:
        logger.warning("no spotify client for user %d", user_id)
        raise UserNotLoggedInError()

    await spotify_client.add_to_queue(track_id)
    logger.info("Added track %s to queue for user %d", track_id, user_id)
    return True


async def logout_user(telegram_id: int) -> bool:
    """Log out a user by deleting their Spotify tokens.

    Args:
        telegram_id: The Telegram user ID

    Returns:
        True if user was logged out, False if user was not found
    """
    async with get_session() as session:
        user = await session.get(User, telegram_id)
        if not user:
            logger.info("User %d not found, cannot logout", telegram_id)
            return False

        # Delete the user record entirely
        await session.delete(user)
        await session.commit()
        logger.info("User %d logged out successfully", telegram_id)
        return True
