"""Fetch generation inputs and retain them under `<state>/inputs/` for offline replay.

`RetainedHttp` stores each member-system response as `http/<sha256 of URL>.body`
beside a `.json` provenance file, the layout of the reference capture. An online
run fetches every response again and replaces the retained copy. An offline run
reads only retained copies and raises MissingInputError for any other URL.

Rilton sections are retained as `rilton/<chess-results ID>.TUNX`. The operator
adds a section only after it finishes, so an online run downloads a section
only when no copy is retained, or when the operator asks for a refresh.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import requests

from .rating_fetcher.api_client import RatingAPIClient

from .atomic_write import atomic_replace_bytes, atomic_replace_text
from .chess_results import RetrievalError, RetrievedTunx, fetch_tunx, retain, retained_tunx_path
from .configuration import ActiveConfiguration
from .generation import Membership, TunxRiltonSections
from .upstream import Sleep, send

INPUTS_DIRECTORY = "inputs"
HTTP_DIRECTORY = "http"


class MissingInputError(LookupError):
    """Raised offline for an input that has never been retained."""


def inputs_directory(state_directory: Path) -> Path:
    return Path(state_directory) / INPUTS_DIRECTORY


class RetainedHttp:
    """
    Record or replay JSON GET responses for tournament and membership clients.

    Online requests follow the `upstream` retry policy. A failed request or
    invalid JSON leaves the retained copy unchanged. Offline requests read
    retained responses without accessing the network.
    """

    def __init__(self, directory: Path, *, offline: bool, session: requests.Session | None = None,
                 sleep: Sleep = time.sleep) -> None:
        self.directory = Path(directory)
        self.offline = offline
        self.session = session or requests.Session()
        self.sleep = sleep

    def get(self, url: str) -> RetainedResponse:
        body = self.directory / f"{hashlib.sha256(url.encode()).hexdigest()}.body"
        if self.offline:
            if not body.exists():
                raise MissingInputError(f"no retained response for {url}")
            return RetainedResponse(body.read_bytes())

        response = send(self.session, "GET", url, sleep=self.sleep)
        response.raise_for_status()
        content = response.content
        json.loads(content)  # Retain only a JSON body
        atomic_replace_bytes(body, content)
        atomic_replace_text(body.with_suffix(".json"), json.dumps({
            "url": url,
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(content).hexdigest(),
        }, indent=2) + "\n")
        return RetainedResponse(content)


class RetainedResponse:
    """The parts of `requests.Response` that the clients use."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return json.loads(self.content)


def fetch_membership(http: RetainedHttp, season: int, today: date) -> Membership:
    """
    Return the 1 January rating list and the members who joined later.

    A member on today's district list but absent from the January list counts
    as joined. Either list failing stops generation, because both decide who
    is eligible.
    """
    january = _rating_list(http, date(season, 1, 1))
    january_ids = {str(member["id"]) for member in january if member.get("id") is not None}
    joined = {}
    for member in _rating_list(http, today):
        member_id = member.get("id")
        if member_id is not None and str(member_id) not in january_ids:
            joined[str(member_id)] = {
                "id": member_id,
                "fideid": member.get("fideid"),
                "firstName": member.get("firstName", ""),
                "lastName": member.get("lastName", ""),
            }
    return Membership(tuple(january), tuple(joined[member_id] for member_id in sorted(joined)))


def _rating_list(http: RetainedHttp, day: date) -> list[dict]:
    url = f"{RatingAPIClient.BASE_URL}/{day.isoformat()}/ratingtype/1/category/0"
    response = http.get(url)
    response.raise_for_status()
    members = response.json()
    if not isinstance(members, list):
        raise ValueError(f"the {day.isoformat()} rating list is not a list")
    return members


def rilton_sections(configuration: ActiveConfiguration, inputs: Path, *, offline: bool, refresh: bool = False,
                    fetch: Callable[[str], RetrievedTunx] = fetch_tunx) -> TunxRiltonSections:
    """
    Return the retained TUNX file of every configured Rilton section.

    Online, download each section that has no retained copy. A section that
    cannot be downloaded, or offline has no retained copy, is recorded as
    unreadable, so generation leaves out the Rilton event with a warning.
    With `refresh`, download every section again. A failed refresh raises
    RetrievalError and keeps any earlier copy of that section.
    """
    files, failures = {}, {}
    for section in configuration.rilton_sections:
        path = retained_tunx_path(inputs, section.id)
        files[section.id] = path
        if offline:
            if not path.exists():
                failures[section.id] = MissingInputError(
                    f"no retained TUNX file for Rilton section {section.id} ({section.name})")
        elif refresh:
            retain(fetch(section.id), inputs)
        elif not path.exists():
            try:
                retain(fetch(section.id), inputs)
            except RetrievalError as error:
                failures[section.id] = error
    return TunxRiltonSections(files, failures)
