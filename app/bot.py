from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums.parse_mode import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton as Button,
)
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineQueryResultUnion,
)
from cachetools import TTLCache

from app.config import config
from app.encryption import create_state
from app.inline_results import build_context_result, build_track_result
from app.logger import logger
from app.messages import get_help_message, get_queue_error_message
from app.rate_limit import RateLimitMiddleware
from app.spotify.auth import get_login_url
from app.spotify.errors import (
    SpotifyApiError,
    SpotifyInvalidRefreshTokenError,
    SpotifyTokenRevokedError,
)
from app.spotify.models import Contextable, Track
from app.user_service import (
    UserNotLoggedInError,
    add_track_to_queue,
    get_playback_data,
    logout_user,
)

bot = Bot(
    token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# Register rate limiting middleware
dp.message.middleware(RateLimitMiddleware())
dp.inline_query.middleware(RateLimitMiddleware())
dp.callback_query.middleware(RateLimitMiddleware())

# Cache for inline query results with 3 second TTL
_inline_query_cache: TTLCache[int, tuple[Track | None, Contextable | None]] = TTLCache(
    maxsize=1000, ttl=3
)


@dp.message(Command("help"))
async def help(message: types.Message) -> None:
    user = message.from_user

    if not user:
        logger.error("Received /help command from message with no user")
        return

    bot_info = await bot.get_me()
    state = create_state(str(user.id))
    url = get_login_url(state)

    await message.answer(
        get_help_message(bot_info.username or "botname"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[Button(text="Login with Spotify", url=url)]]
        ),
    )


@dp.message(Command("start"))
async def start(message: types.Message) -> None:
    user = message.from_user

    if not user:
        logger.error("Received /start command from message with no user")
        return

    state = create_state(str(user.id))
    url = get_login_url(state)

    await message.answer(
        "Welcome! Tap the button below to log in with your Spotify account.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[Button(text="Login with Spotify", url=url)]]
        ),
    )


@dp.message(Command("logout"))
async def logout(message: types.Message) -> None:
    user = message.from_user

    if not user:
        logger.error("Received /logout command from message with no user")
        return

    success = await logout_user(user.id)

    if success:
        await message.answer(
            "✅ Successfully logged out! Your Spotify account has been disconnected.\n\n"
            "Use /start to log in again."
        )
    else:
        await message.answer(
            "You are not currently logged in with Spotify.\n\n"
            "Use /start to log in with your Spotify account."
        )


@dp.inline_query()
async def inline_query(query: types.InlineQuery) -> None:
    user = query.from_user

    results: list[InlineQueryResultUnion] = []
    switch_pm_text: str | None = None
    switch_pm_parameter: str | None = None
    track = None
    context = None

    if user.id in _inline_query_cache:
        logger.debug("Cache hit for inline query from user %d", user.id)
        track, context = _inline_query_cache[user.id]
    else:
        try:
            track, context = await get_playback_data(user.id)
            # Cache the result
            _inline_query_cache[user.id] = (track, context)
        except (
            UserNotLoggedInError,
            SpotifyInvalidRefreshTokenError,
            SpotifyTokenRevokedError,
        ):
            logger.warning(
                "user %d needs to login/re-authenticate with Spotify", user.id
            )
            switch_pm_text = "Login with Spotify"
            switch_pm_parameter = "login"

    if track:
        results.append(build_track_result(track))
        if context:
            results.append(build_context_result(context))
    elif not switch_pm_text:
        logger.warning("no track found for user %d", user.id)

    try:
        await query.answer(
            results=results,
            cache_time=0,
            switch_pm_text=switch_pm_text,
            switch_pm_parameter=switch_pm_parameter,
        )
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            logger.debug("inline query %s expired before response", query.id)
        else:
            raise


# Handle callback queries that starts with "queue;"
@dp.callback_query(F.data.startswith("queue;"))
async def queue_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id

    if not callback.data:
        logger.error("Received callback query without data")
        return

    track_id = callback.data.split(";", 1)[1]

    try:
        await add_track_to_queue(user_id, track_id)
        await callback.answer("Added to your queue!")

    except UserNotLoggedInError:
        await callback.answer("Please log in with Spotify first!", show_alert=True)

    except (SpotifyInvalidRefreshTokenError, SpotifyTokenRevokedError):
        logger.warning("user %d needs to re-authenticate with Spotify", user_id)
        await callback.answer(
            "Your Spotify session expired. Please log in again.", show_alert=True
        )

    except SpotifyApiError as e:
        logger.warning("Spotify API error for user %d: %s", user_id, e.message)
        await callback.answer(get_queue_error_message(e), show_alert=True)

    except Exception as e:
        logger.error(
            "Unexpected error adding to queue for user %d: %s", user_id, str(e)
        )
        await callback.answer("An error occurred. Please try again.", show_alert=True)
