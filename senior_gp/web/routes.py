"""Senior's pages and JSON API routes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import threading
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, render_template, request


from ..chess_results import (
    RetrievalError,
    RetrievedTunx,
    retain,
    retained_provenance,
    tournament_id as chess_results_id,
    tournament_url,
)
from ..configuration import (
    GP,
    MEMBER_SYSTEM,
    RILTON,
    SCORING_TYPES,
    ActiveConfiguration,
    ConfigurationValidationError,
    StaleConfigurationError,
    Tournament,
    by_date_of_play,
    load_configuration,
    save_configuration,
    stored_seasons,
)
from ..generation import GenerationError, check_generatable
from ..inputs import inputs_directory
from ..member_system import MemberSystemDiscovery, MemberTournament, SearchHit, TournamentNotFound, suggested_scoring
from ..seasons import default_season, season_choices, starts_in_season, stockholm_today
from ..service import generation_date

from .errors import json_error, register_error_handlers
from .files import DOWNLOADS, REPORTS, list_files
from .localization import register_localization
from .operations import GenerationBusyError, GenerationOperationManager


pages = Blueprint("senior", __name__, template_folder="templates", static_folder="static")
register_localization(pages)
register_error_handlers(pages)

# Serializes saves in this process, so two saves of one revision cannot both pass the revision check.
_SAVE_LOCK = threading.Lock()


def _senior() -> dict[str, Any]:
    return current_app.extensions["senior"]


@pages.before_request
def _protect_mutations():
    """Let the host's `MUTATION_PROTECTION`, when supplied, reject any Senior request other than GET, HEAD or OPTIONS."""
    protect = _senior()["settings"].get("MUTATION_PROTECTION")
    if protect and request.method not in ("GET", "HEAD", "OPTIONS") and not protect():
        abort(403)


@pages.context_processor
def _base_template() -> dict[str, str]:
    return {"senior_base_template": _senior()["settings"]["BASE_TEMPLATE"]}


def _state_directory() -> Path:
    return Path(_senior()["settings"]["STATE_DIRECTORY"])


def _actor() -> Any:
    """Return the host's `ACTOR` value for the signed-in user, or `None` without one."""
    actor = _senior()["settings"].get("ACTOR")
    return actor() if actor else None


def _generation_operations() -> GenerationOperationManager:
    return _senior()["generation_operations"]


def _member_system() -> MemberSystemDiscovery:
    return _senior()["member_system"]


def _fetch_rilton(identifier: str) -> RetrievedTunx:
    return _senior()["rilton_fetch"](identifier)


def _season_selection() -> tuple[int | None, tuple[int, ...]]:
    """Return the season named by the `season` query, or the default season, and the selectable seasons.

    The season is None when the query names anything other than one of the choices.
    """
    settings = _senior()["settings"]
    today = stockholm_today(settings["CLOCK"])
    choices = season_choices(today, development=bool(settings["DEVELOPMENT"]))
    requested = request.args.get("season")
    if requested is None:
        return default_season(today), choices
    if not requested.isascii() or not requested.isdigit() or int(requested) not in choices:
        return None, choices
    return int(requested), choices


def _configuration_state(season: int) -> tuple[ActiveConfiguration | None, tuple[str, ...] | None]:
    """Return the season's configuration, or the problems that prevent loading it.

    A season without a file has neither.
    """
    try:
        if season not in stored_seasons(_state_directory()):
            return None, None
        return load_configuration(_state_directory(), season), None
    except ConfigurationValidationError as error:
        return None, tuple(error.problems)


@pages.get("/")
def landing():
    season, season_choices = _season_selection()
    if season is None:
        abort(404)
    configuration, configuration_problems = _configuration_state(season)
    return render_template(
        "senior/landing.jinja2",
        season=season,
        season_choices=season_choices,
        configuration=configuration,
        configuration_problems=configuration_problems,
        tournaments=_entries(configuration) if configuration else [],
        rilton_edition=_edition(season),
        mercure_hub=_mercure_hub(),
    )


@pages.get("/downloads")
def available_files():
    return _file_page(DOWNLOADS, "files.title", "files.empty")


