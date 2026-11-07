"""
Data models for results processor.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class ProcessedResult:
    """Represents a processed tournament result."""
    contenderId: int
    name: str
    points: float
    secPoints: float
    klass: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'contenderId': self.contenderId,
            'name': self.name,
            'points': self.points,
            'secPoints': self.secPoints,
            'klass': self.klass
        }


@dataclass
class TournamentInfo:
    """Represents tournament information from API."""
    id: int
    name: str
    start: str
    end: str
    state: int
    root_classes: List[Dict[str, Any]]
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'TournamentInfo':
        return cls(
            id=data['id'],
            name=data['name'],
            start=data['start'],
            end=data['end'],
            state=data['state'],
            root_classes=data.get('rootClasses', [])
        )


@dataclass
class MemberInfo:
    """Represents member information."""
    id: int
    klass: str
    
    
class ResultsProcessorError(Exception):
    """Base exception for results processor errors."""
    pass


class TournamentFetchError(ResultsProcessorError):
    """Raised when tournament data cannot be fetched."""
    pass


class MemberDataError(ResultsProcessorError):
    """Raised when member data cannot be loaded."""
    pass
