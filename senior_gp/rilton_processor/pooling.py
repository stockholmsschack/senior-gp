"""
Pool matched chess-results sections into one Rilton event.

Works on matched records, so TUNX and XLS input follow the same rules.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .exceptions import RiltonProcessorError

# Values the pooled ranking needs for every player.
REQUIRED_RESULT_FIELDS = ("Pts", "BH/C1", "BH", "PS")


@dataclass
class Section:
    """One configured section, its matched member records, and its rating floor or None for no floor."""
    title: str
    records: List[Dict[str, Any]]
    rating_floor: Optional[int] = None


def members_by_fide(january: List[Dict[str, Any]], joined: List[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    """
    Index classified January members, then later joiners, by FIDE ID.

    Joiners are eligible as class E with Elo 0.
    """
    members = {player['fideid']: player for player in january if player.get('fideid')}
    for member in joined:
        fide_id = member.get('fideid')
        if fide_id and fide_id not in members:
            members[fide_id] = {**member, 'elo': {}, 'klass': 'E'}
    return members


def match_members(rows: List[Dict[str, Any]], members: Dict[Any, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the section rows of district members, joined with their rating data."""
    matched = []
    for row in rows:
        fide_id = row.get("Fide-No.")
        member = members.get(fide_id) if fide_id else None
        if member is None:
            continue
        matched.append({
            "fideid": fide_id,
            "contenderId": member.get("id"),
            "rank": row.get("Rank", 0),
            "firstName": member.get("firstName", ""),
            "lastName": member.get("lastName", ""),
            "elo_rating": (member.get("elo") or {}).get("rating") or 0,
            "klass": member.get("klass", ""),
            "tournament_data": row,
        })
    return matched


def is_penalized(elo_rating: int, rating_floor: Optional[int]) -> bool:
    """Return whether January Elo is below the floor. Exactly the floor is not penalized."""
    return rating_floor is not None and elo_rating < rating_floor


def pool_sections(sections: List[Section]) -> List[Dict[str, Any]]:
    """
    Combine sections into one record list with penalties marked.

    Fails on a missing tie-break value or a FIDE ID in more than one section.
    """
    pooled: List[Dict[str, Any]] = []
    seen: Dict[Any, str] = {}
    for section in sections:
        for record in section.records:
            missing = [name for name in REQUIRED_RESULT_FIELDS
                       if record["tournament_data"].get(name) in (None, "")]
            if missing:
                raise RiltonProcessorError(
                    f"Unsupported section '{section.title}': no {', '.join(missing)} "
                    f"for FIDE ID {record['fideid']}; the pooled ranking needs {', '.join(REQUIRED_RESULT_FIELDS)}"
                )
            fide_id = record["fideid"]
            if fide_id in seen:
                raise RiltonProcessorError(
                    f"FIDE ID {fide_id} appears in both '{seen[fide_id]}' and '{section.title}'"
                )
            seen[fide_id] = section.title
            pooled.append({**record, "penalty": is_penalized(record["elo_rating"], section.rating_floor)})
    return pooled
