"""
Data models and type definitions for the Rilton Tournament Processor Module
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class PlayerRating:
    """Represents a player's rating data from the JSON file"""
    fideid: int
    id: Optional[str]
    firstName: str
    lastName: str
    elo_rating: int
    klass: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlayerRating':
        """Create PlayerRating from dictionary data"""
        return cls(
            fideid=data.get('fideid', 0),
            id=data.get('id'),
            firstName=data.get('firstName', ''),
            lastName=data.get('lastName', ''),
            elo_rating=(data.get('elo') or {}).get('rating') or 0,
            klass=data.get('klass', 'E'),
        )


@dataclass
class TournamentResult:
    """Represents a player's tournament result"""
    fideid: int
    id: Optional[str]
    rank: int
    firstName: str
    lastName: str
    elo_rating: int
    klass: str
    tournament_data: Dict[str, Any]


# Type aliases for better readability
RatingsData = Dict[int, Dict[str, Any]]
ProcessedData = List[Dict[str, Any]]
FileValidationResult = tuple[str, str, str]  # (u1800_file, u2200_file, ratings_file)
