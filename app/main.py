from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import sentry_sdk
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.encryption import StateExpiredError, validate_state
from app.messages import get_inline_mode_instructions
from app.models import User
from app.spotify.auth import SpotifyAuthError, get_token

from .bot import bot, dp
from .config import config
from .db import get_session
from .logger import configure_uvicorn_loggers, logger

if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.ENVIRONMENT,
        enable_logs=True,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
    )
    logger.info("Sentry initialized with environment: %s", config.ENVIRONMENT)
else:
    logger.info("Sentry not configured, skipping initialization")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Configure uvicorn loggers to use our RichHandler format
    configure_uvicorn_loggers()

    await bot.set_webhook(
        f"{config.APP_URL}{config.BOT_WEBHOOK_PATH}",
        allowed_updates=["message", "inline_query", "callback_query"],
        secret_token=config.BOT_WEBHOOK_SECRET,
    )
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="help", description="How to use inline mode and login"),
            BotCommand(command="logout", description="Disconnect your Spotify account"),
        ]
    )
    logger.info("Webhook set")
    try:
        yield
    finally:
        if config.ENVIRONMENT == "development":
            await bot.delete_my_commands()
            await bot.delete_webhook()
        logger.info("App shutdown")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(config.BOT_WEBHOOK_PATH)
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


@app.get(config.SPOTIFY_CALLBACK_PATH)
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

    try:
        await bot.send_message(
            chat_id=int(telegram_user_id),
            text=f"✅ Successfully logged in with Spotify!\n\n{get_inline_mode_instructions(bot_info.username)}",
        )
    except Exception as e:
        logger.error("Failed to send welcome message: %s", str(e))

    return RedirectResponse(url=telegram_url)
