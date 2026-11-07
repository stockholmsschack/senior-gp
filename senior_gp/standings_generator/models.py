"""
Data models for the standings generator.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class PlayerDetails:
    """A standings player's identity and January membership details."""
    fide_id: Optional[int]
    member_id: int
    name: str
    january_club: str
    january_rating: Optional[float]


@dataclass
class TournamentResult:
    """Represents a player's result in a single tournament."""
    contender_id: int
    name: str
    klass: str
    points: float
    tie_break_1: Optional[float] = None
    tie_break_2: Optional[float] = None
    tie_break_3: Optional[float] = None
    rank: Optional[int] = None
    standings_points: int = 0
    penalty: bool = None


@dataclass
class PlayerStanding:
    """Represents a player's overall standing across all tournaments."""
    contender_id: int
    name: str
    klass: str
    tournament_results: Dict[str, TournamentResult]
    total_standings_points: int = 0
    final_rank: Optional[int] = None

    def __post_init__(self):
        """Calculate total standings points after initialization."""
        self.total_standings_points = sum(
            result.standings_points for result in self.tournament_results.values()
        )


@dataclass
class Tournament:
    """Represents tournament metadata."""
    id: str
    name: str
    year: int
    dm: bool = False
