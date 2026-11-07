"""The member-system search and lookup endpoints, answered by a fake member system."""

from datetime import UTC, datetime
import json

import pytest
import requests

from senior_gp.member_system import BASE_URL, MemberSystemDiscovery
from senior_gp.web import create_app

SEARCH_URL = f"{BASE_URL}/tournament/group/search/"
TOURNAMENT_URL = f"{BASE_URL}/tournament/tournament/id/"


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return json.loads(self.body)

    def close(self):
        pass


class FakeMemberSystem:
    """Answer each URL with its (status, body) pair, where the body is JSON data or raw text, a request exception, or HTTP 404 when unlisted."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def request(self, method, url, timeout=None, **options):
        self.urls.append(url)
        answer = self.answers.get(url, (404, None))
        if isinstance(answer, Exception):
            raise answer
        status, data = answer
        return FakeResponse(status, data if isinstance(data, str) else json.dumps(data))


def _tournament(tournament_id, name, start, end):
    return {"id": tournament_id, "name": name, "start": start, "end": end, "rootClasses": []}


@pytest.fixture
def discovery_client(tmp_path):
    def make(answers):
        member_system = FakeMemberSystem(answers)
        app = create_app({
            "TESTING": True,
            "STATE_DIRECTORY": tmp_path / "state",
            "OUTPUT_DIRECTORY": tmp_path / "output",
            # 31 May 2026 in Stockholm, when the choices are 2026 and 2025 and the default is 2025.
            "CLOCK": lambda: datetime(2026, 5, 31, 12, tzinfo=UTC),
            "MEMBER_SYSTEM": MemberSystemDiscovery(new_session=lambda: member_system, sleep=lambda _seconds: None),
        })
        return app.test_client(), member_system
    return make


class TestSearch:

    def test_matching_groups_are_grouped_by_tournament_highest_id_first(self, discovery_client):
        client, member_system = discovery_client({f"{SEARCH_URL}Senior%20GP": (200, [
            {"id": 11, "name": "Grupp A", "tournamentid": 5382, "tournamentname": "Senior GP 1"},
            {"id": 21, "name": "Grupp A", "tournamentid": 5400, "tournamentname": "Senior GP 2",
             "latestUpdatedGame": "2025-10-04T15:00:00"},
            {"id": 12, "name": "Grupp B", "tournamentid": 5382, "tournamentname": "Senior GP 1"},
        ])})

        response = client.get("/api/v1/tournaments/search?q=%20Senior%20GP%20")

        assert response.status_code == 200
        assert response.get_json() == {"data": {"state": "results", "query": "Senior GP", "tournaments": [
            {"tournament_id": 5400, "name": "Senior GP 2", "matching_groups": [
                {"group_id": 21, "name": "Grupp A", "latest_updated_game": "2025-10-04T15:00:00"},
            ]},
            {"tournament_id": 5382, "name": "Senior GP 1", "matching_groups": [
                {"group_id": 11, "name": "Grupp A", "latest_updated_game": None},
                {"group_id": 12, "name": "Grupp B", "latest_updated_game": None},
            ]},
        ]}}
        assert member_system.urls == [f"{SEARCH_URL}Senior%20GP"]

    def test_no_matches(self, discovery_client):
        client, _ = discovery_client({f"{SEARCH_URL}Ok%C3%A4nd": (200, [])})

        response = client.get("/api/v1/tournaments/search?q=Okänd")

        assert response.get_json() == {"data": {"state": "no_matches", "query": "Okänd", "tournaments": []}}

    @pytest.mark.parametrize("query", ["", "?q=", "?q=%20%20"])
    def test_blank_search_text_is_refused_without_asking_the_member_system(self, discovery_client, query):
        client, member_system = discovery_client({})

        response = client.get(f"/api/v1/tournaments/search{query}")

        assert response.status_code == 400
        assert response.get_json() == {"error": {
            "code": "invalid_input", "message_key": "errors.tournament_search.invalid_input", "details": {"field": "q"},
        }}
        assert member_system.urls == []


class TestLookup:

    @pytest.mark.parametrize("name, scoring", [
        ("Senior GP Höstcupen", "GP"),
        ("Stockholmsmästerskapet för seniorer", "DM"),
    ])
    def test_a_tournament_in_the_season_has_its_dates_and_suggested_scoring(self, discovery_client, name, scoring):
        client, _ = discovery_client({
            f"{TOURNAMENT_URL}5382": (200, _tournament(5382, name, "2025-09-06T10:00:00Z", "2025-09-07")),
        })

        response = client.get("/api/v1/tournaments/5382?season=2025")

        assert response.status_code == 200
        assert response.get_json() == {"data": {"tournament": {
            "tournament_id": 5382, "name": name, "start_date": "2025-09-06", "end_date": "2025-09-07",
            "suggested_scoring": scoring,
        }}}

    @pytest.mark.parametrize("start, allowed", [
        ("2024-12-31", False),
        # 23:30 UTC on 31 December 2024 is 1 January 2025 in Stockholm.
        ("2024-12-31T23:30:00Z", True),
        ("2025-01-01", True),
        ("2026-12-31", True),
        ("2027-01-01", False),
    ])
    def test_a_tournament_must_start_in_the_season_year_or_the_next(self, discovery_client, start, allowed):
        client, _ = discovery_client({f"{TOURNAMENT_URL}5382": (200, _tournament(5382, "Cupen", start, start))})

        response = client.get("/api/v1/tournaments/5382?season=2025")

        if allowed:
            assert response.status_code == 200
        else:
            assert response.status_code == 422
            assert response.get_json() == {"error": {
                "code": "tournament_outside_season", "message_key": "errors.tournament_lookup.outside_season",
                "details": {"source": "member", "tournament_id": 5382, "season": 2025, "start_date": start},
            }}

    def test_without_a_season_the_default_season_applies(self, discovery_client):
        client, _ = discovery_client({
            f"{TOURNAMENT_URL}5382": (200, _tournament(5382, "Cupen", "2027-02-01", "2027-02-01")),
        })

        assert client.get("/api/v1/tournaments/5382").get_json()["error"]["details"]["season"] == 2025

    def test_an_unknown_tournament_is_not_found(self, discovery_client):
        client, _ = discovery_client({})

        response = client.get("/api/v1/tournaments/9999?season=2025")

        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "tournament_not_found"

    @pytest.mark.parametrize("tournament_id", ["0", "012", "12a", "-5", "１２"])
    def test_an_invalid_id_is_refused_without_asking_the_member_system(self, discovery_client, tournament_id):
        client, member_system = discovery_client({})

        response = client.get(f"/api/v1/tournaments/{tournament_id}?season=2025")

        assert response.status_code == 400
        assert response.get_json()["error"]["details"] == {"field": "tournament_id"}
        assert member_system.urls == []

    @pytest.mark.parametrize("season", ["2024", "2027", "x"])
    def test_a_season_outside_the_choices_is_refused(self, discovery_client, season):
        client, member_system = discovery_client({})

        response = client.get(f"/api/v1/tournaments/5382?season={season}")

        assert response.status_code == 400
        assert response.get_json()["error"] == {
            "code": "invalid_input", "message_key": "errors.season.invalid_input", "details": {"field": "season"},
        }
        assert member_system.urls == []


@pytest.mark.parametrize("answer", [
    (503, {}),
    requests.ConnectionError("refused"),
    (403, {}),
    (200, "<html>"),
    (200, {"id": 5382, "name": "Cupen"}),
    (200, _tournament(5383, "Cupen", "2025-09-06", "2025-09-06")),
], ids=["5xx", "connection", "403", "not-json", "missing-dates", "other-tournament"])
def test_an_unavailable_member_system_is_a_502(discovery_client, answer):
    client, _ = discovery_client({f"{TOURNAMENT_URL}5382": answer, f"{SEARCH_URL}Cupen": answer})

    for path in ("/api/v1/tournaments/5382?season=2025", "/api/v1/tournaments/search?q=Cupen"):
        response = client.get(path)
        assert response.status_code == 502
        assert response.get_json() == {"error": {
            "code": "upstream_failure", "message_key": "errors.member_system.unavailable", "details": {},
        }}
