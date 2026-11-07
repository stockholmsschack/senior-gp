"""Retrieve a tournament's TUNX file from chess-results.com without a browser.

The flow follows `_spec/chess-results-tunx-fetch.md`: the tournament page, an
optional details gate, the full-details page, the gate again after a host
change, and the Swiss-Manager download. Chess-results adds the gate about a
month after a tournament, so a recent one reaches the download without it.
Each retrieval uses its own session, because the download link names no
tournament and is bound to the session.
Every request, redirect, and followed link must stay on a chess-results host.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from .tunx import ParseError, parse
from .tunx.constants import MAGIC

from .atomic_write import atomic_replace_bytes, atomic_replace_text
from .upstream import Sleep, UpstreamRetryExhausted, send

HOST = re.compile(r"(?:s\d+\.)?chess-results\.com", re.IGNORECASE)
TOURNAMENT_PATH = re.compile(r"/tnr(\d+)\.aspx", re.IGNORECASE)
DOWNLOAD_PATH = "/downloadturnier.aspx"
GATE_CONTROL = "cb_alleDetails"
DATE_LABEL = "Date"  # The English label; `tournament_url` asks for English pages
DATES = re.compile(r"(\d{4}/\d{2}/\d{2})(?: to (\d{4}/\d{2}/\d{2}))?")
MAX_BYTES = 5_000_000
MAX_STEPS = 6
MAX_REDIRECTS = 5
RILTON_DIRECTORY = "rilton"


class RetrievalError(RuntimeError):
    """Raised when a TUNX file cannot be retrieved. `stage` names the failed step."""

    def __init__(self, tournament_id: str, stage: str, message: str) -> None:
        self.tournament_id = tournament_id
        self.stage = stage
        super().__init__(f"chess-results tournament {tournament_id}: {stage}: {message}")


@dataclass(frozen=True)
class RetrievedTunx:
    """A validated TUNX file and where it came from, with the dates its pages show, if any."""
    tournament_id: str
    title: str
    content: bytes
    source_url: str
    download_url: str
    filename: str | None
    retrieved_utc: str
    start_date: date | None = None
    end_date: date | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def tournament_id(url: str) -> str:
    """
    Return the tournament ID of a chess-results tournament link.

    Server aliases such as `s3.` and query parameters such as `lan=1` do not
    change the ID, so equivalent links give the same ID.
    """
    parts = urlsplit(url.strip())
    match = TOURNAMENT_PATH.fullmatch(parts.path)
    if parts.scheme != "https" or not HOST.fullmatch(parts.hostname or "") or not match:
        raise ValueError(f"{url!r} is not an https chess-results tournament link such as "
                         "https://chess-results.com/tnr967028.aspx")
    return str(int(match.group(1)))


def tournament_url(identifier: str) -> str:
    return f"https://chess-results.com/tnr{identifier}.aspx?lan=1"


def fetch_tunx(identifier: str, *, session: requests.Session | None = None, max_bytes: int = MAX_BYTES,
               sleep: Sleep = time.sleep) -> RetrievedTunx:
    """
    Download and validate the TUNX file of one tournament.

    The file is accepted only when it parses and its tournament name equals
    the heading of the tournament page. Raises RetrievalError otherwise.
    Requests follow the retry policy in `upstream`.
    """
    client = _Client(identifier, session or requests.Session(), sleep)
    source_url = tournament_url(identifier)
    response = client.request("GET", source_url, "tournament page")
    title = dates = None
    submitted, visited = set(), {source_url.lower()}
    for _ in range(MAX_STEPS):
        page = _Page.parse(response.text, response.url)
        title = title or page.heading
        dates = dates or page.dates
        download = next((link for link in page.links if urlsplit(link).path.lower() == DOWNLOAD_PATH), None)
        if download:
            break
        if page.gate is not None:
            action, fields = page.gate
            if _tournament_of(action) != identifier:
                raise RetrievalError(identifier, "details gate", f"the form posts to another page: {action}")
            if action.lower() in submitted:
                raise RetrievalError(identifier, "details gate", "the gate returned after it was submitted")
            submitted.add(action.lower())
            response = client.request("POST", action, "details gate", data=fields)
            continue
        details = next((link for link in page.links if link.lower() not in visited
                        and _tournament_of(link) == identifier and _is_details(link)), None)
        if details is None:
            raise RetrievalError(identifier, "download link",
                                 "the page offers no Swiss-Manager download; the organizer may not publish one")
        visited.add(details.lower())
        response = client.request("GET", details, "full details")
    else:
        raise RetrievalError(identifier, "download link", f"no download link after {MAX_STEPS} pages")

    content, download_response = client.download(download, max_bytes)
    try:
        tournament = parse(content)
    except ParseError as error:
        raise RetrievalError(identifier, "validation", f"the download is not a readable TUNX file: {error}") from error
    if not title or _normalized(tournament.name) != _normalized(title):
        raise RetrievalError(identifier, "identity",
                             f"the file is for '{tournament.name}', but the tournament page shows '{title}'")
    return RetrievedTunx(
        tournament_id=identifier,
        title=tournament.name.strip(),
        content=content,
        source_url=source_url,
        download_url=download_response.url,
        filename=_attachment_filename(download_response.headers.get("Content-Disposition", "")),
        retrieved_utc=datetime.now(UTC).isoformat(),
        start_date=dates[0] if dates else None,
        end_date=dates[1] if dates else None,
    )


def retained_tunx_path(inputs_directory: Path, identifier: str) -> Path:
    return Path(inputs_directory) / RILTON_DIRECTORY / f"{identifier}.TUNX"


def retained_provenance(inputs_directory: Path, identifier: str) -> dict | None:
    """Return the provenance of a retained TUNX file, or None when the file or its provenance is missing or unreadable."""
    path = retained_tunx_path(inputs_directory, identifier)
    try:
        provenance = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return provenance if path.is_file() and isinstance(provenance, dict) else None


def retain(retrieved: RetrievedTunx, inputs_directory: Path) -> Path:
    """Atomically save the file and its provenance, replacing any earlier copy."""
    path = retained_tunx_path(inputs_directory, retrieved.tournament_id)
    atomic_replace_bytes(path, retrieved.content)
    atomic_replace_text(path.with_suffix(".json"), json.dumps({
        "tournament_id": retrieved.tournament_id,
        "title": retrieved.title,
        "source_url": retrieved.source_url,
        "download_url": retrieved.download_url,
        "filename": retrieved.filename,
        "retrieved_utc": retrieved.retrieved_utc,
        "start_date": retrieved.start_date.isoformat() if retrieved.start_date else None,
        "end_date": retrieved.end_date.isoformat() if retrieved.end_date else None,
        "sha256": retrieved.sha256,
    }, ensure_ascii=False, indent=2) + "\n")
    return path


class _Client:
    """Send requests in one session and follow redirects only to chess-results hosts."""

    def __init__(self, identifier: str, session: requests.Session, sleep: Sleep) -> None:
        self.identifier = identifier
        self.session = session
        self.sleep = sleep

    def request(self, method: str, url: str, stage: str, data: dict | None = None,
                stream: bool = False) -> requests.Response:
        for _ in range(MAX_REDIRECTS + 1):
            self._check_host(url, stage)
            try:
                response = send(self.session, method, url, sleep=self.sleep, data=data,
                                allow_redirects=False, stream=stream)
            except UpstreamRetryExhausted as error:
                raise RetrievalError(self.identifier, stage, f"request failed: {error}") from error
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                method, data = "GET", None
                continue
            if response.status_code != 200:
                raise RetrievalError(self.identifier, stage, f"HTTP {response.status_code} from {url}")
            return response
        raise RetrievalError(self.identifier, stage, f"more than {MAX_REDIRECTS} redirects")

    def download(self, url: str, max_bytes: int) -> tuple[bytes, requests.Response]:
        response = self.request("GET", url, "download", stream=True)
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise RetrievalError(self.identifier, "download", f"the file exceeds {max_bytes} bytes")
        content = bytearray()
        try:
            for chunk in response.iter_content(65536):
                content += chunk
                if len(content) > max_bytes:
                    raise RetrievalError(self.identifier, "download", f"the file exceeds {max_bytes} bytes")
        except requests.RequestException as error:
            raise RetrievalError(self.identifier, "download", f"request failed: {error}") from error
        finally:
            response.close()
        if bytes(content[:4]) != MAGIC.to_bytes(4, "little"):
            kind = "an HTML page" if content.lstrip()[:1] == b"<" else "a file without the TUNX signature"
            raise RetrievalError(self.identifier, "download", f"the server returned {kind} instead of a TUNX file")
        return bytes(content), response

    def _check_host(self, url: str, stage: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not HOST.fullmatch(parts.hostname or ""):
            raise RetrievalError(self.identifier, stage, f"refused a request outside chess-results.com: {url}")


class _Page(HTMLParser):
    """Collect the first heading, the links, the details gate, and the `Date` row of one page."""

    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.heading: str | None = None
        self.links: list[str] = []
        self.gate: tuple[str, dict[str, str]] | None = None
        self.dates: tuple[date, date] | None = None
        self._cells: list[str] | None = None
        self._in_heading = False
        self._heading_text: list[str] = []
        self._form: tuple[str, dict[str, str]] | None = None

    @classmethod
    def parse(cls, text: str, url: str) -> _Page:
        page = cls(url)
        page.feed(text)
        page.close()
        return page

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "a" and attributes.get("href"):
            self.links.append(urljoin(self.url, attributes["href"]))
        elif tag == "h2" and self.heading is None:
            self._in_heading = True
        elif tag == "tr":
            self._cells = []
        elif tag == "td" and self._cells is not None:
            self._cells.append("")
        elif tag == "form":
            self._form = (urljoin(self.url, attributes.get("action") or self.url), {})
        elif tag == "input" and self._form is not None and attributes.get("name"):
            # Submit only the gate's own button; other buttons are unrelated actions.
            kind = attributes.get("type", "text").lower()
            is_gate_button = kind == "submit" and attributes["name"] == GATE_CONTROL
            if kind in {"hidden", "text"} or is_gate_button:
                self._form[1][attributes["name"]] = attributes.get("value", "")
            if is_gate_button:
                self.gate = self._form

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_heading:
            self._in_heading = False
            self.heading = " ".join("".join(self._heading_text).split())
        elif tag == "tr" and self._cells is not None:
            if self.dates is None and len(self._cells) == 2 and self._cells[0].strip() == DATE_LABEL:
                self.dates = _dates(self._cells[1])
            self._cells = None
        elif tag == "form":
            self._form = None

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_text.append(data)
        if self._cells:
            self._cells[-1] += data


def _dates(text: str) -> tuple[date, date] | None:
    """Read `2025/01/02 to 2025/01/05`, or a single date, as start and end dates."""
    match = DATES.fullmatch(text.strip())
    if not match:
        return None
    try:
        start = datetime.strptime(match.group(1), "%Y/%m/%d").date()
        end = datetime.strptime(match.group(2) or match.group(1), "%Y/%m/%d").date()
    except ValueError:
        return None
    return start, end


def _tournament_of(url: str) -> str | None:
    parts = urlsplit(url)
    match = TOURNAMENT_PATH.fullmatch(parts.path)
    return str(int(match.group(1))) if match and HOST.fullmatch(parts.hostname or "") else None


def _is_details(url: str) -> bool:
    return parse_qs(urlsplit(url).query).get("turdet") == ["YES"]


def _normalized(name: str) -> str:
    return " ".join(name.split()).casefold()


def _attachment_filename(disposition: str) -> str | None:
    match = re.search(r'filename="?([^";]+)"?', disposition)
    return Path(match.group(1)).name if match else None
