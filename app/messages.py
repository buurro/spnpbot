from textwrap import dedent

from app.spotify.errors import SpotifyApiError


def get_inline_mode_instructions(bot_username: str | None) -> str:
    username = bot_username or "botname"
    return (
        f"Use inline mode to share your currently playing Spotify track! "
        f"Just type @{username} (followed by a space) in any chat."
    )


def get_help_message(bot_username: str) -> str:
    return dedent(
        f"""
        <b>How to use {bot_username}:</b>

        1️⃣ <b>Login with Spotify</b>
        Use the button below to connect your Spotify account.

        2️⃣ <b>Share what you're playing</b>
        Type @{bot_username} (followed by a space) in any chat to share your currently playing track!

        3️⃣ <b>Add tracks to queue</b>
        Others can add the shared track to their queue by tapping the 'Add to queue' button.

        <b>Commands:</b>
        /help - Show this help message
        /logout - Disconnect your Spotify account"
        """
    )


def get_queue_error_message(error: SpotifyApiError) -> str:
    message = error.message.lower()

    if "no active device" in message:
        return "No active device found"
    elif "restricted device" in message or "not supported" in message:
        return "Your device is not supported"
    elif "premium" in message:
        return "This requires Spotify Premium"
    else:
        return "An error occurred"
