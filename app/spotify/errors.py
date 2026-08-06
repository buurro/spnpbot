class SpotifyTokenError(Exception):
    """Base exception for Spotify token-related errors."""


class SpotifyTokenExpiredError(SpotifyTokenError): ...


class SpotifyInvalidRefreshTokenError(SpotifyTokenError):
    """Raised when a refresh token is rejected (expired, revoked, malformed).

    Spotify reports all of these as invalid_grant; the user must log in again.
    """


class SpotifyAuthError(Exception):
    """Raised when Spotify OAuth authentication or token exchange fails."""


class SpotifyApiError(Exception):
    """Raised when Spotify API returns an error response.

    Attributes:
        message: Human-readable error message
        status_code: HTTP status code from the API response (if available)
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)
