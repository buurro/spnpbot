"""Tests for rate limiting middleware."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, InlineQuery, Message, User

from app.rate_limit import (
    RateLimitConfig,
    RateLimitMiddleware,
    RateLimiter,
)


class TestRateLimiter:
    """Test the RateLimiter class."""

    def test_allow_first_request(self):
        """Test that first request is always allowed."""
        limiter = RateLimiter()
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=123, request_type="test", limit=5, window=10
        )

        assert is_allowed is True
        assert retry_after == 0.0

    def test_allow_within_limit(self):
        """Test that requests within limit are allowed."""
        limiter = RateLimiter()

        # Make 4 requests (limit is 5)
        for _ in range(4):
            is_allowed, _ = limiter.check_rate_limit(
                user_id=123, request_type="test", limit=5, window=10
            )
            assert is_allowed is True

    def test_block_when_limit_exceeded(self):
        """Test that requests are blocked when limit is exceeded."""
        limiter = RateLimiter()

        # Make 5 requests (hitting the limit)
        for _ in range(5):
            is_allowed, _ = limiter.check_rate_limit(
                user_id=123, request_type="test", limit=5, window=10
            )
            assert is_allowed is True

        # 6th request should be blocked
        is_allowed, retry_after = limiter.check_rate_limit(
            user_id=123, request_type="test", limit=5, window=10
        )
        assert is_allowed is False
        assert retry_after > 0

    def test_different_users_independent(self):
        """Test that rate limits are independent per user."""
        limiter = RateLimiter()

        # User 1 hits limit
        for _ in range(5):
            limiter.check_rate_limit(user_id=1, request_type="test", limit=5, window=10)

        is_allowed_user1, _ = limiter.check_rate_limit(
            user_id=1, request_type="test", limit=5, window=10
        )
        assert is_allowed_user1 is False

        # User 2 should still be allowed
        is_allowed_user2, _ = limiter.check_rate_limit(
            user_id=2, request_type="test", limit=5, window=10
        )
        assert is_allowed_user2 is True

    def test_different_request_types_independent(self):
        """Test that different request types have independent limits."""
        limiter = RateLimiter()

        # Hit limit for "inline" requests
        for _ in range(5):
            limiter.check_rate_limit(
                user_id=123, request_type="inline", limit=5, window=10
            )

        is_allowed_inline, _ = limiter.check_rate_limit(
            user_id=123, request_type="inline", limit=5, window=10
        )
        assert is_allowed_inline is False

        # "command" requests should still be allowed
        is_allowed_command, _ = limiter.check_rate_limit(
            user_id=123, request_type="command", limit=5, window=10
        )
        assert is_allowed_command is True

    def test_sliding_window(self):
        """Test that sliding window works correctly."""
        limiter = RateLimiter()

        # Make 5 requests
        for _ in range(5):
            limiter.check_rate_limit(
                user_id=123, request_type="test", limit=5, window=1
            )

        # Should be blocked immediately
        is_allowed, _ = limiter.check_rate_limit(
            user_id=123, request_type="test", limit=5, window=1
        )
        assert is_allowed is False

        # Wait for window to pass
        time.sleep(1.1)

        # Should be allowed again
        is_allowed, _ = limiter.check_rate_limit(
            user_id=123, request_type="test", limit=5, window=1
        )
        assert is_allowed is True

    def test_cleanup_old_data(self):
        """Test that old data is cleaned up."""
        limiter = RateLimiter()
        limiter._cleanup_interval = 0  # Force cleanup on every check

        # Make some requests
        limiter.check_rate_limit(user_id=123, request_type="test", limit=5, window=10)

        # Simulate time passing
        time.sleep(0.1)

        # Trigger cleanup by making another request
        limiter.check_rate_limit(user_id=456, request_type="test", limit=5, window=10)

        # Old data should still be present (within 30 second cleanup window)
        assert len(limiter._requests) == 2


class TestRateLimitMiddleware:
    """Test the RateLimitMiddleware class."""

    @pytest.fixture
    def middleware(self):
        """Create a middleware instance."""
        return RateLimitMiddleware()

    @pytest.fixture
    def mock_handler(self):
        """Create a mock handler."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_allow_message_within_limit(self, middleware, mock_handler):
        """Test that messages within rate limit are allowed."""
        message = MagicMock(spec=Message)
        message.from_user = User(id=123, is_bot=False, first_name="Test")
        message.answer = AsyncMock()

        data = {"event_update": None}

        await middleware(mock_handler, message, data)

        # Handler should be called
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_message_exceeding_limit(self, middleware, mock_handler):
        """Test that messages exceeding rate limit are blocked."""
        message = MagicMock(spec=Message)
        message.from_user = User(id=123, is_bot=False, first_name="Test")
        message.answer = AsyncMock()

        data = {"event_update": None}

        # Make requests up to the limit
        for _ in range(RateLimitConfig.COMMAND_LIMIT):
            await middleware(mock_handler, message, data)

        # Next request should be blocked
        mock_handler.reset_mock()
        await middleware(mock_handler, message, data)

        # Handler should NOT be called
        mock_handler.assert_not_called()
        # User should receive rate limit message
        message.answer.assert_called_once()
        assert "too quickly" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_allow_inline_query_within_limit(self, middleware, mock_handler):
        """Test that inline queries within rate limit are allowed."""
        inline_query = MagicMock(spec=InlineQuery)
        inline_query.from_user = User(id=123, is_bot=False, first_name="Test")
        inline_query.answer = AsyncMock()

        data = {"event_update": None}

        await middleware(mock_handler, inline_query, data)

        # Handler should be called
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_inline_query_exceeding_limit(self, middleware, mock_handler):
        """Test that inline queries exceeding rate limit are blocked."""
        inline_query = MagicMock(spec=InlineQuery)
        inline_query.from_user = User(id=123, is_bot=False, first_name="Test")
        inline_query.answer = AsyncMock()

        data = {"event_update": None}

        # Make requests up to the limit
        for _ in range(RateLimitConfig.INLINE_LIMIT):
            await middleware(mock_handler, inline_query, data)

        # Next request should be blocked
        mock_handler.reset_mock()
        await middleware(mock_handler, inline_query, data)

        # Handler should NOT be called
        mock_handler.assert_not_called()
        # User should receive rate limit response
        inline_query.answer.assert_called_once()
        call_kwargs = inline_query.answer.call_args[1]
        assert call_kwargs.get("button") is not None
        assert "Too many requests" in call_kwargs["button"].text

    @pytest.mark.asyncio
    async def test_allow_callback_query_within_limit(self, middleware, mock_handler):
        """Test that callback queries within rate limit are allowed."""
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = User(id=123, is_bot=False, first_name="Test")
        callback.answer = AsyncMock()

        data = {"event_update": None}

        await middleware(mock_handler, callback, data)

        # Handler should be called
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_callback_query_exceeding_limit(self, middleware, mock_handler):
        """Test that callback queries exceeding rate limit are blocked."""
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = User(id=123, is_bot=False, first_name="Test")
        callback.answer = AsyncMock()

        data = {"event_update": None}

        # Make requests up to the limit
        for _ in range(RateLimitConfig.CALLBACK_LIMIT):
            await middleware(mock_handler, callback, data)

        # Next request should be blocked
        mock_handler.reset_mock()
        await middleware(mock_handler, callback, data)

        # Handler should NOT be called
        mock_handler.assert_not_called()
        # User should receive rate limit alert
        callback.answer.assert_called_once()
        call_args = callback.answer.call_args[0]
        assert "slow down" in call_args[0].lower()

    @pytest.mark.asyncio
    async def test_different_users_independent_limits(self, middleware, mock_handler):
        """Test that rate limits are independent between users."""
        user1_message = MagicMock(spec=Message)
        user1_message.from_user = User(id=1, is_bot=False, first_name="User1")
        user1_message.answer = AsyncMock()

        user2_message = MagicMock(spec=Message)
        user2_message.from_user = User(id=2, is_bot=False, first_name="User2")
        user2_message.answer = AsyncMock()

        data = {"event_update": None}

        # User 1 hits limit
        for _ in range(RateLimitConfig.COMMAND_LIMIT):
            await middleware(mock_handler, user1_message, data)

        # User 1 should be blocked
        mock_handler.reset_mock()
        await middleware(mock_handler, user1_message, data)
        mock_handler.assert_not_called()

        # User 2 should still be allowed
        mock_handler.reset_mock()
        await middleware(mock_handler, user2_message, data)
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_allow_event_without_user(self, middleware, mock_handler):
        """Test that events without user info are allowed (fail open)."""
        message = MagicMock(spec=Message)
        message.from_user = None  # No user info

        data = {"event_update": None}

        await middleware(mock_handler, message, data)

        # Handler should be called (fail open)
        mock_handler.assert_called_once()
