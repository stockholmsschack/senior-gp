"""Choose the default season and the seasons an operator may select.

A Senior GP season runs into the following spring: the GP 2025 final was in
May 2026. So until 31 May the default is last year's season, and from 1 June
it is this year's. Dates are Stockholm dates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")
FIRST_MONTH_OF_NEW_SEASON = 6
RETAINED_SEASON_COUNT = 3

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current time in UTC. This is the default clock."""
    return datetime.now(UTC)


def stockholm_today(clock: Clock = utc_now) -> date:
    """Return the Stockholm date of the clock's time, which must include a time zone."""
    instant = clock()
    if instant.utcoffset() is None:
        raise ValueError("the clock must return a time with a time zone")
    return instant.astimezone(STOCKHOLM).date()


def default_season(today: date) -> int:
    """Return last year's season until 31 May and this year's from 1 June."""
    return today.year if today.month >= FIRST_MONTH_OF_NEW_SEASON else today.year - 1


def season_choices(today: date, *, development: bool = False) -> tuple[int, ...]:
    """Return the selectable seasons, newest first: this year, last year, and in development the year before last."""
    count = 3 if development else 2
    return tuple(today.year - offset for offset in range(count))


def is_historical(season: int, today: date) -> bool:
    """Return whether the season is older than last year. No production year choice offers such a season."""
    return season < today.year - 1


def retained_seasons(today: date, stored: Iterable[int]) -> frozenset[int]:
    """Return the seasons whose configuration cleanup must keep.

    Keep this year and the two before it, and the three newest seasons with stored data, so that three seasons
    stay stored before the new season has any.
    """
    retained = {today.year - offset for offset in range(RETAINED_SEASON_COUNT)}
    retained.update(sorted(stored, reverse=True)[:RETAINED_SEASON_COUNT])
    return frozenset(retained)


def starts_in_season(season: int, start: date) -> bool:
    """Return whether a tournament starting on `start` may count for `season`: it starts in that year or the next."""
    return start.year in (season, season + 1)
