"""
Custom exceptions for the rating fetcher module
"""


class RatingFetcherError(Exception):
    """Base exception for rating fetcher errors"""
    pass


class APIError(RatingFetcherError):
    """Exception for API-related errors"""
    pass


class ValidationError(RatingFetcherError):
    """Exception for data validation errors"""
    pass


class ProcessingError(RatingFetcherError):
    """Exception for data processing errors"""
    pass