"""Search the member system for tournaments and look one up by ID, for the tournament picker.

Requests follow the `upstream` retry policy, with a new HTTP session for each
request because a `requests.Session` is not safe to share between threads.
A tournament the member system does not know raises `TournamentNotFound`.
Every other failure, including a response without the expected fields,
raises `MemberSystemUnavailable`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
import time
from typing import Any
from urllib.parse import quote

import requests

from .configuration import DM, GP
from .seasons import STOCKHOLM
from .upstream import Sleep, UpstreamRetryExhausted, send

BASE_URL = "https://member.schack.se/public/api/v1"
DM_NAME = "Stockholmsmästerskapet"


class MemberSystemUnavailable(RuntimeError):
    """Raised when the member system fails or answers without the expected fields."""


class TournamentNotFound(RuntimeError):
    """Raised when the member system answers 404 for a tournament ID."""


@dataclass(frozen=True)
class SearchHit:
    """One tournament group that the member system matches to the search text."""

    tournament_id: int
    tournament_name: str
    group_id: int
    group_name: str
    latest_updated_game: str | None


@dataclass(frozen=True)
class MemberTournament:
    """A tournament's ID, name and dates."""

    tournament_id: int
    name: str
    start_date: date
    end_date: date


def suggested_scoring(name: str) -> str:
    """Suggest DM for a name containing `Stockholmsmästerskapet`, and GP otherwise."""
    return DM if DM_NAME in name else GP


class MemberSystemDiscovery:
    """Read search results and tournaments from the member-system API."""

    def __init__(self, new_session: Callable[[], requests.Session] = requests.Session,
                 sleep: Sleep = time.sleep) -> None:
        self.new_session = new_session
        self.sleep = sleep

    def search(self, text: str) -> list[SearchHit]:
        rows = self._get(f"/tournament/group/search/{quote(text, safe='')}")
        if not isinstance(rows, list):
            raise MemberSystemUnavailable("the search response is not a list")
        return [
            SearchHit(
                tournament_id=_positive_int(row, "tournamentid"),
                tournament_name=_text(row, "tournamentname"),
                group_id=_positive_int(row, "id"),
                group_name=_text(row, "name"),
                latest_updated_game=_optional_text(row, "latestUpdatedGame"),
            )
            for row in rows
        ]

    def tournament(self, tournament_id: int) -> MemberTournament:
        data = self._get(f"/tournament/tournament/id/{tournament_id}", not_found=TournamentNotFound)
        if _positive_int(data, "id") != tournament_id:
            raise MemberSystemUnavailable(f"the response for tournament {tournament_id} names another tournament")
        start_date, end_date = _date(data, "start"), _date(data, "end")
        if end_date < start_date:
            raise MemberSystemUnavailable(f"tournament {tournament_id} ends before it starts")
        return MemberTournament(tournament_id, _text(data, "name"), start_date, end_date)

    def _get(self, path: str, *, not_found: type[Exception] = MemberSystemUnavailable) -> Any:
        url = f"{BASE_URL}{path}"
        try:
            with self.new_session() as session:
                response = send(session, "GET", url, sleep=self.sleep)
        except UpstreamRetryExhausted as error:
            raise MemberSystemUnavailable(f"{url}: {error}") from error
        if response.status_code == 404:
            raise not_found(url)
        if not 200 <= response.status_code <= 299:
            raise MemberSystemUnavailable(f"{url}: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise MemberSystemUnavailable(f"{url}: the response is not JSON") from error


def _field(data: Any, key: str) -> Any:
    if not isinstance(data, Mapping) or key not in data:
        raise MemberSystemUnavailable(f"a response has no {key!r} field")
    return data[key]


def _positive_int(data: Any, key: str) -> int:
    value = _field(data, key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MemberSystemUnavailable(f"{key!r} is not a positive integer")
    return value


def _text(data: Any, key: str) -> str:
    value = _field(data, key)
    if not isinstance(value, str) or not value.strip():
        raise MemberSystemUnavailable(f"{key!r} is not a non-empty string")
    return value.strip()


def _optional_text(data: Mapping[str, Any], key: str) -> str | None:
    if data.get(key) in (None, ""):
        return None
    return _text(data, key)


def _date(data: Any, key: str) -> date:
    """Read an ISO date, or the Stockholm date of an ISO date-time. A date-time without an offset is in Stockholm time."""
    value = _text(data, key)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MemberSystemUnavailable(f"{key!r} is not an ISO date") from error
    return instant.astimezone(STOCKHOLM).date() if instant.utcoffset() is not None else instant.date()