@pages.get("/reports")
def reports():
    return _file_page(REPORTS, "reports.title", "reports.empty")


def _file_page(category: str, title_key: str, empty_key: str):
    settings = _senior()["settings"]
    files = list_files(settings["OUTPUT_DIRECTORY"], settings["FILES_PUBLIC_ORIGIN"], category)
    return render_template(
        "senior/files.jinja2",
        title_key=title_key,
        empty_key=empty_key,
        files=files,
        # Only Available files offers Clear, as in JGP, once per listed season.
        clear_seasons=sorted({file.season for file in files}, reverse=True) if category == DOWNLOADS else [],
    )


def _mercure_hub() -> str:
    """Return the hub URL for the browser, or an empty string without both a publisher and a public URL."""
    settings = _senior()["settings"]
    if settings.get("MERCURE_PUBLISHER") is None:
        return ""
    return settings.get("MERCURE_PUBLIC_URL", "")


def _entries(configuration: ActiveConfiguration) -> list[dict[str, Any]]:
    """Return the season's tournaments as the picker shows them, ordered by date of play, with their suggested
    scoring."""
    entries = []
    tournaments = [
        replace(tournament, start_date=_missing_start_date(tournament, configuration.season))
        if tournament.start_date is None else tournament
        for tournament in configuration.tournaments
    ]
    for tournament in by_date_of_play(tournaments):
        rilton = tournament.source == RILTON
        entries.append({
            "source": tournament.source,
            "tournament_id": int(tournament.id),
            "name": tournament.name,
            "scoring": tournament.scoring,
            "suggested_scoring": GP if rilton else suggested_scoring(tournament.name),
            "rating_floor": tournament.rating_floor,
            "start_date": tournament.start_date.isoformat() if tournament.start_date else None,
        })
    return entries


def _invalid_input(message_key: str, field: str):
    return json_error("invalid_input", message_key, 400, details={"field": field})


