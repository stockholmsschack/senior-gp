"""Check the upstream retry policy through member-system retention."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import requests

from senior_gp.inputs import RetainedHttp
from senior_gp.upstream import UpstreamRetryExhausted

URL = "https://member.schack.se/public/api/v1/tournament/tournament/id/5382"


class FakeResponse:
    def __init__(self, status, body=b"{}"):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        pass


class SequenceSession:
    """Answer each request with the next outcome."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.timeouts = []

    def request(self, method, url, timeout=None, **options):
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.sleeps = []

    def http(self, *outcomes):
        session = SequenceSession(*outcomes)
        return RetainedHttp(self.directory, offline=False, session=session, sleep=self.sleeps.append), session

    def test_transient_failures_are_retried_with_linear_backoff(self):
        http, session = self.http(requests.ConnectionError("reset"), FakeResponse(503), FakeResponse(200, b'{"id": 1}'))
        self.assertEqual(http.get(URL).json(), {"id": 1})
        self.assertEqual(self.sleeps, [0.25, 0.5])
        self.assertEqual(session.timeouts, [(3.0, 15.0)] * 3)
        self.assertEqual(len(list(self.directory.glob("*.body"))), 1)

    def test_other_client_errors_are_not_retried_or_retained(self):
        http, session = self.http(FakeResponse(404))
        with self.assertRaises(requests.HTTPError):
            http.get(URL)
        self.assertEqual((session.timeouts, self.sleeps), ([(3.0, 15.0)], []))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_exhausted_retries_name_the_last_failure(self):
        http, _ = self.http(FakeResponse(503), FakeResponse(502), FakeResponse(429))
        with self.assertRaisesRegex(UpstreamRetryExhausted, r"^HTTP 429; exhausted 3 attempts$"):
            http.get(URL)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_retained_response_records_provenance(self):
        http, _ = self.http(FakeResponse(200, b"[]"))
        http.get(URL)
        provenance = json.loads(next(self.directory.glob("*.json")).read_text())
        self.assertEqual((provenance["url"], provenance["status"]), (URL, 200))


if __name__ == "__main__":
    unittest.main()
