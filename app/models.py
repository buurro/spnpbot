from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, event
from sqlmodel import Field, SQLModel

from app.encryption import decrypt, encrypt


class User(SQLModel, table=True):
    telegram_id: int = Field(primary_key=True, sa_type=BigInteger)

    spotify_access_token: str
    spotify_refresh_token: str
    spotify_expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    created_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime | None = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc)
        ),
    )


def _is_encrypted(value: str) -> bool:
    """
    Check if a value is already Fernet-encrypted.

    Fernet tokens are base64-encoded and typically start with 'gAAAAA'.
    We also check for a minimum length to avoid false positives.
    """
    if not value or len(value) < 40:
        return False

    # Fernet tokens start with version (0x80) which encodes to 'gA' in base64
    # and include a timestamp, totaling to 'gAAAAA' prefix typically
    return value.startswith("gA") and all(
        c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_"
        for c in value
    )


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def encrypt_tokens(mapper: object, connection: object, target: User) -> None:
    if not _is_encrypted(target.spotify_access_token):
        target.spotify_access_token = encrypt(target.spotify_access_token)

    if not _is_encrypted(target.spotify_refresh_token):
        target.spotify_refresh_token = encrypt(target.spotify_refresh_token)


@event.listens_for(User, "load")
def decrypt_tokens_and_fix_timezone(target: User, context: object) -> None:
    # Only decrypt if tokens are encrypted (loaded from DB)
    # New objects in memory won't be encrypted yet
    if _is_encrypted(target.spotify_access_token):
        target.spotify_access_token = decrypt(target.spotify_access_token)

    if _is_encrypted(target.spotify_refresh_token):
        target.spotify_refresh_token = decrypt(target.spotify_refresh_token)

    # Ensure all datetime fields are treated as UTC (SQLite doesn't preserve timezone)
    if target.spotify_expires_at and target.spotify_expires_at.tzinfo is None:
        target.spotify_expires_at = target.spotify_expires_at.replace(
            tzinfo=timezone.utc
        )

    if target.created_at and target.created_at.tzinfo is None:
        target.created_at = target.created_at.replace(tzinfo=timezone.utc)

    if target.updated_at and target.updated_at.tzinfo is None:
        target.updated_at = target.updated_at.replace(tzinfo=timezone.utc)
