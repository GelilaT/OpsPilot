"""Typed port errors (FR-INT-05). Adapters translate every provider failure into one of these; the job
engine maps them to retry, deferral or failure. Vendor exceptions never reach domain code."""


class PortError(Exception):
    """Base class for all integration failures."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class TransientError(PortError):
    """Temporary failure (timeout, 5xx, connection reset): retry with back-off."""


class RateLimitedError(PortError):
    """Provider quota hit (e.g. Gemini 429): defer without consuming a retry attempt."""

    def __init__(self, message: str, *, retry_after: float = 60.0, provider: str | None = None) -> None:
        super().__init__(message, provider=provider)
        self.retry_after = retry_after


class PermanentError(PortError):
    """The request can never succeed as sent (bad input, unsupported document): fail with a reason."""


class InvalidCredentialsError(PortError):
    """Credentials missing, wrong or revoked: fail and surface on the integration connection."""
