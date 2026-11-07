"""Parse Swiss-Manager TUNX files. See README.md for provenance and changes."""

from .parse import parse
from .types import ParseError, Tournament

__all__ = ["ParseError", "Tournament", "parse"]
