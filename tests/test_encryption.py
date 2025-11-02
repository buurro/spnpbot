"""Tests for encryption and state validation."""

import time

import pytest

from app.encryption import (
    STATE_EXPIRATION_SECONDS,
    StateExpiredError,
    create_state,
    decrypt,
    encrypt,
    validate_state,
)


def test_encrypt_decrypt() -> None:
    """Test basic encryption and decryption."""
    plaintext = "test_user_id"
    ciphertext = encrypt(plaintext)

    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_create_state() -> None:
    """Test state creation includes user ID and timestamp."""
    user_id = "12345"
    state = create_state(user_id)

    # State should be encrypted
    assert state != user_id

    # Should be decodable
    payload = decrypt(state)
    assert user_id in payload
    assert ":" in payload


def test_validate_state_success() -> None:
    """Test successful state validation."""
    user_id = "12345"
    state = create_state(user_id)

    # Should validate successfully and return user_id
    result = validate_state(state)
    assert result == user_id


def test_validate_state_expired() -> None:
    """Test state validation fails for expired state."""
    user_id = "12345"

    # Create a state with old timestamp
    old_timestamp = int(time.time()) - STATE_EXPIRATION_SECONDS - 100
    payload = f"{user_id}:{old_timestamp}"
    old_state = encrypt(payload)

    # Should raise StateExpiredError
    with pytest.raises(StateExpiredError) as exc_info:
        validate_state(old_state)

    assert "expired" in str(exc_info.value).lower()


def test_validate_state_future_timestamp() -> None:
    """Test state validation fails for future timestamp."""
    user_id = "12345"

    # Create a state with future timestamp (1 hour from now)
    future_timestamp = int(time.time()) + 3600
    payload = f"{user_id}:{future_timestamp}"
    future_state = encrypt(payload)

    # Should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        validate_state(future_state)

    assert "future" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("state_payload", "should_encrypt", "error_substring"),
    [
        ("12345", True, "format"),  # No colon separator
        ("12345:not_a_number", True, "timestamp"),  # Non-numeric timestamp
        ("not_encrypted_data", False, "invalid"),  # Not encrypted
    ],
)
def test_validate_state_invalid(
    state_payload: str, should_encrypt: bool, error_substring: str
) -> None:
    """Test state validation fails for various invalid inputs."""
    invalid_state = encrypt(state_payload) if should_encrypt else state_payload

    with pytest.raises(ValueError) as exc_info:
        validate_state(invalid_state)

    assert error_substring in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("offset_seconds", "should_be_valid"),
    [
        (5, True),  # Just before expiration (5 seconds before limit)
        (-1, False),  # Just after expiration (1 second past limit)
    ],
)
def test_validate_state_expiration_boundary(
    offset_seconds: int, should_be_valid: bool
) -> None:
    """Test state validation at expiration boundaries."""
    user_id = "12345"
    timestamp = int(time.time()) - STATE_EXPIRATION_SECONDS + offset_seconds
    payload = f"{user_id}:{timestamp}"
    state = encrypt(payload)

    if should_be_valid:
        result = validate_state(state)
        assert result == user_id
    else:
        with pytest.raises(StateExpiredError):
            validate_state(state)


@pytest.mark.parametrize(
    "user_id",
    ["123", "987654321", "user_123", "test@example.com"],
)
def test_state_preserves_user_id_format(user_id: str) -> None:
    """Test that user IDs with different formats are preserved."""
    state = create_state(user_id)
    result = validate_state(state)
    assert result == user_id
