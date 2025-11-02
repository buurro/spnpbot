"""Tests for database error handling."""

from typing import Any, Never
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import get_async_database_url, get_session


@pytest.mark.asyncio
async def test_get_session_success() -> None:
    """Test get_session returns a valid session."""
    async with get_session() as session:
        assert session is not None


@pytest.mark.asyncio
async def test_get_session_retry_on_operational_error() -> None:
    """Test get_session retries on OperationalError."""
    from sqlalchemy.ext.asyncio import AsyncSession

    call_count = 0

    def mock_session_init(*args: Any, **kwargs: Any) -> AsyncSession:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OperationalError("Database locked", None, Exception("DB locked"))
        return AsyncSession(*args, **kwargs)

    with patch("app.db.AsyncSession", side_effect=mock_session_init):
        async with get_session() as session:
            assert session is not None
            assert call_count == 2  # First failed, second succeeded


@pytest.mark.asyncio
async def test_get_session_exhausts_retries() -> None:
    """Test get_session raises error after exhausting retries."""

    def always_fail(*args: Any, **kwargs: Any) -> Never:  # noqa: ANN401
        raise OperationalError("Database error", None, Exception("DB error"))

    with patch("app.db.AsyncSession", side_effect=always_fail):
        with pytest.raises(OperationalError, match="Database error"):
            async with get_session(max_retries=2, retry_delay=0.01):
                pass


@pytest.mark.asyncio
async def test_get_session_exponential_backoff() -> None:
    """Test get_session uses exponential backoff."""
    from sqlalchemy.ext.asyncio import AsyncSession

    call_count = 0

    def mock_session_init(*args: Any, **kwargs: Any) -> AsyncSession:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise OperationalError("Database locked", None, Exception("DB locked"))
        return AsyncSession(*args, **kwargs)

    with patch("app.db.AsyncSession", side_effect=mock_session_init):
        with patch("app.db.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            async with get_session(retry_delay=0.1) as session:
                assert session is not None
                assert call_count == 3
                # Check exponential backoff: 0.1, 0.2
                assert mock_sleep.call_count == 2
                assert mock_sleep.call_args_list[0][0][0] == 0.1
                assert mock_sleep.call_args_list[1][0][0] == 0.2


def test_get_async_database_url_sqlite() -> None:
    """Test _get_async_database_url converts sqlite URL correctly."""
    url = "sqlite:///path/to/db.sqlite"
    expected = "sqlite+aiosqlite:///path/to/db.sqlite"
    assert get_async_database_url(url) == expected


def test_get_async_database_url_postgresql() -> None:
    """Test _get_async_database_url converts postgresql URL correctly."""
    url = "postgresql://user:pass@localhost/db"
    expected = "postgresql+psycopg://user:pass@localhost/db"
    assert get_async_database_url(url) == expected


def test_get_async_database_url_postgresql_psycopg() -> None:
    """Test _get_async_database_url handles existing psycopg driver."""
    url = "postgresql+psycopg://user:pass@localhost/db"
    expected = "postgresql+psycopg://user:pass@localhost/db"
    assert get_async_database_url(url) == expected


def test_get_async_database_url_other() -> None:
    """Test _get_async_database_url returns other URLs unchanged."""
    url = "mysql://user:pass@localhost/db"
    assert get_async_database_url(url) == url


@pytest.mark.asyncio
async def test_large_telegram_id(test_db: AsyncEngine) -> None:
    """Test that large Telegram IDs (exceeding 32-bit int) are handled correctly."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

    # Use a real Telegram ID that exceeds 32-bit INTEGER max (2,147,483,647)
    # This is the ID from the error log that caused the overflow
    large_telegram_id = 5272036395

    async with AsyncSession(test_db, expire_on_commit=False) as session:
        # Create user with large ID
        user = User(
            telegram_id=large_telegram_id,
            spotify_access_token="test_access_token",
            spotify_refresh_token="test_refresh_token",
            spotify_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(user)
        await session.commit()

    # Verify we can retrieve the user by large ID
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        retrieved_user = await session.get(User, large_telegram_id)
        assert retrieved_user is not None
        assert retrieved_user.telegram_id == large_telegram_id
        assert retrieved_user.spotify_access_token == "test_access_token"

    # Clean up
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = await session.get(User, large_telegram_id)
        if user:
            await session.delete(user)
            await session.commit()
