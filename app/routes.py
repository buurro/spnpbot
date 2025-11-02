from datetime import datetime, timedelta, timezone

from aiogram.types import Update
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.bot import bot, dp
from app.config import config
from app.db import get_session
from app.encryption import StateExpiredError, validate_state
from app.logger import logger
from app.messages import get_inline_mode_instructions
from app.models import User
from app.spotify.auth import SpotifyAuthError, get_token

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post(config.BOT_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    # Validate Telegram webhook secret token
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_token != config.BOT_WEBHOOK_SECRET:
        logger.warning("Invalid webhook secret token")
        return {"ok": False}

    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot=bot, update=update)
    return {"ok": True}


@router.get(config.SPOTIFY_CALLBACK_PATH)
async def spotify_auth_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    bot_info = await bot.get_me()
    telegram_url = f"https://t.me/{bot_info.username}"

    if error:
        logger.error("Spotify auth error: %s", error)
        return RedirectResponse(url=telegram_url)

    if not code:
        logger.error("Missing authorization code from Spotify")
        return RedirectResponse(url=telegram_url)

    try:
        telegram_user_id = validate_state(state)
    except StateExpiredError as e:
        logger.error("State expired: %s", str(e))
        # Send error message to user if possible
        return RedirectResponse(url=telegram_url)
    except ValueError as e:
        logger.error("Invalid state: %s", str(e))
        return RedirectResponse(url=telegram_url)

    try:
        token_response = await get_token(code)
    except SpotifyAuthError as e:
        logger.error("SpotifyAuthError: %s", str(e))
        return RedirectResponse(url=telegram_url)

    user = User(
        telegram_id=int(telegram_user_id),
        spotify_access_token=token_response.access_token,
        spotify_refresh_token=token_response.refresh_token,
        spotify_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=token_response.expires_in),
    )

    async with get_session() as session:
        await session.merge(user)
        await session.commit()

    logger.info("User %s logged in successfully", telegram_user_id)

    try:
        await bot.send_message(
            chat_id=int(telegram_user_id),
            text=f"✅ Successfully logged in with Spotify!\n\n{get_inline_mode_instructions(bot_info.username)}",
        )
    except Exception as e:
        logger.error("Failed to send welcome message: %s", str(e))

    return RedirectResponse(url=telegram_url)
