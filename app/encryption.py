"""Cryptography utilities for encrypting sensitive data."""

import time

from cryptography.fernet import Fernet

from .config import config

fern = Fernet(config.APP_SECRET.encode())

# State token expiration time in seconds (10 minutes)
STATE_EXPIRATION_SECONDS = 600


class StateExpiredError(Exception):
    """Raised when a state parameter has expired."""


def encrypt(plaintext: str) -> str:
    return fern.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return fern.decrypt(ciphertext.encode()).decode()


def create_state(user_id: str) -> str:
    timestamp = int(time.time())
    payload = f"{user_id}:{timestamp}"
    return encrypt(payload)


def validate_state(state: str) -> str:
    """Validate and extract user ID from state parameter.

    Args:
        state: The encrypted state string from OAuth callback

    Returns:
        The user ID extracted from the state

    Raises:
        StateExpiredError: If the state has expired (older than 10 minutes)
        ValueError: If the state format is invalid
    """
    try:
        payload = decrypt(state)
    except Exception as e:
        raise ValueError(f"Invalid state parameter: {e}") from e

    parts = payload.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Invalid state format")

    user_id, timestamp_str = parts

    try:
        timestamp = int(timestamp_str)
    except ValueError as e:
        raise ValueError("Invalid timestamp in state") from e

    current_time = int(time.time())
    age = current_time - timestamp

    if age > STATE_EXPIRATION_SECONDS:
        raise StateExpiredError(
            f"State expired (age: {age}s, max: {STATE_EXPIRATION_SECONDS}s)"
        )

    if age < 0:
        raise ValueError("State timestamp is in the future")

    return user_id
