"""Custom exception classes for the application."""


class ForecastingAPIException(Exception):
    """Base exception for all API errors."""
    pass


class DatabaseConnectionError(ForecastingAPIException):
    """Raised when database connection fails."""
    pass


class ValidationError(ForecastingAPIException):
    """Raised when input validation fails."""
    pass


class ResourceNotFoundError(ForecastingAPIException):
    """Raised when requested resource doesn't exist."""
    pass


class UnauthorizedError(ForecastingAPIException):
    """Raised when authentication fails."""
    pass


class ForecastingError(ForecastingAPIException):
    """Raised when forecasting operation fails."""
    pass


class AdjustmentError(ForecastingAPIException):
    """Raised when adjustment operation fails."""
    pass


class AlertError(ForecastingAPIException):
    """Raised when alert operation fails."""
    pass
