"""Command-line entry points for validation, Rilton retrieval, and generation.

    senior validate
    senior fetch-rilton TOURNAMENT [--refresh]
    senior generate [--offline] [--date YYYY-MM-DD] [--refresh-rilton]

`--state-dir`, `--output-dir` and `--season` precede the command. The
directories default to `state/` and `output/`. The state directory holds
each season's configuration and the retained inputs. By the date in
Stockholm, the season defaults to last year until 31 May and to this year
from 1 June. Without `--date`, `generate` uses today's Stockholm date. For
a season before last year, it uses the date of the season's latest run
instead, because today's district list would count members who joined
after the season. It refuses such a season when the season has no run.
Command failures exit with status 1. Invalid arguments exit with status 2.
Generation prints the run directory on standard output, and its
progress and warnings on standard error.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys
from typing import Annotated, NoReturn

import typer

from .chess_results import RetrievalError, fetch_tunx, retain, retained_tunx_path, tournament_id
from .configuration import ActiveConfiguration, ConfigurationValidationError, configuration_path, load_configuration
from .generation import GenerationError
from .inputs import inputs_directory
from .seasons import default_season, is_historical, stockholm_today
from .service import generation_date, run_generation

STATE_DIRECTORY = Path("state")
OUTPUT_DIRECTORY = Path("output")
UNCHANGED = "Nothing was published; the earlier standings are unchanged."


@dataclass(frozen=True)
class WorkingDirectories:
    """Filesystem locations shared by CLI commands."""

    state: Path
    output: Path
    season: int


app = typer.Typer(
    help="The Stockholm Senior Grand Prix standings.",
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


@app.callback()
def configure(
    context: typer.Context,
    state_dir: Annotated[
        Path, typer.Option("--state-dir", help="Where the configuration and the retained inputs are kept.")
    ] = STATE_DIRECTORY,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Where each season's runs and latest-run pointer are written.")
    ] = OUTPUT_DIRECTORY,
    season: Annotated[
        int | None,
        typer.Option("--season", help="The season's GP year. By the date in Stockholm, defaults to last year until 31 May "
                             "and to this year from 1 June.",
                     min=1900, max=2100),
    ] = None,
) -> None:
    if season is None:
        season = default_season(stockholm_today())
    context.obj = WorkingDirectories(state_dir, output_dir, season)


@app.command()
def validate(context: typer.Context) -> None:
    """Check the configuration without fetching or writing anything."""
    state, season = context.obj.state, context.obj.season
    configuration = _load_configuration(state, season)
    print(f"The configuration {configuration_path(state, season)} is valid: season {configuration.season}, "
          f"{len(configuration.member_tournaments)} member-system tournaments, "
          f"{len(configuration.rilton_sections)} Rilton sections.")


@app.command(name="fetch-rilton")
def fetch_rilton(
    context: typer.Context,
    tournament: Annotated[
        str, typer.Argument(help="A configured section's chess-results ID or tournament link.", metavar="TOURNAMENT")
    ],
    refresh: Annotated[bool, typer.Option("--refresh", help="Download again although a copy is retained.")] = False,
) -> None:
    """Download and retain the TUNX file of one configured Rilton section.

    The file is retained only after it parses and its name matches the
    tournament page. A failed download keeps the earlier copy.
    """
    identifier = _section_id(tournament)
    state, season = context.obj.state, context.obj.season
    configuration = _load_configuration(state, season)
    if not any(section.id == identifier for section in configuration.rilton_sections):
        _fail(f"Chess-results tournament {identifier} is not a configured Rilton section of season {season}; "
              f"add it to {configuration_path(state, season)} first.")
    inputs = inputs_directory(state)
    path = retained_tunx_path(inputs, identifier)
    if path.exists() and not refresh:
        print("A copy is already retained; use --refresh to download it again.", file=sys.stderr)
    else:
        try:
            retain(fetch_tunx(identifier), inputs)
        except RetrievalError as error:
            _fail(f"Error: {error}")
        except OSError as error:
            _fail(f"Error: cannot save the retained copy: {error}")
    print(path.resolve())


@app.command(name="generate")
def generate_command(
    context: typer.Context,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use only retained inputs and make no network requests.")
    ] = False,
    on: Annotated[
        str | None,
        typer.Option("--date", help="The generation date, YYYY-MM-DD. It decides which events have been played "
                                    "and which district list supplies later members. Defaults to today in "
                                    "Stockholm, or for a season before last year to the date of its latest run. "
                                    "Required for such a season without a run."),
    ] = None,
    refresh_rilton: Annotated[
        bool, typer.Option("--refresh-rilton", help="Download every Rilton section again; a failed download "
                                                    "stops the run and keeps any retained copy of that section.")
    ] = False,
) -> None:
    """Fetch, calculate, and publish the standings as a new run.

    An online run fetches the rating lists and member-system results again
    and downloads each Rilton section that has no retained copy. An offline
    run reads only retained inputs. A member-system tournament that cannot
    be retrieved or read is left out with a warning. A Rilton section that
    cannot be retrieved or read leaves out the whole Rilton event with a
    warning. A failed `--refresh-rilton` download, and any other failure,
    publishes nothing. Without --date, a season before last year generates
    at the date of its latest run.
    """
    if offline and refresh_rilton:
        raise typer.BadParameter("--refresh-rilton needs network access", param_hint="--offline")
    directories = context.obj
    day = _date(on) if on is not None else _generation_date(directories)
    configuration = _load_configuration(directories.state, directories.season)
    try:
        # The calculation modules print progress; keep standard output for the run directory.
        with redirect_stdout(sys.stderr):
            run = run_generation(configuration, directories.state, directories.output, today=day, offline=offline,
                                 refresh_rilton=refresh_rilton)
    except RetrievalError as error:
        _fail(f"Error: {error}\nAny retained copy of that section is unchanged. {UNCHANGED}")
    except GenerationError as error:
        _fail(f"Generation failed at {error}\n{UNCHANGED}")
    except OSError as error:
        _fail(f"Error: cannot save a Rilton section: {error}\n{UNCHANGED}")
    for warning in run.result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print(run.directory.resolve())


def _generation_date(directories: WorkingDirectories) -> date:
    """Return today in Stockholm, or for a historical season the date of its latest run."""
    today = stockholm_today()
    season = directories.season
    try:
        day = generation_date(directories.output, season, today)
    except (OSError, KeyError, TypeError, ValueError) as error:
        _fail(f"Error: cannot read the date of season {season}'s latest run: {error}\n"
              f"Give the date with --date. {UNCHANGED}")
    if day is None:
        raise typer.BadParameter(f"season {season} is older than last year and has no run. Give the date with --date.",
                                 param_hint="--date")
    if is_historical(season, today):
        print(f"Generating season {season}, which is older than last year, at {day.isoformat()}, "
              "the date of its latest run.", file=sys.stderr)
    return day


def _load_configuration(state_directory: Path, season: int) -> ActiveConfiguration:
    try:
        return load_configuration(state_directory, season)
    except ConfigurationValidationError as error:
        _fail(f"The configuration {configuration_path(state_directory, season)} cannot be used:", error.problems)


def _section_id(value: str) -> str:
    value = value.strip()
    if value.isascii() and value.isdigit() and int(value) > 0:
        return str(int(value))
    try:
        return tournament_id(value)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="TOURNAMENT") from error


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{value!r} is not a YYYY-MM-DD date", param_hint="--date") from error


def _fail(message: str, problems=()) -> NoReturn:
    print(message, *(f"  - {problem}" for problem in problems), sep="\n", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    """Run the packaged command-line application."""
    app(prog_name="senior")


if __name__ == "__main__":
    main()
