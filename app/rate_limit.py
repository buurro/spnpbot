"""Rate limiting middleware for aiogram bot handlers.

Implements a sliding window rate limiter to prevent user abuse while allowing
legitimate usage patterns. Different rate limits are applied based on update type.
"""

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, Message, TelegramObject


class RateLimitConfig:
    """Rate limit configuration for different handler types."""

    # Commands: /start, /help, /logout
    COMMAND_LIMIT = 30  # requests
    COMMAND_WINDOW = 30  # seconds

    # Inline queries: @bot in any chat
    INLINE_LIMIT = 20  # requests
    INLINE_WINDOW = 10  # seconds

    # Callback queries: button clicks (queue track)
    CALLBACK_LIMIT = 5  # requests
    CALLBACK_WINDOW = 10  # seconds


class RateLimiter:
    """Sliding window rate limiter using in-memory storage.

    Tracks request timestamps per user and enforces rate limits
    based on configurable time windows.
    """

    def __init__(self) -> None:
        # Store timestamps: {(user_id, request_type): [timestamp1, timestamp2, ...]}
        self._requests: dict[tuple[int, str], list[float]] = defaultdict(list)
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # Clean up old data every 60 seconds

    def _cleanup_old_data(self) -> None:
        """Remove old timestamps to prevent memory growth."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        # Remove entries older than the longest window (30 seconds)
        cutoff = now - 30
        for key in list(self._requests.keys()):
            self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]
            # Remove empty lists
            if not self._requests[key]:
                del self._requests[key]

        self._last_cleanup = now

    def check_rate_limit(
        self, user_id: int, request_type: str, limit: int, window: float
    ) -> tuple[bool, float]:
        """Check if request is within rate limit.

        Args:
            user_id: Telegram user ID
            request_type: Type of request (command, inline, callback)
            limit: Maximum number of requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
            - is_allowed: True if request should be allowed
            - retry_after_seconds: Time to wait before retrying (0 if allowed)
        """
        now = time.time()
        key = (user_id, request_type)

        # Clean up old data periodically
        self._cleanup_old_data()

        # Get timestamps within the current window
        cutoff = now - window
        recent_requests = [ts for ts in self._requests[key] if ts > cutoff]

        if len(recent_requests) >= limit:
            # Rate limit exceeded
            oldest_in_window = min(recent_requests)
            retry_after = oldest_in_window + window - now
            return False, max(0, retry_after)

        # Allow request and record timestamp
        recent_requests.append(now)
        self._requests[key] = recent_requests
        return True, 0.0


class RateLimitMiddleware(BaseMiddleware):
    """Middleware to enforce rate limits on bot handlers.

    Applies different rate limits based on update type:
    - Commands: Low frequency (5 per 30 seconds)
    - Inline queries: Medium frequency (10 per 5 seconds)
    - Callback queries: Medium frequency (5 per 10 seconds)
    """

    def __init__(self) -> None:
        """Initialize middleware with its own rate limiter instance."""
        super().__init__()
        self._rate_limiter = RateLimiter()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401 - Middleware must match aiogram's BaseMiddleware signature
        """Process event with rate limiting."""
        # Extract user and determine request type
        match event:
            case Message():
                user_id = event.from_user.id if event.from_user else None
                request_type = "command"
                limit = RateLimitConfig.COMMAND_LIMIT
                window = RateLimitConfig.COMMAND_WINDOW
            case InlineQuery():
                user_id = event.from_user.id
                request_type = "inline"
                limit = RateLimitConfig.INLINE_LIMIT
                window = RateLimitConfig.INLINE_WINDOW
            case CallbackQuery():
                user_id = event.from_user.id if event.from_user else None
                request_type = "callback"
                limit = RateLimitConfig.CALLBACK_LIMIT
                window = RateLimitConfig.CALLBACK_WINDOW
            case _:
                # Unknown event type, allow the request
                return await handler(event, data)

        # If we can't identify the user, allow the request
        if user_id is None:
            return await handler(event, data)

        # Check rate limit
        is_allowed, retry_after = self._rate_limiter.check_rate_limit(
            user_id, request_type, limit, window
        )

        if not is_allowed:
            # Rate limit exceeded - send user-friendly message
            await self._handle_rate_limit_exceeded(event, retry_after)
            return None  # Stop handler execution

        # Allow request to proceed
        return await handler(event, data)

    async def _handle_rate_limit_exceeded(
        self, event: TelegramObject, retry_after: float
    ) -> None:
        """Send user-friendly message when rate limit is exceeded."""
        retry_seconds = int(retry_after) + 1

        match event:
            case InlineQuery():
                # For inline queries, show a "switch to PM" message
                await event.answer(
                    results=[],
                    cache_time=1,
                    switch_pm_text=f"⏱️ Too many requests, wait {retry_seconds}s",
                    switch_pm_parameter="rate_limit",
                )
            case CallbackQuery():
                # For callback queries, show an alert
                await event.answer(
                    f"⏱️ Please slow down. Try again in {retry_seconds} seconds.",
                    show_alert=True,
                )
            case Message():
                # For commands, send a message
                await event.answer(
                    f"⏱️ You're sending commands too quickly. "
                    f"Please wait {retry_seconds} seconds and try again."
                )
            case _:
                pass
