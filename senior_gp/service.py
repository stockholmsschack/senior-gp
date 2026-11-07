"""Run one generation from a configuration snapshot, for the CLI and the web operation alike.

`run_generation` reads the Rilton sections and the rating lists, retaining
what it downloads under `<state>/inputs/`, then calculates and publishes the
standings as a new run of the season.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from .chess_results import RetrievedTunx, fetch_tunx
from .configuration import ActiveConfiguration
from .generation import GenerationError, GenerationResult, MemberSystemClient, check_generatable, generate
from .inputs import HTTP_DIRECTORY, RetainedHttp, fetch_membership, inputs_directory, rilton_sections
from .publication import latest_run, publish, run_date
from .seasons import is_historical

# The stages that `run_generation` reports, in order.
RILTON_STAGE = "rilton"
MEMBERSHIP_STAGE = "membership"
CALCULATION_STAGE = "calculation"
PUBLICATION_STAGE = "publication"
STAGES = (RILTON_STAGE, MEMBERSHIP_STAGE, CALCULATION_STAGE, PUBLICATION_STAGE)


@dataclass(frozen=True)
class GenerationRun:
    """A published result and the directory of its run."""

    result: GenerationResult
    directory: Path


def run_generation(
    configuration: ActiveConfiguration,
    state_directory: Path,
    output_directory: Path,
    *,
    today: date,
    offline: bool = False,
    refresh_rilton: bool = False,
    session: requests.Session | None = None,
    rilton_fetch: Callable[[str], RetrievedTunx] | None = None,
    report_stage: Callable[[str], None] = lambda stage: None,
) -> GenerationRun:
    """Generate the configuration's season at `today` and publish it as the season's latest run.

    `rilton_fetch` downloads a Rilton section, by default from chess-results. `report_stage` receives each stage
    name before the stage starts. A failure publishes nothing and raises GenerationError, RetrievalError for a
    failed `refresh_rilton` download, or OSError when a downloaded section cannot be retained.
    """
    check_generatable(configuration)
    inputs = inputs_directory(state_directory)
    report_stage(RILTON_STAGE)
    rilton = rilton_sections(configuration, inputs, offline=offline, refresh=refresh_rilton,
                             fetch=rilton_fetch or fetch_tunx)
    report_stage(MEMBERSHIP_STAGE)
    http = RetainedHttp(inputs / HTTP_DIRECTORY, offline=offline, session=session)
    try:
        membership = fetch_membership(http, configuration.season, today)
    except Exception as error:
        raise GenerationError("membership", str(error)) from error
    report_stage(CALCULATION_STAGE)
    result = generate(configuration, membership, MemberSystemClient(http), rilton, today=today)
    report_stage(PUBLICATION_STAGE)
    return GenerationRun(result, publish(result, output_directory))


def generation_date(output_directory: Path, season: int, today: date) -> date | None:
    """Return the date to generate the season at when the operator names none.

    That is `today`, or for a historical season the date of its latest run, because today's district list would
    count members who joined after the season. Return None for a historical season without a run. Raise OSError,
    KeyError, TypeError or ValueError when the latest run cannot be read.
    """
    if not is_historical(season, today):
        return today
    run = latest_run(output_directory, season)
    return run_date(run) if run is not None else None
