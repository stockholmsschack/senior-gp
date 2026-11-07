from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

# "bye" scores one point without an opponent. "unpaired" scores zero without
# an opponent. "double-loss" scores zero for both players of a game.
ResultKind = Literal[
    "bye",
    "double-loss",
    "draw",
    "forfeit-loss",
    "forfeit-win",
    "loss",
    "unpaired",
    "win",
]
Title = Literal["CM", "FM", "GM", "IM", "WCM", "WFM", "WGM", "WIM"]

POINTS: dict[ResultKind, float] = {
    "bye": 1.0,
    "double-loss": 0.0,
    "draw": 0.5,
    "forfeit-loss": 0.0,
    "forfeit-win": 1.0,
    "loss": 0.0,
    "unpaired": 0.0,
    "win": 1.0,
}


class ParseError(ValueError):
    """Raised for malformed input or a result code the parser cannot decode."""

    def __init__(self, message: str, offset: Optional[int] = None):
        self.message = message
        self.offset = offset
        super().__init__(message if offset is None else f"{message} (byte {offset})")


@dataclass(slots=True)
class RawTournament:
    config_bytes: bytes
    header_bytes: bytes
    metadata_strings: list[str]
    pairing_bytes: list[bytes]
    pairings_section: bytes
    player_numeric_bytes: list[bytes]
    player_strings: list[list[str]]


@dataclass(slots=True)
class Arbiter:
    name: str
    role: Literal["arbiter", "chief", "deputy"]
    fide_id: Optional[int] = None


@dataclass(slots=True)
class DateRange:
    start: str
    end: str


@dataclass(slots=True)
class Pairing:
    """One pairing record. `black` is 0 without an opponent. `result` is None until the game has a result."""
    black: int
    board: int
    white: int
    code: int
    result: Optional[ResultKind] = None


@dataclass(slots=True)
class Result:
    """One decided round for one player, scored from the player's side."""
    kind: ResultKind
    round: int
    color: Optional[Literal["black", "white"]] = None
    opponent: Optional[int] = None

    @property
    def points(self) -> float:
        return POINTS[self.kind]


@dataclass(slots=True)
class Player:
    first_name: str
    pairing_number: int
    results: list[Result]
    surname: str
    academic_title: Optional[str] = None
    birth_year: Optional[int] = None
    club: Optional[str] = None
    federation: Optional[str] = None
    fide_id: Optional[int] = None
    group: Optional[str] = None
    national_id: Optional[str] = None
    rating: Optional[int] = None
    sex: Optional[Literal["F", "M"]] = None
    title: Optional[Title] = None


@dataclass(slots=True)
class Round:
    number: int
    pairings: list[Pairing]
    date: Optional[str] = None


@dataclass(slots=True)
class Tournament:
    """
    A parsed tournament.

    `rounds` holds the paired rounds and is shorter than `total_rounds` while
    later rounds are unpaired. `tiebreak_codes` holds the raw Swiss-Manager
    tie-break codes, which this package does not name.
    """
    _raw: RawTournament
    arbiters: list[Arbiter]
    name: str
    players: list[Player]
    rounds: list[Round]
    tiebreak_codes: list[int]
    total_rounds: int
    current_round: int
    city: Optional[str] = None
    dates: Optional[DateRange] = None
    federation: Optional[str] = None
    subtitle: Optional[str] = None
    time_control: Optional[str] = None
    venue: Optional[str] = None

    @property
    def finished(self) -> bool:
        """Return whether every round is paired and every game has a result."""
        return (self.current_round == self.total_rounds == len(self.rounds)
                and all(pairing.result is not None for round_ in self.rounds for pairing in round_.pairings))
