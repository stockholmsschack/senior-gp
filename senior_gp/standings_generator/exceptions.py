"""
Custom exceptions for the standings generator module.
"""


class StandingsGeneratorError(Exception):
    """Base exception for standings generator errors."""
    pass


class TournamentDataError(StandingsGeneratorError):
    """Raised when tournament data is invalid or corrupted."""
    pass


class ConfigurationError(StandingsGeneratorError):
    """Raised when configuration files are missing or invalid."""
    pass