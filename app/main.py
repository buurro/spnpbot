import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
from aiogram.types import BotCommand
from fastapi import FastAPI

from . import STARTUP_T0
from .bot import bot
from .config import config
from .logger import configure_uvicorn_loggers, get_logger
from .routes import router

logger = get_logger(__name__)


def _since_start() -> float:
    return (time.monotonic() - STARTUP_T0) * 1000


logger.info("Imports completed in %.0f ms", _since_start())

if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.ENVIRONMENT,
        enable_logs=True,
        traces_sample_rate=1.0,
    )
    logger.info("Sentry initialized with environment: %s", config.ENVIRONMENT)
else:
    logger.info("Sentry not configured, skipping initialization")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Configure uvicorn loggers to use our RichHandler format
    configure_uvicorn_loggers()

    t = time.monotonic()
    await bot.set_webhook(
        f"{config.APP_URL}{config.BOT_WEBHOOK_PATH}",
        allowed_updates=["message", "inline_query", "callback_query"],
        secret_token=config.BOT_WEBHOOK_SECRET,
    )
    logger.info("Webhook set in %.0f ms", (time.monotonic() - t) * 1000)
    t = time.monotonic()
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="help", description="How to use inline mode and login"),
            BotCommand(command="logout", description="Disconnect your Spotify account"),
        ]
    )
    logger.info(
        "Commands set in %.0f ms; startup ready %.0f ms after first import",
        (time.monotonic() - t) * 1000,
        _since_start(),
    )
    try:
        yield
    finally:
        if config.ENVIRONMENT == "development":
            await bot.delete_my_commands()
            await bot.delete_webhook()
        logger.info("App shutdown")


app = FastAPI(lifespan=lifespan)

app.include_router(router)
