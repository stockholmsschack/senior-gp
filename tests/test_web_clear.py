"""Clear downloads: removing one season's generated files, as JGP's Clear downloads does for all of JGP's."""

import re

import pytest

from senior_gp.configuration import configuration_path
from senior_gp.publication import LATEST_FILE, latest_run, season_output_directory
from senior_gp.web.operations import GenerationBusyError
from tests.test_generation import SEASON
from tests.test_web_files import _publish
from tests.test_web_generation import _start, generation_app  # noqa: F401 - a fixture


@pytest.fixture
def published(generation_app, tmp_path):
    """Run 2025 from the web, and publish a run of 2026 beside it."""
    state, output = tmp_path / "state", tmp_path / "output"
    client = generation_app.test_client()
    started = _start(client).get_json()["data"]
    assert client.get(started["status_url"]).get_json()["data"]["state"] == "completed"
    _publish(output, SEASON + 1, "2026-10-26T10:00")
    return state, output


def test_clearing_a_season_removes_its_runs_and_keeps_the_rest(generation_app, published):
    state, output = published
    configuration = configuration_path(state, SEASON).read_text()
    inputs = sorted(path.relative_to(state) for path in (state / "inputs").rglob("*"))
    operations = sorted((state / "operations").glob("*.json"))
    later = latest_run(output, SEASON + 1)

    response = generation_app.test_client().post(f"/api/v1/downloads/clear?season={SEASON}")

    assert response.get_json() == {"data": {"season": SEASON, "cleared": True}}
    assert not (output / "runs" / str(SEASON)).exists()
    assert not (season_output_directory(output, SEASON) / LATEST_FILE).exists()
    assert latest_run(output, SEASON + 1) == later and later.is_dir()
    assert configuration_path(state, SEASON).read_text() == configuration
    assert sorted(path.relative_to(state) for path in (state / "inputs").rglob("*")) == inputs
    assert sorted((state / "operations").glob("*.json")) == operations
    downloads = generation_app.test_client().get("/downloads?lang=en").get_data(as_text=True)
    assert 'data-season="2025"' not in downloads and 'data-season="2026"' in downloads


def test_a_repeated_clear_and_a_clear_without_files_succeed(generation_app):
    client = generation_app.test_client()

    assert client.post(f"/api/v1/downloads/clear?season={SEASON}").status_code == 200
    assert client.post(f"/api/v1/downloads/clear?season={SEASON}").status_code == 200


@pytest.mark.parametrize("query", ["", "?season=25", "?season=two", "?season=２０２５"])
def test_a_clear_needs_a_four_digit_season(generation_app, query):
    response = generation_app.test_client().post(f"/api/v1/downloads/clear{query}")

    assert (response.status_code, response.get_json()["error"]["details"]["field"]) == (400, "season")


def test_the_clear_is_refused_while_a_generation_holds_the_lease(generation_app, published):
    _state, output = published
    store = generation_app.extensions["senior"]["generation_operations"].store
    store.acquire("abc123")
    try:
        response = generation_app.test_client().post(f"/api/v1/downloads/clear?season={SEASON}")
    finally:
        store.release("abc123")

    error = response.get_json()["error"]
    assert (response.status_code, error["code"], error["message_key"], error["details"]) == (
        409, "downloads_busy", "errors.downloads.busy", {"active_operation_id": "abc123"})
    assert latest_run(output, SEASON) is not None


def test_a_generation_is_refused_while_the_clear_holds_the_lease(generation_app, monkeypatch, published):
    manager = generation_app.extensions["senior"]["generation_operations"]
    refusals = []

    def generate_while_clearing(output_directory, season):
        with pytest.raises(GenerationBusyError) as refused:
            manager.store.acquire("abc123")
        refusals.append(refused.value.operation_id)

    monkeypatch.setattr("senior_gp.web.operations.clear_season", generate_while_clearing)
    manager.clear_season(SEASON)

    assert len(refusals) == 1 and refusals[0].startswith("clear-")
    assert not (manager.store.directory / "generation.lease").exists()


def test_a_failing_clear_answers_with_its_message_key(generation_app, monkeypatch):
    def fail(output_directory, season):
        raise OSError("permission denied")

    monkeypatch.setattr("senior_gp.web.operations.clear_season", fail)
    response = generation_app.test_client().post(f"/api/v1/downloads/clear?season={SEASON}")

    assert (response.status_code, response.get_json()["error"]["message_key"]) == (
        500, "errors.downloads.clear_failed")


def test_each_listed_season_has_a_clear_with_a_dialog_that_names_what_goes(generation_app, published):
    client = generation_app.test_client()
    english = client.get("/downloads?lang=en").get_data(as_text=True)
    swedish = client.get("/downloads?lang=sv").get_data(as_text=True)

    assert re.findall(r'data-clear-open="(\d+)"', english) == ["2026", "2025"]
    assert "Clear the downloads of season 2025?" in english
    assert "Every file of season 2025 will be removed." in english
    assert "Rensa nedladdningarna för säsongen 2025?" in swedish
    assert "data-clear-open" not in client.get("/reports?lang=en").get_data(as_text=True)


def test_an_empty_page_offers_no_clear(generation_app):
    body = generation_app.test_client().get("/downloads?lang=en").get_data(as_text=True)

    assert "No files yet." in body
    assert "data-clear-open" not in body
    assert "available-files.js" not in body


def test_clearing_a_season_whose_runs_directory_is_a_symlink_removes_the_symlink(generation_app, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    _publish(elsewhere, SEASON, "2026-10-25T10:00")
    runs = tmp_path / "output" / "runs"
    runs.mkdir(parents=True)
    (runs / str(SEASON)).symlink_to(elsewhere / "runs" / str(SEASON))

    assert generation_app.test_client().post(f"/api/v1/downloads/clear?season={SEASON}").status_code == 200

    assert not (runs / str(SEASON)).is_symlink()
    assert (elsewhere / "runs" / str(SEASON)).is_dir()
