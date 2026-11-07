"""Generate Senior GP standings from a configuration snapshot.

`generate` is the single calculation path. It reads tournaments through the
supplied sources and returns the standings and workbooks in memory. It never
edits the configuration or writes files. `publication` commits the result.
It leaves out a tournament it cannot read and records a warning. Any other
failure raises `GenerationError` and produces no result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .rating_fetcher.processor import classify_members, merge_duplicate_members
from .results_processor.models import TournamentNotFinishedError
from .results_processor.processor import (
    GROUP_TABLE_URL, TOURNAMENT_URL, group_ids, has_been_played, member_results,
)
from .rilton_processor.excel_parser import ExcelParser
from .rilton_processor.pooling import Section, match_members, members_by_fide, pool_sections
from .rilton_processor.tunx_results import UnsupportedSectionError, section_rows
from .standings_generator.exceptions import TournamentDataError
from .standings_generator.excel_exporter import ExcelExporter
from .standings_generator.models import PlayerDetails, PlayerStanding
from .standings_generator.processor import DM_PLACES, GP_PLACES, StandingsProcessor
from .tunx import ParseError, parse

from .configuration import DM, ActiveConfiguration, Tournament, by_date_of_play, validate_configuration


class GenerationError(RuntimeError):
    """Raised when generation stops. `stage` names the failed input or step."""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(f"{stage}: {message}")


@dataclass(frozen=True)
class Membership:
    """
    District members for one season.

    `january` is the 1 January rating list as fetched. `joined` holds members
    on the district list at generation time who are absent from `january`. They
    compete as class E.
    """
    january: tuple[Mapping[str, Any], ...]
    joined: tuple[Mapping[str, Any], ...] = ()


class MemberSystem(Protocol):
    def tournament(self, tournament_id: str) -> dict: ...
    def group_table(self, group_id: int) -> list[dict]: ...


class RiltonSections(Protocol):
    def rows(self, section: Tournament, season: int) -> list[dict]:
        """Return every player row of the section, with FIDE ID and tie-break columns."""


@dataclass(frozen=True)
class GenerationResult:
    """
    The standings and the workbooks built from them, keyed by filename.

    `skipped` lists tournaments that have not started. `warnings` names each
    tournament left out because it could not be read, with the reason.
    """
    season: int
    generated_on: date
    configuration_revision: int
    standings: Mapping[str, Mapping[int, PlayerStanding]]
    workbooks: Mapping[str, bytes]
    included: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def check_generatable(configuration: ActiveConfiguration) -> None:
    """Raise GenerationError when the configuration is invalid or has no tournaments."""
    try:
        validate_configuration(configuration)
    except ValueError as error:
        raise GenerationError("configuration", str(error)) from error
    if not configuration.tournaments:
        raise GenerationError("configuration", f"season {configuration.season} has no tournaments")


def generate(
    configuration: ActiveConfiguration,
    membership: Membership,
    member_system: MemberSystem,
    rilton: RiltonSections,
    *,
    today: date,
) -> GenerationResult:
    """
    Calculate standings and render both workbooks.

    `today` decides which tournaments have been played and dates the workbook
    names. Generation leaves out a tournament that has not started. It also
    leaves out, with a warning, a tournament that cannot be fetched or has a
    malformed result row. An unreadable Rilton section leaves out the whole
    pooled Rilton event, because the remaining sections would rank players
    against an incomplete field. A section that has not finished or needs an
    operator decision raises GenerationError, as does every other problem.
    """
    check_generatable(configuration)
    season = configuration.season

    january = _stage("membership", lambda: classify_members(merge_duplicate_members(list(membership.january))))
    if not january:
        raise GenerationError("membership", f"the 1 January {season} rating list is empty")
    member_classes = {member["id"]: member["klass"] for member in january}
    for member in membership.joined:
        member_classes.setdefault(int(member["id"]), "E")

    standings = StandingsProcessor(season)
    included, skipped, warnings = [], [], []

    def leave_out(stage: str, error: Exception) -> None:
        warnings.append(f"{stage}: left out: {error}")

    # Each event to count: (start date or None, numeric ID, its configured tournaments, how to add it, stage label).
    events = []
    sections = by_date_of_play(configuration.rilton_sections)
    if sections:
        members = members_by_fide(january, list(membership.joined))
        try:
            pooled = [Section(section.name, match_members(rilton.rows(section, season), members),
                              section.rating_floor) for section in sections]
        except (TournamentNotFinishedError, UnsupportedSectionError) as error:
            raise GenerationError("Rilton", str(error)) from error
        except Exception as error:
            leave_out("Rilton", error)
        else:
            pooled_records = _stage("Rilton pooling", lambda: pool_sections(pooled))
            # The pooled event takes the date of its earliest section.
            events.append((sections[0].start_date, min(int(section.id) for section in sections), sections,
                           lambda: standings.add_rilton(pooled_records), "Rilton"))

    for tournament in configuration.member_tournaments:
        stage = f"tournament {tournament.id} ({tournament.name})"
        try:
            details = member_system.tournament(tournament.id)
            if not has_been_played(details, today):
                skipped.append(tournament.key)
                continue
            records = member_results([member_system.group_table(group_id) for group_id in group_ids(details)],
                                     member_classes)
        except TournamentNotFinishedError as error:
            raise GenerationError(stage, str(error)) from error
        except Exception as error:
            leave_out(stage, error)
            continue
        places = DM_PLACES if tournament.scoring == DM else GP_PLACES
        events.append((date.fromisoformat(details['start']), int(tournament.id), (tournament,),
                       lambda tournament=tournament, records=records, places=places:
                       standings.add_member_event(tournament.id, records, places), stage))

    # Count events by date of play, then ID; an undated event comes last. The first event supplies a player's name.
    for _, _, tournaments, add, stage in sorted(events, key=lambda event: (event[0] is None, event[0] or date.min,
                                                                           event[1])):
        try:
            add()
        except TournamentDataError as error:
            leave_out(stage, error)
            continue
        included += [tournament.key for tournament in tournaments]
    _stage("calculation", standings.calculate_final_standings)

    by_key = {tournament.key: tournament for tournament in configuration.tournaments}
    used = [by_key[key] for key in included]
    players = _player_details(standings.player_standings, january, membership)
    workbooks = _stage("export", lambda: ExcelExporter(standings.player_standings, season, used, players).render(today))
    return GenerationResult(season, today, configuration.revision, standings.player_standings,
                            workbooks, tuple(included), tuple(skipped), tuple(warnings))


def _player_details(standings: Mapping[str, Mapping[int, PlayerStanding]],
                    january: list[dict], membership: Membership) -> list[PlayerDetails]:
    """Use January identity and rating, retaining all clubs listed for duplicate memberships.

    Later joiners get identity from their membership record, but no January club or rating.
    """
    january_by_id = {int(member['id']): member for member in january}
    joined_by_id = {int(member['id']): member for member in membership.joined}
    clubs: dict[int, set[str]] = {}
    for member in membership.january:
        if member.get('club'):
            clubs.setdefault(int(member['id']), set()).add(member['club'])
    players = []
    for group in standings.values():
        for player in group.values():
            member_id = player.contender_id
            member = january_by_id.get(member_id, joined_by_id.get(member_id, {}))
            name = ' '.join(str(member.get(part) or '').strip() for part in ('firstName', 'lastName')).strip()
            rating = None
            if member_id in january_by_id:
                rating = (member.get('elo') or {}).get('rating') or 0
            players.append(PlayerDetails(
                member.get('fideid') or None, member_id, name or player.name,
                '; '.join(sorted(clubs.get(member_id, ()), key=str.casefold)), rating,
            ))
    return players


def _stage(stage: str, action: Callable[[], Any]) -> Any:
    """Run one step and report any failure under the stage name."""
    try:
        return action()
    except GenerationError:
        raise
    except Exception as error:
        raise GenerationError(stage, str(error)) from error


class MemberSystemClient:
    """
    Read tournaments and group tables from the member-system API.

    `http` sends each GET. `service.run_generation` passes `inputs.RetainedHttp`,
    which retains responses and follows the upstream retry policy.
    """

    def __init__(self, http: Any) -> None:
        self.http = http

    def tournament(self, tournament_id: str) -> dict:
        return self._get(TOURNAMENT_URL.format(tournament_id))

    def group_table(self, group_id: int) -> list[dict]:
        return self._get(GROUP_TABLE_URL.format(group_id))

    def _get(self, url: str) -> Any:
        response = self.http.get(url)
        response.raise_for_status()
        return response.json()


class TunxRiltonSections:
    """
    Read retained TUNX files, one file per section ID.

    `failures` holds the error of each section that could not be retrieved.
    Reading that section raises it.
    """

    def __init__(self, files: Mapping[str, Path], failures: Mapping[str, Exception] | None = None) -> None:
        self.files = dict(files)
        self.failures = dict(failures or {})

    def rows(self, section: Tournament, season: int) -> list[dict]:
        if section.id in self.failures:
            raise self.failures[section.id]
        if section.id not in self.files:
            raise FileNotFoundError(f"no TUNX file is configured for section {section.id}")
        label = f"section {section.id} ({section.name})"
        try:
            tournament = parse(self.files[section.id].read_bytes())
        except ParseError as error:
            raise ParseError(f"{label}: {error}") from error
        if not tournament.finished:
            raise TournamentNotFinishedError(
                f"{label} has not finished: round {tournament.current_round} of {tournament.total_rounds}"
            )
        return section_rows(tournament, label, season)


class XlsRiltonSections:
    """Read retained chess-results XLS exports, one file per section ID, for comparison with TUNX."""

    def __init__(self, files: Mapping[str, Path]) -> None:
        self.files = dict(files)

    def rows(self, section: Tournament, season: int) -> list[dict]:
        if section.id not in self.files:
            raise FileNotFoundError(f"no XLS file is configured for section {section.id}")
        return ExcelParser({}, season).read_rows(str(self.files[section.id]))
