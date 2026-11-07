"""The Rilton verification endpoint, answered by a fake chess-results retrieval."""

from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest

from senior_gp.chess_results import RetrievalError, RetrievedTunx, retained_tunx_path
from senior_gp.inputs import inputs_directory
from senior_gp.web import create_app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rilton"
U1800 = (FIXTURES / "rilton_u1800_2024_2025_967028.TUNX").read_bytes()
U2200 = (FIXTURES / "rilton_u2200_2024_2025_967027.TUNX").read_bytes()


def _retrieved(identifier, title, content, start=date(2025, 1, 2), end=date(2025, 1, 5)):
    return RetrievedTunx(
        tournament_id=identifier,
        title=title,
        content=content,
        source_url=f"https://chess-results.com/tnr{identifier}.aspx?lan=1",
        download_url="https://s2.chess-results.com/DownloadTurnier.Aspx?art=1",
        filename=None,
        retrieved_utc="2026-05-31T12:00:00+00:00",
        start_date=start,
        end_date=end,
    )


@pytest.fixture
def rilton_client(tmp_path):
    """Return a factory for a client whose retrieval answers each ID from `answers`, recording the requested IDs."""
    def make(answers):
        requested = []

        def fetch(identifier):
            requested.append(identifier)
            answer = answers[identifier]
            if isinstance(answer, Exception):
                raise answer
            return answer

        app = create_app({
            "TESTING": True,
            "STATE_DIRECTORY": tmp_path / "state",
            "OUTPUT_DIRECTORY": tmp_path / "output",
            # 31 May 2026 in Stockholm, when the choices are 2026 and 2025 and the default is 2025.
            "CLOCK": lambda: datetime(2026, 5, 31, 12, tzinfo=UTC),
            "RILTON_FETCH": fetch,
        })
        return app.test_client(), requested
    return make


def _verify(client, url, season=None):
    query = f"?season={season}" if season else ""
    return client.post(f"/api/v1/rilton/verify{query}", json={"url": url})


def _retained(tmp_path, identifier):
    return retained_tunx_path(inputs_directory(tmp_path / "state"), identifier)


def test_verified_tournament_is_retained_and_described(rilton_client, tmp_path):
    client, requested = rilton_client({"967028": _retrieved("967028", "Rilton U1800 2024/2025", U1800)})

    response = _verify(client, "https://s3.chess-results.com/tnr967028.aspx?lan=6&turdet=YES")

    assert response.status_code == 200
    assert response.get_json() == {"data": {"tournament": {
        "source": "rilton",
        "tournament_id": 967028,
        "name": "Rilton U1800 2024/2025",
        "url": "https://chess-results.com/tnr967028.aspx?lan=1",
        "start_date": "2025-01-02",
        "end_date": "2025-01-05",
        "edition": "2025/2026",
    }}}
    assert requested == ["967028"]
    assert _retained(tmp_path, "967028").read_bytes() == U1800
    provenance = json.loads(_retained(tmp_path, "967028").with_suffix(".json").read_text())
    assert provenance["start_date"] == "2025-01-02"


def test_tournament_without_a_date_is_accepted(rilton_client):
    client, _requested = rilton_client({"967028": _retrieved("967028", "Rilton U1800 2024/2025", U1800, None, None)})

    response = _verify(client, "https://chess-results.com/tnr967028.aspx")

    assert response.status_code == 200
    assert response.get_json()["data"]["tournament"]["start_date"] is None


@pytest.mark.parametrize("body", [
    {"url": "http://chess-results.com/tnr967028.aspx"},
    {"url": "https://example.com/tnr967028.aspx"},
    {"url": "967028"},
    {"url": 967028},
    {},
])
def test_invalid_url_is_refused_without_retrieval(rilton_client, body):
    client, requested = rilton_client({})

    response = client.post("/api/v1/rilton/verify", json=body)

    assert response.status_code == 400
    assert response.get_json()["error"]["message_key"] == "errors.rilton.invalid_url"
    assert response.get_json()["error"]["details"] == {"field": "url"}
    assert requested == []


def test_season_outside_the_choices_is_refused(rilton_client):
    client, requested = rilton_client({})

    response = _verify(client, "https://chess-results.com/tnr967028.aspx", season=2024)

    assert response.status_code == 400
    assert response.get_json()["error"]["details"] == {"field": "season"}
    assert requested == []


@pytest.mark.parametrize(("stage", "message_key"), [
    ("tournament page", "errors.rilton.unavailable"),
    ("details gate", "errors.rilton.unavailable"),
    ("full details", "errors.rilton.unavailable"),
    ("download", "errors.rilton.unavailable"),
    ("download link", "errors.rilton.no_download"),
    ("validation", "errors.rilton.unsupported_file"),
    ("identity", "errors.rilton.unsupported_file"),
])
def test_retrieval_failure_names_its_stage_and_retains_nothing(rilton_client, tmp_path, stage, message_key):
    client, _requested = rilton_client({"967028": RetrievalError("967028", stage, "the cause")})

    response = _verify(client, "https://chess-results.com/tnr967028.aspx")

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "rilton_retrieval_failed",
        "message_key": message_key,
        "details": {"tournament_id": 967028, "stage": stage,
                    "cause": f"chess-results tournament 967028: {stage}: the cause"},
    }
    assert not _retained(tmp_path, "967028").exists()


def test_unreadable_season_file_stops_verification_before_retrieval(rilton_client, tmp_path):
    path = tmp_path / "state" / "seasons" / "2025" / "active-configuration.toml"
    path.parent.mkdir(parents=True)
    path.write_text("not toml =")
    client, requested = rilton_client({})

    response = _verify(client, "https://chess-results.com/tnr967028.aspx")

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "invalid_configuration"
    assert requested == []


def test_tournament_outside_the_season_is_refused_and_not_retained(rilton_client, tmp_path):
    client, _requested = rilton_client({"967028": _retrieved("967028", "Rilton U1800 2024/2025", U1800)})

    response = _verify(client, "https://chess-results.com/tnr967028.aspx", season=2026)

    assert response.status_code == 422
    assert response.get_json()["error"] == {
        "code": "tournament_outside_season",
        "message_key": "errors.tournament_lookup.outside_season",
        "details": {"source": "rilton", "tournament_id": 967028, "season": 2026, "start_date": "2025-01-02"},
    }
    assert not _retained(tmp_path, "967028").exists()
