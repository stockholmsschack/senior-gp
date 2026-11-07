"""Commit a complete generation under `<output>/runs/<year>/<run id>/`.

Publication writes every file into a staging directory, renames it into the
season's runs directory, and then atomically points the season's
`<output>/seasons/<year>/latest.json` at the new run. A failure before the
pointer moves leaves the previous run as the season's latest result. Each
season has its own runs and pointer, so a run of one season never replaces
another season's latest result.

The host's file server serves `<output>/runs/`, so a run directory holds only
the files an operator downloads. Every file of a run ends with the UTC time
the run was published, as in `2025-gp-standings-20261025T120000Z.xlsx`.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import shutil
import tempfile

from .atomic_write import atomic_replace_text, fsync_directory
from .configuration import SEASONS_DIRECTORY, ConfigurationValidationError, load_configuration
from .generation import GenerationError, GenerationResult, Membership, MemberSystem, RiltonSections, generate

RUNS_DIRECTORY = "runs"
RUN_ID_FORMAT = "%Y%m%dT%H%M%S%fZ"
FILE_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
LATEST_FILE = "latest.json"
REPORT_PATTERN = "*-gp-report-*.json"


def generate_and_publish(
    state_directory: Path,
    output_directory: Path,
    membership: Membership,
    member_system: MemberSystem,
    rilton: RiltonSections,
    *,
    season: int,
    today: date,
) -> Path:
    """Generate from the season's saved configuration and publish the result as the season's latest run."""
    try:
        configuration = load_configuration(state_directory, season)
    except ConfigurationValidationError as error:
        raise GenerationError("configuration", str(error)) from error
    result = generate(configuration, membership, member_system, rilton, today=today)
    return publish(result, output_directory)


def season_output_directory(output_directory: Path, season: int) -> Path:
    """Return the directory that holds the season's `latest.json`."""
    return Path(output_directory) / SEASONS_DIRECTORY / str(season)


def season_runs_directory(output_directory: Path, season: int) -> Path:
    """Return the directory that holds the season's runs."""
    return Path(output_directory) / RUNS_DIRECTORY / str(season)


def publish(result: GenerationResult, output_directory: Path, *, published_at: datetime | None = None) -> Path:
    """Write the result as one new run of its season, make it the season's latest, and return its directory.

    `published_at`, by default now, names the run and ends each of its filenames.
    """
    published_at = published_at or datetime.now(UTC)
    run_id = published_at.strftime(RUN_ID_FORMAT)
    file_time = published_at.strftime(FILE_TIME_FORMAT)
    files = _run_files(result, file_time)
    season_directory = season_output_directory(output_directory, result.season)
    runs = season_runs_directory(output_directory, result.season)
    run_directory = runs / run_id
    if run_directory.exists():
        raise GenerationError("publication", f"run {run_id} already exists")
    try:
        runs.mkdir(parents=True, exist_ok=True)
        season_directory.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=runs))
    except OSError as error:
        raise GenerationError("publication", str(error)) from error
    try:
        for name, content in files.items():
            with (staging / name).open("wb") as staged:
                staged.write(content)
                staged.flush()
                os.fsync(staged.fileno())
        staging.rename(run_directory)
        staging = None
        fsync_directory(runs)
        atomic_replace_text(season_directory / LATEST_FILE,
                            json.dumps({"run": run_id, "files": sorted(files)}, indent=2) + "\n")
    except OSError as error:
        raise GenerationError("publication", str(error)) from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return run_directory


def latest_run(output_directory: Path, season: int) -> Path | None:
    """Return the directory of the season's latest committed run, or None before its first."""
    season_directory = season_output_directory(output_directory, season)
    latest = season_directory / LATEST_FILE
    if not latest.exists():
        return None
    return season_runs_directory(output_directory, season) / json.loads(latest.read_text())["run"]


def clear_season(output_directory: Path, season: int) -> None:
    """Remove the season's runs and `latest.json`. Other seasons' runs and the state directory stay."""
    runs = season_runs_directory(output_directory, season)
    (season_output_directory(output_directory, season) / LATEST_FILE).unlink(missing_ok=True)
    if runs.is_symlink() or runs.is_file():
        runs.unlink()
    elif runs.is_dir():
        shutil.rmtree(runs)


def run_date(run_directory: Path) -> date:
    """Return the generation date recorded in a run's report. Raise ValueError unless the run holds one report."""
    report, = Path(run_directory).glob(REPORT_PATTERN)
    return date.fromisoformat(json.loads(report.read_text())["generated_on"])


def standings_document(standings) -> str:
    """Serialize standings by class, in the same form as the reference replay."""
    return json.dumps({
        klass: [asdict(player) for player in players.values()] for klass, players in standings.items()
    }, ensure_ascii=False, indent=2) + "\n"


def _run_files(result: GenerationResult, file_time: str) -> dict[str, bytes]:
    """Return the run's files by name: the workbooks, the standings data and the report, each ending in `file_time`.

    A workbook's name loses the generation date that the exporter gives it.
    """
    day = result.generated_on.strftime("%Y%m%d")
    workbooks = {f"{Path(name).stem.removesuffix(f'-{day}')}-{file_time}{Path(name).suffix}": content
                 for name, content in result.workbooks.items()}
    report = json.dumps({
        "season": result.season,
        "generated_on": result.generated_on.isoformat(),
        "configuration_revision": result.configuration_revision,
        "included": list(result.included),
        "skipped_not_started": list(result.skipped),
        "warnings": list(result.warnings),
        "workbooks": sorted(workbooks),
    }, ensure_ascii=False, indent=2) + "\n"
    return {
        **workbooks,
        f"{result.season}-gp-standings-{file_time}.json": standings_document(result.standings).encode(),
        f"{result.season}-gp-report-{file_time}.json": report.encode(),
    }
