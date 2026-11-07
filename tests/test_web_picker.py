"""The tournament picker: its browser state under Node, and the route that saves the season's tournaments."""

from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from senior_gp.chess_results import retain
from senior_gp.configuration import (
    DM,
    GP,
    MEMBER_SYSTEM,
    RILTON,
    ActiveConfiguration,
    Tournament,
    configuration_path,
    load_configuration,
    save_configuration,
)
from senior_gp.inputs import inputs_directory
from senior_gp.member_system import MemberSystemDiscovery
from senior_gp.web import create_app
from tests.test_web_discovery import TOURNAMENT_URL, FakeMemberSystem, _tournament
from tests.test_web_rilton import U1800, U2200, _retrieved

ROOT = Path(__file__).resolve().parent.parent
SAVE = "/api/v1/configuration/tournaments?season=2025"
CONFIGURATION = ActiveConfiguration(2025, (
    Tournament(MEMBER_SYSTEM, "5366", "Stockholmsmästerskapet", DM, start_date=date(2025, 3, 3)),
    Tournament(MEMBER_SYSTEM, "5382", "Senior GP Höstcupen", GP, start_date=date(2025, 3, 21)),
    Tournament(RILTON, "1301929", "Rilton U1800", GP, start_date=date(2026, 1, 2)),
))


