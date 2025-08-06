import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    APP_URL: str
    APP_SECRET: str

    BOT_TOKEN: str
    BOT_WEBHOOK_PATH: str = "/telegram/webhook"
    BOT_WEBHOOK_SECRET: str

    SPOTIFY_CLIENT_ID: str
    SPOTIFY_CLIENT_SECRET: str
    SPOTIFY_CALLBACK_PATH: str = "/spotify/callback"

    DATABASE_URL: str = "sqlite:///database.db"
    DATABASE_ECHO: bool = False

    SENTRY_DSN: str | None = None

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"), env_file_encoding="utf-8"
    )


config = Config()  # type: ignore[call-arg]
