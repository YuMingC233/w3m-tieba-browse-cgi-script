"""Application errors."""


class FetchError(RuntimeError):
    """Raised when w3m cannot retrieve a Tieba page."""