def _search_results(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Group the matching groups by tournament, highest tournament ID first, keeping the member system's group order."""
    grouped: dict[int, list[SearchHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.tournament_id, []).append(hit)
    return [
        {
            "tournament_id": tournament_id,
            "name": matches[0].tournament_name,
            "matching_groups": [
                {"group_id": hit.group_id, "name": hit.group_name, "latest_updated_game": hit.latest_updated_game}
                for hit in matches
            ],
        }
        for tournament_id, matches in sorted(grouped.items(), reverse=True)
    ]


@pages.get("/api/v1/tournaments/search")
def tournament_search():
    query = request.args.get("q", "").strip()
    if not query:
        return _invalid_input("errors.tournament_search.invalid_input", "q")
    results = _search_results(_member_system().search(query))
    return jsonify({"data": {"state": "results" if results else "no_matches", "query": query, "tournaments": results}})


def _tournament_in_season(tournament_id: int, season: int) -> tuple[MemberTournament | None, Any]:
    """Look up a member-system tournament. Return it, or the error response when it is unknown or outside the season's window."""
    try:
        tournament = _member_system().tournament(tournament_id)
    except TournamentNotFound:
        return None, json_error("tournament_not_found", "errors.tournament_lookup.not_found", 404,
                                details={"source": MEMBER_SYSTEM, "tournament_id": tournament_id})
    if not starts_in_season(season, tournament.start_date):
        return None, json_error("tournament_outside_season", "errors.tournament_lookup.outside_season", 422, details={
            "source": MEMBER_SYSTEM,
            "tournament_id": tournament.tournament_id,
            "season": season,
            "start_date": tournament.start_date.isoformat(),
        })
    return tournament, None


@pages.get("/api/v1/tournaments/<tournament_id>")
def tournament_lookup(tournament_id: str):
    """Return a member-system tournament with its suggested scoring, if it starts in the season's window."""
    if not tournament_id.isascii() or not tournament_id.isdigit() or tournament_id.startswith("0"):
        return _invalid_input("errors.tournament_lookup.invalid_input", "tournament_id")
    season, _choices = _season_selection()
    if season is None:
        return _invalid_input("errors.season.invalid_input", "season")
    tournament, error = _tournament_in_season(int(tournament_id), season)
    if error:
        return error
    return jsonify({"data": {"tournament": {
        "tournament_id": tournament.tournament_id,
        "name": tournament.name,
        "start_date": tournament.start_date.isoformat(),
        "end_date": tournament.end_date.isoformat(),
        "suggested_scoring": suggested_scoring(tournament.name),
    }}})


# The message for each retrieval stage: the site failed, offered no file, or offered an unusable file.
_RILTON_STAGE_MESSAGES = {
    "download link": "errors.rilton.no_download",
    "validation": "errors.rilton.unsupported_file",
    "identity": "errors.rilton.unsupported_file",
}


def _edition(season: int) -> str:
    """Return the Rilton edition that counts for the season, such as `2025/2026`."""
    return f"{season}/{season + 1}"


@pages.post("/api/v1/rilton/verify")
def verify_rilton():
    """Retrieve, validate and retain a chess-results tournament's TUNX file, and return its identity.

    The tournament must start in the season's window when its page shows a date.
    """
    season, _choices = _season_selection()
    if season is None:
        return _invalid_input("errors.season.invalid_input", "season")
    payload = request.get_json(silent=True)
    url = payload.get("url") if isinstance(payload, dict) else None
    try:
        identifier = chess_results_id(url) if isinstance(url, str) else None
    except ValueError:
        identifier = None
    if identifier is None:
        return _invalid_input("errors.rilton.invalid_url", "url")
    # Read the season first, so that an unreadable season file stops verification before anything is retained.
    _stored_configuration(season)

    try:
        retrieved = _fetch_rilton(identifier)
    except RetrievalError as error:
        current_app.logger.warning("Rilton retrieval: %s", error)
        return json_error("rilton_retrieval_failed",
                          _RILTON_STAGE_MESSAGES.get(error.stage, "errors.rilton.unavailable"), 502,
                          details={"tournament_id": int(identifier), "stage": error.stage, "cause": str(error)})
    if retrieved.start_date and not starts_in_season(season, retrieved.start_date):
        return json_error("tournament_outside_season", "errors.tournament_lookup.outside_season", 422, details={
            "source": RILTON,
            "tournament_id": int(identifier),
            "season": season,
            "start_date": retrieved.start_date.isoformat(),
        })
    try:
        retain(retrieved, inputs_directory(_state_directory()))
    except OSError as error:
        current_app.logger.error("cannot retain Rilton tournament %s: %s", identifier, error)
        return json_error("retention_failed", "errors.rilton.retention_failed", 500,
                          details={"tournament_id": int(identifier)})

    return jsonify({"data": {"tournament": {
        "source": RILTON,
        "tournament_id": int(identifier),
        "name": retrieved.title,
        "url": tournament_url(identifier),
        "start_date": retrieved.start_date.isoformat() if retrieved.start_date else None,
        "end_date": retrieved.end_date.isoformat() if retrieved.end_date else None,
        "edition": _edition(season),
    }}})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_rating_floor(value: Any) -> bool:
    """Return whether `value` is a rating floor: a positive Elo, or None for no floor."""
    return value is None or (_is_int(value) and value > 0)


def _submitted_entry(entry: Any) -> dict[str, Any] | None:
    """Return one submitted tournament as source, ID, scoring and rating floor, or None when it is invalid.

    An entry without `source` is a member-system entry. A Rilton entry always scores as GP.
    """
    if not isinstance(entry, dict):
        return None
    source = entry.get("source", MEMBER_SYSTEM)
    tournament_id, scoring, rating_floor = entry.get("tournament_id"), entry.get("scoring"), entry.get("rating_floor")
    if not _is_int(tournament_id) or tournament_id <= 0:
        return None
    if source == MEMBER_SYSTEM and scoring in SCORING_TYPES and rating_floor is None:
        return {"source": source, "id": tournament_id, "scoring": scoring, "rating_floor": None}
    if source == RILTON and scoring in (None, GP) and _is_rating_floor(rating_floor):
        return {"source": source, "id": tournament_id, "scoring": GP, "rating_floor": rating_floor}
    return None


def _submitted_tournaments(payload: Any) -> tuple[int, list[dict[str, Any]]] | None:
    """Return the submitted revision and tournaments, or None when the body is invalid."""
    if not isinstance(payload, dict):
        return None
    revision, entries = payload.get("revision"), payload.get("tournaments")
    if not _is_int(revision) or revision < 0 or not isinstance(entries, list):
        return None
    tournaments = [_submitted_entry(entry) for entry in entries]
    if None in tournaments:
        return None
    if len({(entry["source"], entry["id"]) for entry in tournaments}) != len(tournaments):
        return None
    return revision, tournaments


def _stored_configuration(season: int) -> ActiveConfiguration:
    """Return the season's configuration, or an empty one at revision 0 when the season has no file."""
    if season not in stored_seasons(_state_directory()):
        return ActiveConfiguration(season)
    return load_configuration(_state_directory(), season)


def _rilton_start_date(provenance: dict) -> date | None:
    """Return the start date that a retained Rilton file's provenance records, or None when it records none."""
    try:
        return date.fromisoformat(provenance["start_date"])
    except (KeyError, TypeError, ValueError):
        return None


def _verified_rilton(tournament_id: int, season: int) -> tuple[tuple[str, date | None] | None, Any]:
    """Return the name and start date of a verified Rilton tournament, or the error response when it is unverified
    or outside the season."""
    provenance = retained_provenance(inputs_directory(_state_directory()), str(tournament_id))
    if provenance is None or not isinstance(provenance.get("title"), str):
        return None, json_error("rilton_not_verified", "errors.rilton.not_verified", 422,
                                details={"source": RILTON, "tournament_id": tournament_id})
    start = provenance.get("start_date")
    start_date = _rilton_start_date(provenance)
    if start_date and not starts_in_season(season, start_date):
        return None, json_error("tournament_outside_season", "errors.tournament_lookup.outside_season", 422, details={
            "source": RILTON,
            "tournament_id": tournament_id,
            "season": season,
            "start_date": start,
        })
    return (provenance["title"], start_date), None


def _new_tournament(entry: dict[str, Any], season: int) -> tuple[tuple[str, date | None] | None, Any]:
    """Return the name and start date of a tournament new to the season, or the error response that refuses it."""
    if entry["source"] == RILTON:
        return _verified_rilton(entry["id"], season)
    tournament, error = _tournament_in_season(entry["id"], season)
    return ((tournament.name, tournament.start_date), None) if tournament else (None, error)


def _missing_start_date(tournament: Tournament, season: int) -> date | None:
    """Return the start date of a stored tournament saved without one, or None when it is still unknown.

    Seasons saved before Senior stored dates have none. A failed member-system lookup leaves the date unknown.
    """
    if tournament.source == RILTON:
        provenance = retained_provenance(inputs_directory(_state_directory()), tournament.id)
        return _rilton_start_date(provenance) if provenance else None
    try:
        found, _error = _tournament_in_season(int(tournament.id), season)
    except Exception as error:
        current_app.logger.warning("cannot read the start date of tournament %s: %s", tournament.id, error)
        return None
    return found.start_date if found else None


@pages.post("/api/v1/configuration/tournaments")
def save_tournaments():
    """Save the season's complete tournament list, ordered by date of play.

    A tournament already in the season keeps its stored name and start date. A new member-system tournament must
    start in the season's window and takes its name and start date from the member system. A new Rilton tournament
    must have been verified, and takes its name and start date from its retained file. A stored tournament without a
    start date gets one when it can be found.
    """
    season, _choices = _season_selection()
    if season is None:
        return _invalid_input("errors.season.invalid_input", "season")
    submission = _submitted_tournaments(request.get_json(silent=True))
    if submission is None:
        return _invalid_input("errors.configuration.invalid_input", "tournaments")
    revision, entries = submission

    stored = _stored_configuration(season)
    if revision != stored.revision:
        # `save_configuration` checks again under the lock. This early check avoids upstream requests for a stale save.
        raise StaleConfigurationError(f"configuration revision {revision} is stale; current revision is "
                                      f"{stored.revision}", current_revision=stored.revision)
    known = {tournament.key: tournament for tournament in stored.tournaments}
    tournaments = []
    for entry in entries:
        key = f"{entry['source']}:{entry['id']}"
        if key in known:
            name, start_date = known[key].name, known[key].start_date
            if start_date is None:
                start_date = _missing_start_date(known[key], season)
        else:
            found, error = _new_tournament(entry, season)
            if error:
                return error
            name, start_date = found
        tournaments.append(Tournament(entry["source"], str(entry["id"]), name, entry["scoring"],
                                      entry["rating_floor"], start_date))
    tournaments = by_date_of_play(tournaments)

    if tuple(tournaments) == stored.tournaments:
        saved, changed = stored, False
    else:
        with _SAVE_LOCK:
            saved, changed = save_configuration(_state_directory(), replace(stored, tournaments=tuple(tournaments))), True
    return jsonify({"data": {
        "revision": saved.revision,
        "tournaments": _entries(saved),
        "changed": changed,
    }})


@pages.post("/api/v1/generation/operations")
def start_generation():
    """Start generating the season's saved configuration in the background.

    The body names the revision that the operator sees. The run captures that revision, the season and the
    generation date, so a later save or a change of season leaves the run unchanged.
    """
    season, _choices = _season_selection()
    if season is None:
        return _invalid_input("errors.season.invalid_input", "season")
    payload = request.get_json(silent=True)
    revision = payload.get("revision") if isinstance(payload, dict) else None
    if not _is_int(revision) or revision < 0:
        return _invalid_input("errors.generation.invalid_input", "revision")
    configuration = _stored_configuration(season)
    if revision != configuration.revision:
        raise StaleConfigurationError(f"configuration revision {revision} is stale; current revision is "
                                      f"{configuration.revision}", current_revision=configuration.revision)
    try:
        check_generatable(configuration)
    except GenerationError as error:
        return json_error("not_generatable", "errors.generation.no_tournaments", 422,
                          details={"season": season, "cause": str(error)})
    today = stockholm_today(_senior()["settings"]["CLOCK"])
    try:
        day = generation_date(_senior()["settings"]["OUTPUT_DIRECTORY"], season, today)
    except (OSError, KeyError, TypeError, ValueError) as error:
        current_app.logger.error("cannot read the date of season %s's latest run: %s", season, error)
        day = None
    if day is None:
        return json_error("generation_date_unknown", "errors.generation.date_unknown", 422, details={"season": season})
    try:
        operation = _generation_operations().start(configuration, day, actor=_actor())
    except GenerationBusyError as error:
        return json_error("generation_busy", "errors.generation.busy", 409,
                          details={"operation_id": error.operation_id, "operation": _running_operation(error.operation_id)})
    except Exception:
        current_app.logger.exception("cannot start a generation of season %s", season)
        return json_error("generation_start_failed", "errors.generation.start_failed", 500)
    return jsonify({"data": operation.as_dict()}), 202


@pages.post("/api/v1/downloads/clear")
def clear_downloads():
    """Remove the generated files of the `season` query's season, as JGP's Clear downloads does for all its files.

    The configuration, retained inputs and operation records stay.
    """
    requested = request.args.get("season", "")
    if not (requested.isascii() and requested.isdigit() and len(requested) == 4):
        return _invalid_input("errors.season.invalid_input", "season")
    try:
        _generation_operations().clear_season(int(requested))
    except GenerationBusyError as error:
        return json_error("downloads_busy", "errors.downloads.busy", 409,
                          details={"active_operation_id": error.operation_id})
    except Exception:
        current_app.logger.exception("cannot clear the downloads of season %s", requested)
        return json_error("downloads_clear_failed", "errors.downloads.clear_failed", 500)
    return jsonify({"data": {"season": int(requested), "cleared": True}})


def _running_operation(operation_id: str) -> dict[str, Any] | None:
    """Return the operation's recorded state, or None when its record cannot be read."""
    try:
        return _generation_operations().store.load(operation_id).as_dict()
    except FileNotFoundError:
        return None


@pages.get("/api/v1/generation/operations/<operation_id>")
def generation_operation(operation_id: str):
    """Return an operation's recorded state, which survives a restart."""
    try:
        operation = _generation_operations().store.load(operation_id)
    except FileNotFoundError:
        return json_error("operation_not_found", "errors.generation.operation_not_found", 404)
    return jsonify({"data": operation.as_dict()})
