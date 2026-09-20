SERVICE_UNAVAILABLE = 503


class ApplicationException(Exception):
    """Base Exception for this Advisory Application"""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class RedisPubishException(ApplicationException):
    """Generic Exception for Redis Related Services"""

    def __init__(self, message: str = "Failed to publish event to Redis"):
        super().__init__(message, status_code=SERVICE_UNAVAILABLE)
