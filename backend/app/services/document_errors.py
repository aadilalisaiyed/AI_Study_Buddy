class DocumentError(Exception):
    """Safe, client-facing document failure."""

    def __init__(self, message: str, status: int = 503, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
