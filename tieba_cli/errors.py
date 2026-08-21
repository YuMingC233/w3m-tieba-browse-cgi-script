"""Application errors."""


class FetchError(RuntimeError):
    """Raised when w3m cannot retrieve a Tieba page."""


class ThreadNotFoundError(FetchError):
    """Raised only when Tieba explicitly reports that a thread is absent."""
