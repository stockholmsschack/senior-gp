"""List each season's generated files for Available files and Reports.

The host's file server serves `<output>/runs/` below `FILES_PUBLIC_ORIGIN`, at
both `/downloads/` and `/reports/`. Available files lists standings
workbooks, and Reports lists validation workbooks. A listing skips
hidden directories, such as staging, directories under `runs/` whose names
are not years, and symlinks. It also skips any file whose name lacks the
run's season or a valid UTC time suffix, such as `20261025T120000Z`, and
dates each file by that suffix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from urllib.parse import quote

from ..publication import FILE_TIME_FORMAT, RUNS_DIRECTORY, latest_run
from ..seasons import STOCKHOLM

DOWNLOADS = "downloads"
REPORTS = "reports"

# Each category's files in display order: a filename pattern, with `{season}` for the run's season, and a label key.
_FILE_TYPES = {
    DOWNLOADS: (
        ("{season}-gp-standings", ".xlsx", "files.names.standings_workbook"),
    ),
    REPORTS: (
        ("{season}-gp-standings-validations", ".xlsx", "files.names.validation_workbook"),
    ),
}


@dataclass(frozen=True)
class GeneratedFile:
    """One listed file. `generated_at` is the Stockholm time of its suffix. `latest` marks the season's latest run."""

    season: int
    run_id: str
    label_key: str
    generated_at: datetime
    url: str
    latest: bool


def list_files(output_directory: Path, public_origin: str, category: str) -> tuple[GeneratedFile, ...]:
    """Return the category's files of every season, newest season first, then newest run first."""
    runs = Path(output_directory) / RUNS_DIRECTORY
    files = []
    for season_directory in _directories(runs):
        if not (season_directory.name.isascii() and season_directory.name.isdigit()):
            continue
        season = int(season_directory.name)
        latest = _latest_run_id(output_directory, season)
        patterns = [(re.compile(rf"{re.escape(stem.format(season=season))}-(\d{{8}}T\d{{6}}Z){re.escape(suffix)}"),
                     label_key) for stem, suffix, label_key in _FILE_TYPES[category]]
        for run_directory in _directories(season_directory):
            names = [path.name for path in _regular_files(run_directory)]
            for order, (pattern, label_key) in enumerate(patterns):
                for match in filter(None, map(pattern.fullmatch, names)):
                    name = match.string
                    generated_at = _file_time(match.group(1))
                    if generated_at is None:
                        continue
                    url = "/".join((public_origin.rstrip("/"), category, str(season),
                                    quote(run_directory.name, safe=""), quote(name, safe="")))
                    files.append((order, GeneratedFile(season, run_directory.name, label_key, generated_at,
                                                       url, run_directory.name == latest)))
    files.sort(key=lambda item: (-item[1].season, -item[1].generated_at.timestamp(), item[0]))
    return tuple(file for _order, file in files)


def _directories(directory: Path) -> list[Path]:
    """Return the visible, real subdirectories, or none when the directory cannot be read."""
    try:
        return [path for path in directory.iterdir()
                if not path.name.startswith(".") and path.is_dir() and not path.is_symlink()]
    except OSError:
        return []


def _regular_files(directory: Path) -> list[Path]:
    try:
        return [path for path in directory.iterdir() if path.is_file() and not path.is_symlink()]
    except OSError:
        return []


def _file_time(suffix: str) -> datetime | None:
    """Return the Stockholm time of a UTC time suffix, or None for an impossible time such as month 13."""
    try:
        return datetime.strptime(suffix, FILE_TIME_FORMAT).replace(tzinfo=UTC).astimezone(STOCKHOLM)
    except ValueError:
        return None


def _latest_run_id(output_directory: Path, season: int) -> str | None:
    try:
        run = latest_run(output_directory, season)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return run.name if run is not None else None
