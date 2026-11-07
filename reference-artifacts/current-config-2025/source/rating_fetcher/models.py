"""
Data models for the rating fetcher module
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class EloData:
    """Elo rating information"""
    rating: int
    title: str
    date: str
    k: int
    rapidRating: int
    rapidk: int
    blitzRating: int
    blitzK: int


@dataclass
class Player:
    """Player information from the API"""
    id: int
    firstName: str
    lastName: str
    birthdate: str
    sex: int
    fideid: int
    country: str
    club: str
    clubId: int
    elo: EloData
    lask: Optional[Any]
    klass: str  # Added by our processor


class KlassClassifier:
    """Classification logic for player ratings"""
    
    @staticmethod
    def get_klass(rating: int) -> str:
        """
        Determine the klass (class) based on ELO rating
        
        Args:
            rating: ELO rating value
            
        Returns:
            Klass designation (A, B, C, D, or E)
        """
        if rating >= 2200:
            return "A"
        elif rating >= 2000:
            return "B"
        elif rating >= 1800:
            return "C"
        elif rating >= 1600:
            return "D"
        else:
            return "E"