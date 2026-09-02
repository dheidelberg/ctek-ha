"""Exceptions raised by the CTEK API client."""


class CtekError(Exception):
    """Base error."""


class CtekConnectionError(CtekError):
    """Network-level failure (DNS, timeout, connection reset)."""


class CtekAuthError(CtekError):
    """Login or token refresh was rejected."""


class CtekApiError(CtekError):
    """The backend answered, but with an error."""

    def __init__(self, status: int, message: str | None = None) -> None:
        self.status = status
        self.message = message or f"HTTP {status}"
        super().__init__(self.message)
