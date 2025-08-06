"""Pytest configuration and fixtures."""

import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Mock sentry_sdk BEFORE any app imports to prevent Sentry initialization
mock_sentry = MagicMock()
sys.modules["sentry_sdk"] = mock_sentry

# Point pydantic-settings to load .env.test instead of .env
# This must happen BEFORE any app imports because app.config is loaded at import time
os.environ["ENV_FILE"] = ".env.test"

# Ensure Sentry is explicitly disabled for tests
os.environ["SENTRY_DSN"] = ""

# All imports below must come after environment setup
import pytest
import pytest_asyncio
from aiogram import types
from aiogram.types import InlineQuery
from aiogram.types import User as TelegramUser
from pytest_mock import MockerFixture, MockType
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import User
from app.spotify.models import (
    Album,
    ExternalUrl,
    Image,
    SimplifiedArtist,
    Track,
)


@pytest.fixture(scope="session", autouse=True)
def verify_sentry_disabled():
    """Verify that Sentry is not initialized during tests."""
    from app.config import config

    assert config.SENTRY_DSN is None or config.SENTRY_DSN == "", (
        "Sentry should not be enabled during tests. "
        "SENTRY_DSN must be empty in .env.test"
    )

    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_database_connections():
    """Clean up database connections after all tests to prevent ResourceWarnings."""
    yield
    # Can't dispose async engine from sync fixture
    # Engine cleanup will happen on exit


# Filter out ResourceWarnings from sqlite3 connections
# These are caused by SQLAlchemy's connection pooling and are expected
warnings.filterwarnings(
    "ignore", category=ResourceWarning, message=".*sqlite3.Connection.*"
)


# ============================================================================
# Spotify Model Fixtures
# ============================================================================


@pytest.fixture
def test_artist() -> SimplifiedArtist:
    """Create a test artist."""
    return SimplifiedArtist(
        id="artist123",
        name="Test Artist",
        external_urls=ExternalUrl(spotify="https://open.spotify.com/artist/artist123"),
    )


@pytest.fixture
def test_album(test_artist: SimplifiedArtist) -> Album:
    """Create a test album."""
    return Album(
        id="album123",
        name="Test Album",
        external_urls=ExternalUrl(spotify="https://open.spotify.com/album/album123"),
        artists=[test_artist],
        images=[
            Image(url="https://example.com/image.jpg", width=640, height=640),
            Image(url="https://example.com/image.jpg", width=300, height=300),
            Image(url="https://example.com/image.jpg", width=64, height=64),
        ],
    )


@pytest.fixture
def test_track(test_artist: SimplifiedArtist, test_album: Album) -> Track:
    """Create a test track."""
    return Track(
        id="track123",
        name="Test Track",
        artists=[test_artist],
        external_urls=ExternalUrl(spotify="https://open.spotify.com/track/track123"),
        album=test_album,
    )


# ============================================================================
# Telegram Mock Fixtures
# ============================================================================


@pytest.fixture
def telegram_user_id() -> int:
    """Standard test user ID."""
    return 42


@pytest.fixture
def telegram_user(telegram_user_id: int) -> TelegramUser:
    """Create a mock Telegram user."""
    return TelegramUser(id=telegram_user_id, is_bot=False, first_name="Tester")


@pytest.fixture
def mock_message(mocker: MockerFixture, telegram_user: TelegramUser) -> MockType:
    """Create a mock Telegram message."""
    message = mocker.Mock(spec=types.Message)
    message.from_user = telegram_user
    message.answer = mocker.AsyncMock()
    return message


@pytest.fixture
def mock_inline_query(mocker: MockerFixture, telegram_user: TelegramUser) -> MockType:
    """Create a mock Telegram inline query."""
    # Clear the inline query cache before each test
    from app.bot import _inline_query_cache

    _inline_query_cache.clear()

    query = mocker.Mock(
        spec=InlineQuery,
        id="123",
        from_user=telegram_user,
        query="",
        offset="",
    )
    query.answer = mocker.AsyncMock()
    return query


@pytest.fixture
def mock_callback_query(mocker: MockerFixture, telegram_user: TelegramUser) -> MockType:
    """Create a mock Telegram callback query."""
    callback = mocker.Mock(spec=types.CallbackQuery)
    callback.answer = mocker.AsyncMock()
    callback.from_user = telegram_user
    return callback


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def test_db(mocker: MockerFixture):
    """Create an in-memory test database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Use async engine for tests
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)

    mocker.patch("app.db.engine", engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(test_db, telegram_user_id: int) -> User:
    """Create a test user in the database with valid Spotify credentials."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            telegram_id=telegram_user_id,
            spotify_access_token="test_access_token",
            spotify_refresh_token="test_refresh_token",
            spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user
