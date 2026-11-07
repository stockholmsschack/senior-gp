"""
Calculate Rilton section results from a decoded TUNX tournament.

The calculation follows the profile that reproduces the chess-results XLS
exports of Rilton 2024/2025 and 2025/2026:

- `Pts`: the sum of awarded round points.
- `PS`: the sum of the cumulative scores after each round.
- `BH`: the sum of named opponents' final scores, including forfeited games.
  Each round without an opponent adds half the total round count.
- `BH/C1`: `BH` minus the smallest single contribution.

It applies only to sections whose tie-break list equals `RILTON_TIE_BREAKS`.
The parser reads that list, but not the Buchholz parameters, so a section
with the same list and other parameters is not detected.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..tunx import Tournament

from .exceptions import RiltonProcessorError

# Tie-break list of the verified Rilton sections: BH/C1, BH, PS
RILTON_TIE_BREAKS = (37, 37, 8)

_EDITION = re.compile(r"\b(\d{4})/(\d{4})\b")


class UnsupportedSectionError(RiltonProcessorError):
    """Raised when a section needs an operator decision before it can be scored."""


def section_rows(tournament: Tournament, label: str, season: int) -> List[Dict[str, Any]]:
    """
    Return one row per player, with the columns of the chess-results XLS export.

    Rows follow the XLS order: `Pts`, `BH/C1`, `BH` and `PS` descending, then
    starting number. The tournament must be finished.
    """
    check_section(tournament, label, season)
    if not tournament.finished:
        raise ValueError(f"{label}: the tournament has not finished")
    points = {player.pairing_number: sum(result.points for result in player.results)
              for player in tournament.players}
    no_opponent = tournament.total_rounds / 2
    rows = []
    for player in tournament.players:
        results = sorted(player.results, key=lambda result: result.round)
        cumulative = 0.0
        progressive = 0.0
        for result in results:
            cumulative += result.points
            progressive += cumulative
        contributions = [no_opponent if result.opponent is None else points[result.opponent]
                         for result in results]
        buchholz = sum(contributions)
        rows.append({
            "SNo.": player.pairing_number,
            "title": player.title or "",
            "Name": " ".join(part for part in (player.surname, player.first_name, player.academic_title) if part),
            "Rtg": player.rating or 0,
            "FED": player.federation or "",
            "Club": player.club or "",
            "Fide-No.": player.fide_id or 0,
            "Pts": points[player.pairing_number],
            "BH/C1": buchholz - min(contributions),
            "BH": buchholz,
            "PS": progressive,
        })
    rows.sort(key=lambda row: (-row["Pts"], -row["BH/C1"], -row["BH"], -row["PS"], row["SNo."]))
    for rank, row in enumerate(rows, 1):
        row["Rank"] = rank
    return rows


def check_section(tournament: Tournament, label: str, season: int) -> None:
    """Reject a mismatched edition in the title or an unsupported tie-break code list."""
    edition = _EDITION.search(tournament.name)
    if edition and (int(edition.group(1)), int(edition.group(2))) != (season, season + 1):
        raise UnsupportedSectionError(
            f"{label}: '{tournament.name}' is not the {season}/{season + 1} edition"
        )
    if tuple(tournament.tiebreak_codes) != RILTON_TIE_BREAKS:
        raise UnsupportedSectionError(
            f"{label}: unsupported tie-break settings {tournament.tiebreak_codes}; "
            f"the Rilton calculation supports only {list(RILTON_TIE_BREAKS)}"
        )