@pytest.mark.parametrize("script", [
    "tournament-search-state.mjs", "tournament-picker.mjs", "configuration-save-queue.mjs",
])
def test_browser_state(script):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    completed = subprocess.run([node, f"tests/browser/{script}"], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.fixture
def picker_client(tmp_path):
    """Return a client, its fake member system and the state directory, with `CONFIGURATION` saved as revision 1."""
    state_directory = tmp_path / "state"
    save_configuration(state_directory, CONFIGURATION)
    member_system = FakeMemberSystem({
        f"{TOURNAMENT_URL}5400": (200, _tournament(5400, "Stockholmsmästerskapet i Blixt", "2026-02-01", "2026-02-01")),
        f"{TOURNAMENT_URL}5100": (200, _tournament(5100, "Vårcupen 2024", "2024-04-01", "2024-04-01")),
    })
    app = create_app({
        "TESTING": True,
        "STATE_DIRECTORY": state_directory,
        "OUTPUT_DIRECTORY": tmp_path / "output",
        # 31 May 2026 in Stockholm, when the choices are 2026 and 2025 and the default is 2025.
        "CLOCK": lambda: datetime(2026, 5, 31, 12, tzinfo=UTC),
        "MEMBER_SYSTEM": MemberSystemDiscovery(new_session=lambda: member_system, sleep=lambda _seconds: None),
    })
    return app.test_client(), member_system, state_directory


def _member(tournament_id, scoring):
    return {"source": "member", "tournament_id": tournament_id, "scoring": scoring}


def _rilton(tournament_id, rating_floor=None):
    return {"source": "rilton", "tournament_id": tournament_id, "rating_floor": rating_floor}


def _entries(*pairs):
    return [_member(tournament_id, scoring) for tournament_id, scoring in pairs]


STORED_RILTON = _rilton(1301929)


def _verified(state_directory, identifier, title, content=U2200, **dates):
    """Retain a verified Rilton tournament, as the verification endpoint does."""
    retain(_retrieved(identifier, title, content, **dates), inputs_directory(state_directory))


def test_overview_resolves_missing_dates_before_ordering_tournaments(picker_client):
    client, member_system, state_directory = picker_client
    save_configuration(state_directory, ActiveConfiguration(2025, (
        Tournament(MEMBER_SYSTEM, "5400", "Stockholmsmästerskapet i Blixt", GP),
        Tournament(MEMBER_SYSTEM, "5382", "Cupen", GP, start_date=date(2026, 2, 10)),
    ), revision=1))
    before = configuration_path(state_directory, 2025).read_bytes()

    response = client.get("/?season=2025")

    assert response.status_code == 200
    entries = json.loads(re.search(r'id="selected-tournaments-data">(.*?)</script>',
                                  response.get_data(as_text=True)).group(1))
    assert [(entry["tournament_id"], entry["start_date"]) for entry in entries] == [
        (5400, "2026-02-01"), (5382, "2026-02-10")]
    assert member_system.urls == [f"{TOURNAMENT_URL}5400"]
    assert configuration_path(state_directory, 2025).read_bytes() == before


class TestSave:

    def test_a_new_tournament_takes_its_name_and_date_from_the_member_system_and_the_list_is_saved_by_date(
            self, picker_client):
        client, member_system, state_directory = picker_client

        response = client.post(SAVE, json={"revision": 1, "tournaments": [
            _member(5400, GP), _member(5382, GP), STORED_RILTON, _member(5366, DM),
        ]})

        assert response.status_code == 200
        member = {"source": "member", "rating_floor": None}
        assert response.get_json() == {"data": {"revision": 2, "changed": True, "tournaments": [
            {**member, "tournament_id": 5366, "name": "Stockholmsmästerskapet", "scoring": DM,
             "suggested_scoring": DM, "start_date": "2025-03-03"},
            {**member, "tournament_id": 5382, "name": "Senior GP Höstcupen", "scoring": GP, "suggested_scoring": GP,
             "start_date": "2025-03-21"},
            {"source": "rilton", "tournament_id": 1301929, "name": "Rilton U1800", "scoring": GP,
             "suggested_scoring": GP, "rating_floor": None, "start_date": "2026-01-02"},
            {**member, "tournament_id": 5400, "name": "Stockholmsmästerskapet i Blixt", "scoring": GP,
             "suggested_scoring": DM, "start_date": "2026-02-01"},
        ]}}
        assert member_system.urls == [f"{TOURNAMENT_URL}5400"]
        assert load_configuration(state_directory, 2025) == ActiveConfiguration(2025, CONFIGURATION.tournaments + (
            Tournament(MEMBER_SYSTEM, "5400", "Stockholmsmästerskapet i Blixt", GP, start_date=date(2026, 2, 1)),
        ), revision=2)

    def test_a_stored_tournament_without_a_date_gets_one(self, picker_client):
        client, member_system, state_directory = picker_client
        _verified(state_directory, "1301929", "Rilton U1800 2025/2026", U1800, start=date(2025, 12, 27))
        save_configuration(state_directory, ActiveConfiguration(2025, (
            Tournament(RILTON, "1301929", "Rilton U1800", GP),
            Tournament(MEMBER_SYSTEM, "5400", "Stockholmsmästerskapet i Blixt", GP),
        ), revision=1))

        client.post(SAVE, json={"revision": 2, "tournaments": [STORED_RILTON, _member(5400, DM)]})

        assert [(t.id, t.start_date) for t in load_configuration(state_directory, 2025).tournaments] == [
            ("1301929", date(2025, 12, 27)), ("5400", date(2026, 2, 1))]

    def test_a_change_of_type_alone_is_saved(self, picker_client):
        client, member_system, state_directory = picker_client

        response = client.post(SAVE, json={"revision": 1, "tournaments": [
            _member(5366, GP), STORED_RILTON, _member(5382, GP),
        ]})

        assert response.get_json()["data"]["revision"] == 2
        assert load_configuration(state_directory, 2025).tournaments[0].scoring == GP
        assert member_system.urls == []

    def test_an_unchanged_list_is_not_written(self, picker_client):
        client, _, state_directory = picker_client
        before = configuration_path(state_directory, 2025).read_bytes()

        response = client.post(SAVE, json={"revision": 1, "tournaments": [
            _member(5366, DM), STORED_RILTON, _member(5382, GP),
        ]})

        assert response.get_json()["data"]["changed"] is False
        assert response.get_json()["data"]["revision"] == 1
        assert configuration_path(state_directory, 2025).read_bytes() == before

    def test_a_tournament_left_out_is_removed(self, picker_client):
        client, _, state_directory = picker_client

        client.post(SAVE, json={"revision": 1, "tournaments": [STORED_RILTON]})
        assert load_configuration(state_directory, 2025).tournaments == CONFIGURATION.rilton_sections

        client.post(SAVE, json={"revision": 2, "tournaments": []})
        assert load_configuration(state_directory, 2025).tournaments == ()

    def test_an_entry_without_a_source_is_a_member_system_tournament(self, picker_client):
        client, _, state_directory = picker_client

        response = client.post(SAVE, json={"revision": 1, "tournaments": [
            {"tournament_id": 5366, "scoring": DM}, STORED_RILTON, {"tournament_id": 5382, "scoring": GP},
        ]})

        assert response.get_json()["data"]["changed"] is False

    def test_member_and_rilton_tournaments_with_one_id_are_saved_together(self, picker_client):
        client, _, state_directory = picker_client
        _verified(state_directory, "5366", "Rilton U2200 2024/2025")

        response = client.post(SAVE, json={"revision": 1, "tournaments": [
            _member(5366, DM), STORED_RILTON, _rilton(5366, 2000), _member(5382, GP),
        ]})

        assert response.status_code == 200
        added = response.get_json()["data"]["tournaments"][0]
        assert (added["name"], added["rating_floor"]) == ("Rilton U2200 2024/2025", 2000)
        assert load_configuration(state_directory, 2025).tournaments == (
            (Tournament(RILTON, "5366", "Rilton U2200 2024/2025", GP, 2000, date(2025, 1, 2)),)
            + CONFIGURATION.tournaments
        )

    def test_an_unverified_rilton_tournament_is_refused(self, picker_client):
        client, _, state_directory = picker_client
        before = configuration_path(state_directory, 2025).read_bytes()

        response = client.post(SAVE, json={"revision": 1, "tournaments": [STORED_RILTON, _rilton(967027)]})

        assert response.status_code == 422
        assert response.get_json()["error"] == {
            "code": "rilton_not_verified", "message_key": "errors.rilton.not_verified",
            "details": {"source": "rilton", "tournament_id": 967027},
        }
        assert configuration_path(state_directory, 2025).read_bytes() == before

    def test_a_verified_rilton_tournament_outside_the_season_is_refused(self, picker_client):
        client, _, state_directory = picker_client
        _verified(state_directory, "967027", "Rilton U2200 2024/2025")

        response = client.post("/api/v1/configuration/tournaments?season=2026", json={
            "revision": 0, "tournaments": [_rilton(967027)],
        })

        assert response.status_code == 422
        assert response.get_json()["error"]["details"] == {
            "source": "rilton", "tournament_id": 967027, "season": 2026, "start_date": "2025-01-02"}
        assert not configuration_path(state_directory, 2026).exists()

    def test_a_rilton_entry_without_a_floor_penalizes_nobody(self, picker_client):
        client, _, state_directory = picker_client
        _verified(state_directory, "967022", "Rilton Cup 2024/2025", U1800)

        response = client.post(SAVE, json={"revision": 1, "tournaments": [STORED_RILTON, _rilton(967022)]})

        assert response.status_code == 200
        assert load_configuration(state_directory, 2025).tournaments[1].rating_floor is None

    def test_a_stale_revision_is_refused_without_asking_the_member_system(self, picker_client):
        client, member_system, state_directory = picker_client
        before = configuration_path(state_directory, 2025).read_bytes()

        response = client.post(SAVE, json={"revision": 0, "tournaments": _entries((5400, GP))})

        assert response.status_code == 409
        assert response.get_json() == {"error": {
            "code": "stale_configuration", "message_key": "errors.configuration.stale",
            "details": {"current_revision": 1},
        }}
        assert configuration_path(state_directory, 2025).read_bytes() == before
        assert member_system.urls == []

    def test_a_save_writes_only_the_selected_season(self, picker_client):
        client, _, state_directory = picker_client
        before = configuration_path(state_directory, 2025).read_bytes()

        response = client.post("/api/v1/configuration/tournaments?season=2026", json={
            "revision": 0, "tournaments": _entries((5400, DM)),
        })

        assert response.get_json()["data"]["revision"] == 1
        assert load_configuration(state_directory, 2026).tournaments == (
            Tournament(MEMBER_SYSTEM, "5400", "Stockholmsmästerskapet i Blixt", DM, start_date=date(2026, 2, 1)),
        )
        assert configuration_path(state_directory, 2025).read_bytes() == before

    def test_a_new_tournament_outside_the_season_is_refused(self, picker_client):
        client, _, state_directory = picker_client

        response = client.post("/api/v1/configuration/tournaments?season=2026", json={
            "revision": 0, "tournaments": _entries((5100, GP)),
        })

        assert response.status_code == 422
        assert response.get_json()["error"]["code"] == "tournament_outside_season"
        assert not configuration_path(state_directory, 2026).exists()

    def test_an_unknown_new_tournament_is_not_found(self, picker_client):
        client, _, _ = picker_client

        response = client.post(SAVE, json={"revision": 1, "tournaments": _entries((9999, GP))})

        assert response.status_code == 404
        assert response.get_json()["error"]["details"] == {"source": "member", "tournament_id": 9999}

    @pytest.mark.parametrize("body", [
        [],
        {"tournaments": []},
        {"revision": True, "tournaments": []},
        {"revision": -1, "tournaments": []},
        {"revision": 1},
        {"revision": 1, "tournaments": [5366]},
        {"revision": 1, "tournaments": _entries((5366, "SM"))},
        {"revision": 1, "tournaments": _entries((0, GP))},
        {"revision": 1, "tournaments": _entries(("5366", GP))},
        {"revision": 1, "tournaments": _entries((5366, GP), (5366, DM))},
        {"revision": 1, "tournaments": [{"source": "other", "tournament_id": 5366, "scoring": GP}]},
        {"revision": 1, "tournaments": [{**_member(5366, GP), "rating_floor": 1800}]},
        {"revision": 1, "tournaments": [{**_rilton(5366), "scoring": DM}]},
        {"revision": 1, "tournaments": [_rilton(5366, 0)]},
        {"revision": 1, "tournaments": [_rilton(5366, "1800")]},
        {"revision": 1, "tournaments": [_rilton(5366, True)]},
        {"revision": 1, "tournaments": [_rilton(5366), _rilton(5366, 1800)]},
    ])
    def test_an_invalid_body_is_refused(self, picker_client, body):
        client, member_system, _ = picker_client

        response = client.post(SAVE, json=body)

        assert response.status_code == 400
        assert response.get_json()["error"] == {
            "code": "invalid_input", "message_key": "errors.configuration.invalid_input",
            "details": {"field": "tournaments"},
        }
        assert member_system.urls == []

    def test_a_season_outside_the_choices_is_refused(self, picker_client):
        client, _, _ = picker_client

        response = client.post("/api/v1/configuration/tournaments?season=2024", json={"revision": 0, "tournaments": []})

        assert response.status_code == 400
        assert response.get_json()["error"]["details"] == {"field": "season"}

    def test_an_unreadable_stored_configuration_is_reported(self, picker_client):
        client, _, state_directory = picker_client
        configuration_path(state_directory, 2025).write_bytes(b"\xff")

        response = client.post(SAVE, json={"revision": 1, "tournaments": []})

        assert response.status_code == 422
        error = response.get_json()["error"]
        assert error["code"] == "invalid_configuration"
        assert error["details"]["problems"][0].startswith("cannot read active configuration")


class TestPage:

    def test_the_picker_starts_with_all_the_seasons_tournaments_and_endpoints(self, picker_client):
        client, _, _ = picker_client

        body = client.get("/?season=2025").get_data(as_text=True)

        assert 'data-lookup-endpoint-template="/api/v1/tournaments/__tournament_id__?season=2025"' in body
        assert 'data-rilton-verify-endpoint="/api/v1/rilton/verify?season=2025"' in body
        assert 'data-save-endpoint="/api/v1/configuration/tournaments?season=2025"' in body
        assert 'data-configuration-revision="1"' in body
        assert 'data-reload-url="/?season=2025&lang=sv"' in body
        assert '"tournament_id": 5366' in body and '"scoring": "DM"' in body
        assert '"source": "rilton"' in body and '"tournament_id": 1301929' in body
        assert '<option value="member" selected>' in body
        assert '<option value="rilton">Rilton</option>' in body

    def test_the_rilton_addition_shows_the_gp_season_beside_the_rilton_edition(self, picker_client):
        client, _, _ = picker_client

        body = client.get("/?season=2025&lang=en").get_data(as_text=True)

        assert "GP season 2025 uses Rilton 2025/2026." in body

    def test_a_season_without_a_file_starts_at_revision_0(self, picker_client):
        client, _, _ = picker_client

        body = client.get("/?season=2026").get_data(as_text=True)

        assert 'data-configuration-revision="0"' in body
        assert 'id="selected-tournaments-data">[]</script>' in body

    def test_a_first_save_survives_a_restart_and_the_summary_shows_it(self, picker_client, tmp_path):
        client, _, state_directory = picker_client
        client.post("/api/v1/configuration/tournaments?season=2026", json={
            "revision": 0, "tournaments": _entries((5400, DM)),
        })

        restarted = create_app({
            "TESTING": True,
            "STATE_DIRECTORY": state_directory,
            "OUTPUT_DIRECTORY": tmp_path / "output",
            "CLOCK": lambda: datetime(2026, 5, 31, 12, tzinfo=UTC),
        }).test_client()
        body = restarted.get("/?season=2026&lang=en").get_data(as_text=True)

        assert '<p class="text-body-secondary" hidden data-configuration-none>' in body
        assert '<p class="lead" data-configuration-intro>' in body
        assert "1 from the member system, 0 Rilton" in body
        assert '<dd class="col-sm-9" data-configuration-revision-display>1</dd>' in body
        assert '"tournament_id": 5400' in body and '"scoring": "DM"' in body


@pytest.fixture
def rollover_client(tmp_path):
    """Return a client whose clock the test moves, and the state directory, with `CONFIGURATION` saved."""
    state_directory = tmp_path / "state"
    save_configuration(state_directory, CONFIGURATION)
    clock = {"now": None}
    app = create_app({
        "TESTING": True,
        "STATE_DIRECTORY": state_directory,
        "OUTPUT_DIRECTORY": tmp_path / "output",
        "CLOCK": lambda: clock["now"],
    })
    return app.test_client(), clock, state_directory


def _season_options(body):
    """Return the season choices in order, marking the selected one with `*`."""
    options = []
    for year in ("2027", "2026", "2025", "2024"):
        if f'<option value="{year}" selected>' in body:
            options.append(f"{year}*")
        elif f'<option value="{year}">' in body:
            options.append(year)
    return options


class TestRollover:

    def test_the_default_switches_on_1_june_and_an_explicit_season_stays(self, rollover_client):
        client, clock, state_directory = rollover_client
        # 23:30 on 31 May 2026 in Stockholm, then 00:30 on 1 June.
        clock["now"] = datetime(2026, 5, 31, 21, 30, tzinfo=UTC)
        assert _season_options(client.get("/").get_data(as_text=True)) == ["2026", "2025*"]

        clock["now"] = datetime(2026, 5, 31, 22, 30, tzinfo=UTC)
        assert _season_options(client.get("/").get_data(as_text=True)) == ["2026*", "2025"]
        body = client.get("/?season=2025").get_data(as_text=True)
        assert _season_options(body) == ["2026", "2025*"]
        assert 'data-configuration-revision="1"' in body
        response = client.post(SAVE, json={"revision": 1, "tournaments": [_member(5366, GP)]})
        assert response.get_json()["data"]["revision"] == 2
        assert not configuration_path(state_directory, 2026).exists()

    def test_the_default_stays_on_2025_across_1_january_and_2024_can_no_longer_save(self, rollover_client):
        client, clock, _ = rollover_client
        # 23:30 on 31 December 2025 in Stockholm, then 00:30 on 1 January 2026.
        clock["now"] = datetime(2025, 12, 31, 22, 30, tzinfo=UTC)
        assert _season_options(client.get("/").get_data(as_text=True)) == ["2025*", "2024"]

        clock["now"] = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
        assert _season_options(client.get("/").get_data(as_text=True)) == ["2026", "2025*"]
        assert client.post("/api/v1/configuration/tournaments?season=2024",
                           json={"revision": 0, "tournaments": []}).status_code == 400

    def test_a_new_season_starts_empty_and_leaves_the_previous_season_unchanged(self, rollover_client):
        client, clock, state_directory = rollover_client
        clock["now"] = datetime(2026, 6, 1, 12, tzinfo=UTC)
        before = configuration_path(state_directory, 2025).read_bytes()

        body = client.get("/").get_data(as_text=True)

        assert 'data-configuration-revision="0"' in body
        assert 'id="selected-tournaments-data">[]</script>' in body
        assert configuration_path(state_directory, 2025).read_bytes() == before
