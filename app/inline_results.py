from uuid import uuid4

from aiogram.enums.parse_mode import ParseMode
from aiogram.types import (
    InlineKeyboardButton as Button,
)
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from aiogram.utils.formatting import Text, TextLink

from app.spotify.models import Album, Contextable, Track


def build_track_result(track: Track) -> InlineQueryResultArticle:
    message_text = (
        "🎵 ",
        TextLink(track.name, url=track.url),
        " by ",
        track.artist.name,
    )

    thumbnail = track.thumbnail

    return InlineQueryResultArticle(
        id=str(uuid4()),
        title=f"{track.artist.name} - {track.name}",
        url=track.url,
        thumbnail_url=thumbnail.url if thumbnail else None,
        thumbnail_width=thumbnail.width if thumbnail else None,
        thumbnail_height=thumbnail.height if thumbnail else None,
        input_message_content=InputTextMessageContent(
            message_text=Text(*message_text).as_html(),
            parse_mode=ParseMode.HTML,
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    Button(text="Open in Spotify", url=track.url),
                    Button(
                        text="Add to queue",
                        callback_data="queue;" + track.id,
                    ),
                ]
            ]
        ),
    )


def build_context_result(context: Contextable) -> InlineQueryResultArticle:
    if isinstance(context, Album):
        title = f"{context.artist.name} - {context.name}"
        message_content = Text(
            "🎧 ",
            TextLink(context.name, url=context.url),
            " by ",
            context.artist.name,
        )
    else:
        title = context.name
        message_content = Text("🎧 ", TextLink(context.name, url=context.url))

    thumbnail = context.thumbnail

    return InlineQueryResultArticle(
        id=str(uuid4()),
        title=title,
        url=context.url,
        description=type(context).__name__,
        thumbnail_url=thumbnail.url if thumbnail else None,
        thumbnail_width=thumbnail.width if thumbnail else None,
        thumbnail_height=thumbnail.height if thumbnail else None,
        input_message_content=InputTextMessageContent(
            message_text=message_content.as_html(),
            parse_mode=ParseMode.HTML,
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    Button(text="Open in Spotify", url=context.url),
                ]
            ]
        ),
    )
