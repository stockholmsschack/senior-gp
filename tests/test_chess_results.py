"""Check TUNX retrieval from chess-results.com against sanitized recorded pages."""

from datetime import date
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

import requests

from senior_gp.chess_results import RetrievalError, fetch_tunx, retain, retained_tunx_path, tournament_id
from senior_gp.configuration import RILTON, ActiveConfiguration, Tournament
from senior_gp.inputs import MissingInputError, rilton_sections

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAGES = FIXTURES / "chess_results"
U1800_2024 = (FIXTURES / "rilton" / "rilton_u1800_2024_2025_967028.TUNX").read_bytes()
U2200_2024 = (FIXTURES / "rilton" / "rilton_u2200_2024_2025_967027.TUNX").read_bytes()

START = "https://chess-results.com/tnr967028.aspx?lan=1"
GATE = "https://s3.chess-results.com/tnr967028.aspx?lan=1"
DETAILS = "https://chess-results.com/tnr967028.aspx?lan=1&flag=30&turdet=YES"
DETAILS_S2 = "https://s2.chess-results.com/tnr967028.aspx?lan=1&flag=30&turdet=YES&SNode=S0"
DOWNLOAD = "https://S2.chess-results.com/DownloadTurnier.Aspx?art=1"


def NO_SLEEP(seconds):
    pass


class FakeResponse:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.url = url
        self.status_code = status
        self.content = body
        self.headers = headers or {}
        self.is_redirect = "Location" in self.headers

    @property
    def text(self):
        return self.content.decode()

    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]

    def close(self):
        pass


def page(name):
    return (PAGES / name).read_bytes()


def redirect(url, location):
    return FakeResponse(url, 302, headers={"Location": location})


def recorded_flow():
    """Return the 2026-10-25 flow: two gates, a host switch, and the download."""
    return {
        ("GET", START): redirect(START, GATE),
        ("GET", GATE): FakeResponse(GATE, body=page("gate.html")),
        ("POST", GATE): FakeResponse(GATE, body=page("revealed.html")),
        ("GET", DETAILS): redirect(DETAILS, DETAILS_S2),
        ("GET", DETAILS_S2): FakeResponse(DETAILS_S2, body=page("details_gate.html")),
        ("POST", DETAILS_S2): FakeResponse(DETAILS_S2, body=page("details.html")),
        ("GET", DOWNLOAD): FakeResponse(DOWNLOAD, body=U1800_2024, headers={
            "Content-Type": "application/tunx",
            "Content-Disposition": 'attachment;filename="rilton_u1800_2024_2025_967028.TUNX"',
        }),
    }


def ungated_flow():
    """Return the flow of a recent tournament, which chess-results serves without the details gate."""
    return {
        ("GET", START): FakeResponse(START, body=page("revealed.html")),
        ("GET", DETAILS): FakeResponse(DETAILS, body=page("details.html")),
        ("GET", DOWNLOAD): FakeResponse(DOWNLOAD, body=U1800_2024),
    }


