class DataError(ValueError):
    """A problem with the user's data or request that should be shown to them (HTTP 400/413/422)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
