"""Validate and persist each season's `active-configuration.toml`.

Each season has its own file, `<state>/seasons/<year>/active-configuration.toml`,
with its own revision. Loading returns a frozen `ActiveConfiguration`. Saving
validates the whole configuration, checks its revision, and atomically
replaces its season's file with the next revision. A rejected save leaves the
file unchanged. Saving rewrites the TOML and discards comments.

Earlier versions kept one file, `<state>/active-configuration.toml`. The
first load, save or listing moves that file to its season's directory. When
the move fails, the file stays, and every load, save and listing raises
`ConfigurationValidationError` until the operator resolves the problem.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
import json
import os
from pathlib import Path
import tomllib

from .atomic_write import atomic_replace_text

ACTIVE_CONFIGURATION_FILENAME = "active-configuration.toml"
SEASONS_DIRECTORY = "seasons"

MEMBER_SYSTEM = "member"
RILTON = "rilton"
SOURCES = (MEMBER_SYSTEM, RILTON)
GP = "GP"
DM = "DM"
SCORING_TYPES = (GP, DM)

_TOURNAMENT_KEYS = {"source", "id", "name", "scoring", "rating_floor", "start_date"}


class ConfigurationValidationError(ValueError):
    """Raised with every problem found in a configuration."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class StaleConfigurationError(RuntimeError):
    """Raised when a save is based on an older revision than the stored one."""

    def __init__(self, message: str, *, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(message)


@dataclass(frozen=True)
class Tournament:
    """
    One configured tournament.

    `source` decides retrieval and `scoring` decides allocation. `id` is the
    member-system ID or the chess-results ID. `rating_floor` applies only to
    Rilton: a positive Elo below which a player is penalized, or None for no floor.
    `start_date` is the first day of play, as the member system or the
    chess-results page gave it when the tournament was added or at a later
    save, or None while it is unknown.
    """
    source: str
    id: str
    name: str
    scoring: str = GP
    rating_floor: int | None = None
    start_date: date | None = None

    @property
    def key(self) -> str:
        """Return the source-qualified identity, such as `member:5382`."""
        return f"{self.source}:{self.id}"


@dataclass(frozen=True)
class ActiveConfiguration:
    """The season and its tournaments in order of date of play."""
    season: int
    tournaments: tuple[Tournament, ...] = ()
    revision: int = 0

    @property
    def rilton_sections(self) -> tuple[Tournament, ...]:
        return tuple(t for t in self.tournaments if t.source == RILTON)

    @property
    def member_tournaments(self) -> tuple[Tournament, ...]:
        return tuple(t for t in self.tournaments if t.source == MEMBER_SYSTEM)


def configuration_path(state_directory: Path, season: int) -> Path:
    """Return the path of a season's active configuration."""
    return Path(state_directory) / SEASONS_DIRECTORY / str(season) / ACTIVE_CONFIGURATION_FILENAME


def stored_seasons(state_directory: Path) -> tuple[int, ...]:
    """Return the seasons that have a configuration file, newest first."""
    _move_unseasoned_configuration(state_directory)
    seasons = Path(state_directory) / SEASONS_DIRECTORY
    if not seasons.is_dir():
        return ()
    return tuple(sorted(
        (int(path.name) for path in seasons.iterdir()
         if path.name.isascii() and path.name.isdigit() and (path / ACTIVE_CONFIGURATION_FILENAME).is_file()),
        reverse=True,
    ))


def load_configuration(state_directory: Path, season: int) -> ActiveConfiguration:
    """Load and validate a season's configuration, reporting every problem at once."""
    _move_unseasoned_configuration(state_directory)
    path = configuration_path(state_directory, season)
    if not path.exists():
        raise ConfigurationValidationError((f"season {season} has no configuration yet",))
    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationValidationError((f"cannot read active configuration: {error}",)) from error

    configuration, problems = _configuration_from_document(data)
    problems += _configuration_problems(configuration)
    if configuration.season != season:
        problems.append(f"the file for season {season} names season {configuration.season!r}")
    if problems:
        raise ConfigurationValidationError(problems)
    return configuration


def save_configuration(state_directory: Path, configuration: ActiveConfiguration) -> ActiveConfiguration:
    """
    Validate and atomically save the configuration as its season's next revision.

    The configuration's revision must equal the season's stored revision.
    Revision 0 means that the season has no file yet.
    """
    validate_configuration(configuration)
    _move_unseasoned_configuration(state_directory)
    path = configuration_path(state_directory, configuration.season)
    current_revision = load_configuration(state_directory, configuration.season).revision if path.exists() else 0
    if configuration.revision != current_revision:
        raise StaleConfigurationError(
            f"configuration revision {configuration.revision} is stale; current revision is {current_revision}",
            current_revision=current_revision,
        )
    saved = replace(configuration, revision=current_revision + 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace_text(path, _configuration_document(saved))
    return saved


def _move_unseasoned_configuration(state_directory: Path) -> None:
    """Move a configuration from `<state>/active-configuration.toml` into its season's directory."""
    old_path = Path(state_directory) / ACTIVE_CONFIGURATION_FILENAME
    if not old_path.exists():
        return
    try:
        with old_path.open("rb") as config_file:
            season = tomllib.load(config_file).get("season")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationValidationError((f"cannot read {old_path} to move it to its season: {error}",)) from error
    if not _is_season(season):
        raise ConfigurationValidationError(
            (f"cannot move {old_path} to its season: season must be a four-digit year, not {season!r}",))
    new_path = configuration_path(state_directory, season)
    if new_path.exists():
        raise ConfigurationValidationError(
            (f"cannot move {old_path} to {new_path}, which already exists; remove one of them",))
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old_path, new_path)
    except OSError as error:
        raise ConfigurationValidationError((f"cannot move {old_path} to {new_path}: {error}",)) from error


def validate_configuration(configuration: ActiveConfiguration) -> None:
    """Report all configuration problems in one exception."""
    problems = _configuration_problems(configuration)
    if problems:
        raise ConfigurationValidationError(problems)


def _configuration_problems(configuration: ActiveConfiguration) -> list[str]:
    problems: list[str] = []
    season = configuration.season
    if not _is_season(season):
        problems.append(f"season must be a four-digit year, not {season!r}")
    if not _is_int(configuration.revision) or configuration.revision < 0:
        problems.append("revision must be a non-negative integer")

    keys = set()
    for tournament in configuration.tournaments:
        label = f"tournament {tournament.id!r}"
        if tournament.source not in SOURCES:
            problems.append(f"{label}: source must be one of {', '.join(SOURCES)}")
        if not isinstance(tournament.id, str) or not tournament.id.isascii() or not tournament.id.isdigit():
            problems.append(f"{label}: id must be digits")
        if not isinstance(tournament.name, str) or not tournament.name.strip():
            problems.append(f"{label}: name is required")
        if tournament.scoring not in SCORING_TYPES:
            problems.append(f"{label}: scoring must be one of {', '.join(SCORING_TYPES)}")
        elif tournament.source == RILTON and tournament.scoring != GP:
            problems.append(f"{label}: Rilton always scores as GP")
        if tournament.source != RILTON and tournament.rating_floor is not None:
            problems.append(f"{label}: only Rilton sections have a rating floor")
        elif tournament.rating_floor is not None and not _is_positive_int(tournament.rating_floor):
            problems.append(f"{label}: rating floor must be a positive whole number")
        if tournament.start_date is not None and (
                not isinstance(tournament.start_date, date) or isinstance(tournament.start_date, datetime)):
            problems.append(f"{label}: start_date must be a date")
        if tournament.key in keys:
            problems.append(f"{label}: configured twice")
        keys.add(tournament.key)

    return problems


def _configuration_from_document(data: dict) -> tuple[ActiveConfiguration, list[str]]:
    """Read configuration fields and report unknown or missing ones."""
    problems: list[str] = []
    unknown = sorted(set(data) - {"revision", "season", "tournaments"})
    if unknown:
        problems.append("unknown active configuration fields: " + ", ".join(unknown))

    revision = data.get("revision")
    if not _is_int(revision) or revision < 1:
        problems.append("stored configuration revision must be a positive integer")
        revision = 0

    tournaments = []
    entries = data.get("tournaments", [])
    if not isinstance(entries, list):
        problems.append("tournaments must be an array of tables")
        entries = []
    for position, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            problems.append(f"tournament {position} must be a table")
            continue
        unknown = sorted(set(entry) - _TOURNAMENT_KEYS)
        if unknown:
            problems.append(f"tournament {position}: unknown fields: " + ", ".join(unknown))
        missing = sorted({"source", "id", "name"} - set(entry))
        if missing:
            problems.append(f"tournament {position}: missing fields: " + ", ".join(missing))
            continue
        tournaments.append(Tournament(**{key: value for key, value in entry.items() if key in _TOURNAMENT_KEYS}))

    return ActiveConfiguration(data.get("season"), tuple(tournaments), revision), problems


def _configuration_document(configuration: ActiveConfiguration) -> str:
    lines = [f"revision = {configuration.revision}", f"season = {configuration.season}"]
    for tournament in configuration.tournaments:
        lines += [
            "",
            "[[tournaments]]",
            f"source = {_toml_string(tournament.source)}",
            f"id = {_toml_string(tournament.id)}",
            f"name = {_toml_string(tournament.name)}",
            f"scoring = {_toml_string(tournament.scoring)}",
        ]
        if tournament.rating_floor is not None:
            lines.append(f"rating_floor = {tournament.rating_floor}")
        if tournament.start_date is not None:
            lines.append(f"start_date = {tournament.start_date.isoformat()}")
    return "\n".join(lines) + "\n"


def by_date_of_play(tournaments: Iterable[Tournament]) -> tuple[Tournament, ...]:
    """Return the tournaments ordered by start date. Undated ones follow, and ties keep their order."""
    return tuple(sorted(tournaments, key=lambda tournament: (tournament.start_date is None,
                                                             tournament.start_date or date.min)))


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_int(value) -> bool:
    return _is_int(value) and value > 0


def _is_season(value) -> bool:
    return _is_int(value) and 1900 <= value <= 2100


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