class FakeSession:
    """Answer requests from a route table and record each one."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def request(self, method, url, data=None, **options):
        self.requests.append((method, url, data))
        route = self.routes.get((method, url))
        if route is None:
            raise AssertionError(f"unexpected request {method} {url}")
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        return route


def fetch(routes, **options):
    return fetch_tunx("967028", session=FakeSession(routes), sleep=NO_SLEEP, **options)


class TournamentIdTests(unittest.TestCase):
    def test_equivalent_links_give_one_id(self):
        for url in ("https://s3.chess-results.com/tnr967028.aspx?lan=1",
                    "https://chess-results.com/tnr967028.aspx?lan=6&art=1&turdet=YES",
                    " https://S2.Chess-Results.com/TNR967028.aspx "):
            self.assertEqual(tournament_id(url), "967028", url)

    def test_other_links_are_refused(self):
        for url in ("http://chess-results.com/tnr967028.aspx", "https://chess-results.com.example/tnr967028.aspx",
                    "https://chess-results.com/DownloadTurnier.Aspx?art=1", "967028"):
            with self.assertRaises(ValueError, msg=url):
                tournament_id(url)


class RetrievalTests(unittest.TestCase):
    def test_gates_and_host_switch_reach_the_validated_download(self):
        session = FakeSession(recorded_flow())
        retrieved = fetch_tunx("967028", session=session, sleep=NO_SLEEP)

        self.assertEqual(retrieved.content, U1800_2024)
        self.assertEqual(retrieved.title, "Rilton U1800 2024/2025")
        self.assertEqual(retrieved.filename, "rilton_u1800_2024_2025_967028.TUNX")
        self.assertEqual(retrieved.download_url, DOWNLOAD)
        self.assertEqual((retrieved.start_date, retrieved.end_date), (date(2025, 1, 2), date(2025, 1, 5)))
        posts = [data for method, _, data in session.requests if method == "POST"]
        self.assertEqual(len(posts), 2)
        for data in posts:
            # The gate submits its current state and its own button, not the search button.
            self.assertEqual(data, {
                "__VIEWSTATE": "VIEWSTATE-PLACEHOLDER", "__VIEWSTATEGENERATOR": "GENERATOR-PLACEHOLDER",
                "__EVENTVALIDATION": "VALIDATION-PLACEHOLDER", "cb_alleDetails": "Show tournament details",
                "txt_name": "",
            })

    def test_recent_tournament_reaches_the_download_without_a_gate(self):
        session = FakeSession(ungated_flow())
        retrieved = fetch_tunx("967028", session=session, sleep=NO_SLEEP)

        self.assertEqual(retrieved.content, U1800_2024)
        self.assertEqual((retrieved.start_date, retrieved.end_date), (date(2025, 1, 2), date(2025, 1, 5)))
        self.assertEqual([method for method, _, _ in session.requests], ["GET", "GET", "GET"])

    def test_retained_copy_holds_content_and_provenance(self):
        with TemporaryDirectory() as directory:
            path = retain(fetch(recorded_flow()), Path(directory))
            self.assertEqual(path, retained_tunx_path(Path(directory), "967028"))
            self.assertEqual(path.read_bytes(), U1800_2024)
            provenance = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual((provenance["source_url"], provenance["download_url"]), (START, DOWNLOAD))
            self.assertEqual((provenance["start_date"], provenance["end_date"]), ("2025-01-02", "2025-01-05"))
            self.assertEqual(len(provenance["sha256"]), 64)

    def test_failures_name_the_stage_and_cause(self):
        flow = recorded_flow()
        cases = {
            "redirect off the site": ({("GET", START): redirect(START, "https://example.com/tnr967028.aspx")},
                                      "tournament page: refused a request outside chess-results.com"),
            "HTTP error": ({("GET", START): FakeResponse(START, 404)}, "tournament page: HTTP 404"),
            "server error after retries": ({("GET", START): FakeResponse(START, 503)},
                                           "tournament page: request failed: HTTP 503; exhausted 3 attempts"),
            "timeout after retries": ({("GET", START): requests.Timeout("read timed out")},
                                      "tournament page: request failed: Timeout: read timed out; "
                                      "exhausted 3 attempts"),
            "repeated gate": ({**flow, ("POST", GATE): FakeResponse(GATE, body=page("gate.html"))},
                              "details gate: the gate returned after it was submitted"),
            "missing download": ({**flow, ("POST", DETAILS_S2): FakeResponse(DETAILS_S2, body=page("no_download.html"))},
                                 "download link: the page offers no Swiss-Manager download"),
            "HTML masquerading as a file": (
                {**flow, ("GET", DOWNLOAD): FakeResponse(DOWNLOAD, body=page("details.html"),
                                                         headers={"Content-Type": "application/tunx"})},
                "download: the server returned an HTML page instead of a TUNX file"),
            "another tournament's file": ({**flow, ("GET", DOWNLOAD): FakeResponse(DOWNLOAD, body=U2200_2024)},
                                          "identity: the file is for 'Rilton U2200 2024/2025', "
                                          "but the tournament page shows 'Rilton U1800 2024/2025'"),
            "unreadable file": ({**flow, ("GET", DOWNLOAD): FakeResponse(DOWNLOAD, body=U1800_2024[:4000])},
                                "validation: the download is not a readable TUNX file"),
        }
        for name, (routes, message) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(RetrievalError,
                                                            "^" + re.escape(f"chess-results tournament 967028: {message}")):
                fetch(routes)

    def test_transient_failures_are_retried_twice(self):
        session = FakeSession({**recorded_flow(), ("GET", START): [
            requests.ConnectionError("connection reset"), FakeResponse(START, 503), redirect(START, GATE)]})
        self.assertEqual(fetch_tunx("967028", session=session, sleep=NO_SLEEP).content, U1800_2024)
        self.assertEqual([url for _, url, _ in session.requests].count(START), 3)

        session = FakeSession({("GET", START): FakeResponse(START, 404)})
        with self.assertRaises(RetrievalError):
            fetch_tunx("967028", session=session, sleep=NO_SLEEP)
        self.assertEqual(len(session.requests), 1)

    def test_oversized_download_is_refused(self):
        with self.assertRaisesRegex(RetrievalError, "download: the file exceeds 10000 bytes"):
            fetch(recorded_flow(), max_bytes=10_000)

    def test_links_to_other_sections_are_not_followed(self):
        # no_download.html links to the U2200 and Cup sections; the session refuses any request to them.
        session = FakeSession({**recorded_flow(),
                               ("POST", DETAILS_S2): FakeResponse(DETAILS_S2, body=page("no_download.html"))})
        with self.assertRaises(RetrievalError):
            fetch_tunx("967028", session=session, sleep=NO_SLEEP)
        self.assertFalse(any("967027" in url or "967022" in url for _, url, _ in session.requests))


class RetentionPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.inputs = Path(directory.name)
        section = Tournament(RILTON, "967028", "Rilton U1800")
        self.configuration = ActiveConfiguration(2024, (section,), revision=1)

    def test_online_run_downloads_only_a_missing_section(self):
        downloads = []

        def download(identifier):
            downloads.append(identifier)
            return fetch(recorded_flow())

        for _ in range(2):
            sections = rilton_sections(self.configuration, self.inputs, offline=False, fetch=download)
        self.assertEqual(downloads, ["967028"])
        self.assertEqual(sections.files["967028"].read_bytes(), U1800_2024)

    def test_failed_refresh_keeps_the_retained_copy(self):
        retain(fetch(recorded_flow()), self.inputs)

        def failing(identifier):
            raise RetrievalError(identifier, "download link", "the page offers no Swiss-Manager download")

        with self.assertRaises(RetrievalError):
            rilton_sections(self.configuration, self.inputs, offline=False, refresh=True, fetch=failing)
        self.assertEqual(retained_tunx_path(self.inputs, "967028").read_bytes(), U1800_2024)

    def test_missing_section_is_unreadable_offline_and_after_a_failed_download(self):
        def failing(identifier):
            raise RetrievalError(identifier, "download link", "the page offers no Swiss-Manager download")

        section = self.configuration.tournaments[0]
        for sections, error in ((rilton_sections(self.configuration, self.inputs, offline=True), MissingInputError),
                                (rilton_sections(self.configuration, self.inputs, offline=False, fetch=failing),
                                 RetrievalError)):
            with self.assertRaises(error):
                sections.rows(section, 2024)
        self.assertFalse(retained_tunx_path(self.inputs, "967028").exists())


if __name__ == "__main__":
    unittest.main()
