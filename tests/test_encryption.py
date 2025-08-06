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


def test_validate_state_invalid_format() -> None:
    """Test state validation fails for invalid format."""
    # State without colon separator
    invalid_state = encrypt("12345")

    with pytest.raises(ValueError) as exc_info:
        validate_state(invalid_state)

    assert "format" in str(exc_info.value).lower()


def test_validate_state_invalid_timestamp() -> None:
    """Test state validation fails for non-numeric timestamp."""
    invalid_state = encrypt("12345:not_a_number")

    with pytest.raises(ValueError) as exc_info:
        validate_state(invalid_state)

    assert "timestamp" in str(exc_info.value).lower()


def test_validate_state_invalid_encryption() -> None:
    """Test state validation fails for invalid encrypted data."""
    invalid_state = "not_encrypted_data"

    with pytest.raises(ValueError) as exc_info:
        validate_state(invalid_state)

    assert "invalid" in str(exc_info.value).lower()


def test_validate_state_just_before_expiration() -> None:
    """Test state is valid just before expiration."""
    user_id = "12345"

    # Create state that's almost expired (5 seconds before limit)
    almost_expired_timestamp = int(time.time()) - STATE_EXPIRATION_SECONDS + 5
    payload = f"{user_id}:{almost_expired_timestamp}"
    almost_expired_state = encrypt(payload)

    # Should still be valid
    result = validate_state(almost_expired_state)
    assert result == user_id


def test_validate_state_just_after_expiration() -> None:
    """Test state is invalid just after expiration."""
    user_id = "12345"

    # Create state that's just expired (1 second past limit)
    expired_timestamp = int(time.time()) - STATE_EXPIRATION_SECONDS - 1
    payload = f"{user_id}:{expired_timestamp}"
    expired_state = encrypt(payload)

    # Should raise StateExpiredError
    with pytest.raises(StateExpiredError):
        validate_state(expired_state)


def test_state_preserves_user_id_format() -> None:
    """Test that user IDs with different formats are preserved."""
    test_ids = ["123", "987654321", "user_123", "test@example.com"]

    for user_id in test_ids:
        state = create_state(user_id)
        result = validate_state(state)
        assert result == user_id
