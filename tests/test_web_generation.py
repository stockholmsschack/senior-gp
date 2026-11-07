"""Web generation: starting a run, recording its operation, and matching the CLI."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest
from typer.testing import CliRunner

from senior_gp.cli import app as cli
from senior_gp.configuration import ActiveConfiguration, save_configuration
from senior_gp.publication import latest_run
from senior_gp.service import run_generation
from senior_gp.web import create_app
from tests.test_cli import NO_NETWORK
from tests.test_generation import ACCEPTED, CAPTURE, RILTON_INPUTS, SEASON, reference_configuration, run_file, workbook_parts

ROOT = Path(__file__).resolve().parent.parent
# 25 October 2026 in Stockholm, the capture date. The choices are 2026 and 2025.
CAPTURE_TIME = datetime(2026, 10, 25, 12, tzinfo=UTC)
STAGES = ["rilton", "membership", "calculation", "publication"]


class RecordedResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def close(self):
        pass


class RecordedSession:
    """Answer the generation's requests from the capture's retained responses."""

    def request(self, method, url, timeout=None):
        body = CAPTURE / "inputs" / "http" / f"{hashlib.sha256(url.encode()).hexdigest()}.body"
        if not body.exists():
            raise ConnectionError(f"no recorded response for {url}")
        return RecordedResponse(body.read_bytes())


class ImmediateExecutor:
    """Run each submitted call at once, so a start returns after its run finishes."""

    def submit(self, function, *arguments):
        future = Future()
        future.set_result(function(*arguments))
        return future


def _retain_rilton(state_directory):
    rilton = state_directory / "inputs" / "rilton"
    rilton.mkdir(parents=True)
    for identifier, name in (("1301929", "rilton_u1800_2025_2026_1301929.TUNX"),
                             ("1301930", "rilton_u2200_2025_2026_1301930.TUNX")):
        shutil.copy(RILTON_INPUTS / name, rilton / f"{identifier}.TUNX")


@pytest.fixture
def generation_app(tmp_path):
    """Return an app with the reference configuration saved as revision 1 and its Rilton sections retained."""
    state_directory = tmp_path / "state"
    save_configuration(state_directory, replace(reference_configuration(), revision=0))
    _retain_rilton(state_directory)
    return create_app({
        "TESTING": True,
        "STATE_DIRECTORY": state_directory,
        "OUTPUT_DIRECTORY": tmp_path / "output",
        "CLOCK": lambda: CAPTURE_TIME,
        "ACTOR": lambda: {"email": "operator@example.org", "name": "Operator"},
        "GENERATION_EXECUTOR": ImmediateExecutor(),
        "GENERATION_RUNNER": partial(run_generation, session=RecordedSession()),
    })


def _start(client, revision=1, season=SEASON):
    return client.post(f"/api/v1/generation/operations?season={season}", json={"revision": revision})


def test_a_web_run_publishes_the_same_standings_as_the_cli(generation_app, tmp_path):
    client = generation_app.test_client()

    started = _start(client)
    assert started.status_code == 202
    operation = client.get(started.get_json()["data"]["status_url"]).get_json()["data"]

    assert operation["state"] == "completed"
    assert (operation["season"], operation["configuration_revision"], operation["generated_on"]) == (
        SEASON, 1, "2026-10-25")
    assert operation["actor"] == {"email": "operator@example.org", "name": "Operator"}
    assert [event["kind"] for event in operation["events"]] == ["accepted", *["stage"] * 4, "completed"]
    assert [event["parameters"]["stage"] for event in operation["events"][1:5]] == STAGES
    assert [event["progress"] for event in operation["events"][1:5]] == [
        {"completed": index, "total": 4} for index in range(4)]
    assert operation["events"][-1]["parameters"]["warnings"] == []
    web_run = latest_run(tmp_path / "output", SEASON)
    assert operation["run_id"] == web_run.name

    # The web run retained its member-system responses, so an offline CLI run reads the same inputs.
    cli_output = tmp_path / "cli-output"
    result = CliRunner().invoke(cli, ["--state-dir", str(tmp_path / "state"), "--output-dir", str(cli_output),
                                      "--season", str(SEASON), "generate", "--offline", "--date", "2026-10-25"],
                                env=NO_NETWORK)
    assert result.exit_code == 0, result.stderr
    cli_run = latest_run(cli_output, SEASON)
    assert run_file(web_run, "2025-gp-standings.json").read_text() == run_file(cli_run, "2025-gp-standings.json").read_text()
    assert run_file(web_run, "2025-gp-standings.json").read_text() == (ACCEPTED / "standings.json").read_text()
    for workbook in (ACCEPTED / "output").glob("*.xlsx"):
        assert workbook_parts(run_file(web_run, workbook.name).read_bytes()) == workbook_parts(
            run_file(cli_run, workbook.name).read_bytes())


def test_a_failed_run_names_its_stage_and_input_and_keeps_the_latest_run(generation_app, tmp_path):
    client = generation_app.test_client()
    _start(client)
    previous = latest_run(tmp_path / "output", SEASON)

    class FailingTournament(RecordedSession):
        def request(self, method, url, timeout=None):
            if "5366" in url:
                return RecordedResponse(b"not JSON")
            return super().request(method, url, timeout)

    generation_app.extensions["senior"]["generation_operations"]._runner = partial(
        run_generation, session=FailingTournament())
    # A tournament that cannot be read is left out with a warning.
    warned = client.get(_start(client).get_json()["data"]["status_url"]).get_json()["data"]
    assert warned["state"] == "completed"
    assert any("5366" in warning for warning in warned["events"][-1]["parameters"]["warnings"])

    generation_app.extensions["senior"]["generation_operations"]._runner = partial(
        run_generation, session=FailingTournament(), offline=True)
    shutil.rmtree(tmp_path / "state" / "inputs" / "http")
    failed = client.get(_start(client).get_json()["data"]["status_url"]).get_json()["data"]
    assert (failed["state"], failed["failure_stage"], failed["run_id"]) == ("failed", "membership", None)
    assert failed["events"][-1]["parameters"]["detail"].startswith("membership: no retained response")
    assert latest_run(tmp_path / "output", SEASON).name == warned["run_id"] != previous.name

    generation_app.extensions["senior"]["generation_operations"]._runner = partial(
        run_generation, session=RecordedSession())
    assert client.get(_start(client).get_json()["data"]["status_url"]).get_json()["data"]["state"] == "completed"


def test_an_older_season_without_a_run_has_no_generation_date(tmp_path):
    state_directory = tmp_path / "state"
    save_configuration(state_directory, replace(reference_configuration(), season=2024, revision=0))
    app = create_app({"TESTING": True, "STATE_DIRECTORY": state_directory, "OUTPUT_DIRECTORY": tmp_path / "output",
                      "CLOCK": lambda: CAPTURE_TIME, "DEVELOPMENT": True})
    response = _start(app.test_client(), season=2024)
    assert response.status_code == 422
    assert response.get_json()["error"] == {"code": "generation_date_unknown",
                                            "message_key": "errors.generation.date_unknown",
                                            "details": {"season": 2024}}


def test_a_season_without_tournaments_is_refused_without_an_operation(generation_app, tmp_path):
    save_configuration(tmp_path / "state", ActiveConfiguration(2026))
    response = _start(generation_app.test_client(), revision=1, season=2026)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "not_generatable"
    assert not (tmp_path / "state" / "operations").exists()


def test_a_stale_revision_is_refused(generation_app):
    response = _start(generation_app.test_client(), revision=0)
    assert response.status_code == 409
    assert response.get_json()["error"]["details"] == {"current_revision": 1}


@pytest.mark.parametrize("body", [{}, {"revision": "1"}, {"revision": -1}, [1]])
def test_a_start_without_a_valid_revision_is_refused(generation_app, body):
    response = generation_app.test_client().post(f"/api/v1/generation/operations?season={SEASON}", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"] == {"field": "revision"}


def test_an_unknown_operation_is_not_found(generation_app):
    for operation_id in ("0123abcd", "not-hex"):
        response = generation_app.test_client().get(f"/api/v1/generation/operations/{operation_id}")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "operation_not_found"


def test_generate_is_disabled_for_a_season_without_tournaments(generation_app):
    client = generation_app.test_client()
    with_tournaments = client.get(f"/?season={SEASON}&lang=en").get_data(as_text=True)
    without = client.get("/?season=2026&lang=en").get_data(as_text=True)

    assert f'data-tournament-count="{len(reference_configuration().tournaments)}"' in with_tournaments
    assert _generate_state(with_tournaments) == (False, "")
    assert 'data-tournament-count="0"' in without
    assert _generate_state(without) == (True, "Add a tournament before generating.")


def _generate_state(body):
    """Return whether Generate is disabled and the reason shown beside it."""
    button = re.search(r"<button[^>]*data-generate[^>]*>", body).group()
    reason = re.search(r"data-generation-blocked>([^<]*)</div>", body).group(1)
    return "disabled" in button, reason


def _wait_until_finished(client, status_url):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        operation = client.get(status_url).get_json()["data"]
        if operation["terminal"]:
            return operation
        time.sleep(0.05)
    raise AssertionError("the generation did not finish")


def test_a_start_during_a_run_answers_busy_and_the_run_keeps_its_snapshot(generation_app, tmp_path, request):
    proceed = threading.Event()
    # Let a held run finish when an assertion fails first.
    request.addfinalizer(proceed.set)

    def held_run(*arguments, **options):
        assert proceed.wait(30)
        return run_generation(*arguments, session=RecordedSession(), **options)

    manager = generation_app.extensions["senior"]["generation_operations"]
    manager._executor = ThreadPoolExecutor(max_workers=1)
    request.addfinalizer(manager._executor.shutdown)
    manager._runner = held_run
    client = generation_app.test_client()
    first = _start(client).get_json()["data"]

    # Leave out a tournament while the first run waits.
    saved = save_configuration(tmp_path / "state", replace(reference_configuration(),
                                                           tournaments=reference_configuration().tournaments[:-1]))
    other = save_configuration(tmp_path / "state", replace(reference_configuration(), season=2026, revision=0))
    for season, revision in ((SEASON, saved.revision), (2026, other.revision)):
        busy = _start(client, revision=revision, season=season)
        assert busy.status_code == 409
        error = busy.get_json()["error"]
        assert (error["code"], error["details"]["operation_id"]) == ("generation_busy", first["operation_id"])
        assert error["details"]["operation"]["season"] == SEASON

    proceed.set()
    finished = _wait_until_finished(client, first["status_url"])
    assert (finished["state"], finished["configuration_revision"]) == ("completed", 1)
    run = latest_run(tmp_path / "output", SEASON)
    assert json.loads(run_file(run, "2025-gp-report.json").read_text())["configuration_revision"] == 1
    assert run_file(run, "2025-gp-standings.json").read_text() == (ACCEPTED / "standings.json").read_text()
    assert len(list((tmp_path / "state" / "operations").glob("*.json"))) == 1

    # The finished run released the lease.
    second = _start(client, revision=saved.revision)
    assert second.status_code == 202
    assert _wait_until_finished(client, second.get_json()["data"]["status_url"])["configuration_revision"] == 2


def test_an_export_failure_keeps_the_latest_run_and_a_later_run_succeeds(generation_app, tmp_path):
    client = generation_app.test_client()
    _start(client)
    previous = latest_run(tmp_path / "output", SEASON)

    with mock.patch("senior_gp.generation.ExcelExporter.render", side_effect=OSError("disk full")):
        failed = client.get(_start(client).get_json()["data"]["status_url"]).get_json()["data"]
    assert (failed["state"], failed["failure_stage"]) == ("failed", "calculation")
    assert failed["events"][-1]["parameters"]["detail"] == "export: disk full"
    assert latest_run(tmp_path / "output", SEASON) == previous

    succeeded = client.get(_start(client).get_json()["data"]["status_url"]).get_json()["data"]
    assert succeeded["state"] == "completed"
    assert latest_run(tmp_path / "output", SEASON).name == succeeded["run_id"]


# Take the lease and record a running operation, then exit without releasing either.
INTERRUPTED_PROCESS = """
import sys
from senior_gp.web.operations import GenerationOperation, OperationEvent, OperationStore
store = OperationStore(sys.argv[1])
store.acquire("abc123")
store.create(GenerationOperation("abc123", "", "accepted", 2025, 1, "2026-10-25", None, 1, False,
                                 events=(OperationEvent(1, "accepted", "operations.accepted"),)))
store.transition("abc123", kind="stage", message_key="operations.stage", parameters={"stage": "membership"})
"""


def test_a_run_interrupted_by_a_stopped_process_fails_and_the_next_start_runs(generation_app, tmp_path):
    state_directory = tmp_path / "state"
    subprocess.run([sys.executable, "-c", INTERRUPTED_PROCESS, str(state_directory)], check=True)
    client = generation_app.test_client()
    assert client.get("/api/v1/generation/operations/abc123").get_json()["data"]["state"] == "running"
    assert (state_directory / "operations" / "generation.lease").exists()

    started = _start(client)
    assert started.status_code == 202
    interrupted = client.get("/api/v1/generation/operations/abc123").get_json()["data"]
    assert (interrupted["state"], interrupted["failure_stage"]) == ("failed", "interrupted")
    assert client.get(started.get_json()["data"]["status_url"]).get_json()["data"]["state"] == "completed"
    assert not (state_directory / "operations" / "generation.lease").exists()


def test_creating_the_app_fails_an_operation_interrupted_by_a_restart(generation_app, tmp_path):
    state_directory = tmp_path / "state"
    subprocess.run([sys.executable, "-c", INTERRUPTED_PROCESS, str(state_directory)], check=True)
    restarted = create_app({"TESTING": True, "STATE_DIRECTORY": state_directory,
                            "OUTPUT_DIRECTORY": tmp_path / "output", "CLOCK": lambda: CAPTURE_TIME})

    operation = restarted.test_client().get("/api/v1/generation/operations/abc123").get_json()["data"]
    assert (operation["state"], operation["failure_stage"]) == ("failed", "interrupted")
    assert not (state_directory / "operations" / "generation.lease").exists()
    assert generation_app.test_client().get(
        _start(generation_app.test_client()).get_json()["data"]["status_url"]).get_json()["data"]["state"] == "completed"


def test_a_restart_fails_an_unfinished_operation_without_a_lease(generation_app, tmp_path):
    state_directory = tmp_path / "state"
    subprocess.run([sys.executable, "-c", INTERRUPTED_PROCESS, str(state_directory)], check=True)
    (state_directory / "operations" / "generation.lease").unlink()
    restarted = create_app({"TESTING": True, "STATE_DIRECTORY": state_directory,
                            "OUTPUT_DIRECTORY": tmp_path / "output", "CLOCK": lambda: CAPTURE_TIME})

    operation = restarted.test_client().get("/api/v1/generation/operations/abc123").get_json()["data"]
    assert (operation["state"], operation["failure_stage"]) == ("failed", "interrupted")


def test_generate_names_the_season_and_the_page_has_the_progress_dialog(generation_app):
    body = generation_app.test_client().get(f"/?season={SEASON}&lang=en").get_data(as_text=True)
    assert re.search(r"data-generate[^>]*>\s*Generate season 2025\s*</button>", body)
    assert re.search(r'<div\s+class="modal fade"[^>]*data-generation-dialog', body)
    assert "data-generation-progress" in body


def test_the_operation_follower_and_its_memory():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    completed = subprocess.run([node, "tests/browser/generation-operation.mjs"], cwd=ROOT,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


class RecordingPublisher:
    """Record each publish, with the record's latest event ID on disk at that moment."""

    def __init__(self, state_directory):
        self.state_directory = state_directory
        self.published = []
        self.recorded_event_ids = []

    def publish(self, topic, operation_id, status_url, transition, operation_data):
        self.published.append((topic, operation_id, status_url, transition, operation_data))
        record = json.loads((self.state_directory / "operations" / f"{operation_id}.json").read_text())
        self.recorded_event_ids.append(record["latest_event_id"])


class FailingPublisher:
    def publish(self, *arguments):
        raise ConnectionError("the hub is down")


def _app_with_publisher(generation_app, publisher):
    settings = generation_app.extensions["senior"]["settings"]
    return create_app({**settings, "MERCURE_PUBLISHER": publisher, "MERCURE_PUBLIC_URL": "/.well-known/mercure"})


def test_a_publisher_receives_each_event_after_its_record(generation_app, tmp_path):
    publisher = RecordingPublisher(tmp_path / "state")
    client = _app_with_publisher(generation_app, publisher).test_client()

    operation = _start(client).get_json()["data"]
    recorded = client.get(operation["status_url"]).get_json()["data"]

    topic = f"https://stockholmsschack.se/senior/operations/{operation['operation_id']}"
    assert operation["topic"] == recorded["topic"] == topic
    assert [published.kind for _, _, _, published, _ in publisher.published] == [
        "accepted", *["stage"] * 4, "completed"]
    for event_id, (published_topic, operation_id, status_url, transition, data) in enumerate(publisher.published, 1):
        assert (published_topic, operation_id, status_url) == (topic, operation["operation_id"], operation["status_url"])
        assert (transition.event_id, data["latest_event_id"]) == (event_id, event_id)
    assert publisher.recorded_event_ids == [1, 2, 3, 4, 5, 6]
    assert json.loads(json.dumps(publisher.published[-1][4])) == recorded


def test_a_failing_publisher_changes_nothing(generation_app, tmp_path, caplog):
    client = _app_with_publisher(generation_app, FailingPublisher()).test_client()

    started = _start(client)
    assert started.status_code == 202
    operation = client.get(started.get_json()["data"]["status_url"]).get_json()["data"]

    assert operation["state"] == "completed"
    assert operation["run_id"] == latest_run(tmp_path / "output", SEASON).name
    assert "cannot publish event" in caplog.text


def test_the_page_subscribes_to_the_hub_only_with_a_publisher(generation_app):
    without = generation_app.test_client().get(f"/?season={SEASON}").get_data(as_text=True)
    hub_only = create_app({**generation_app.extensions["senior"]["settings"],
                           "MERCURE_PUBLIC_URL": "/.well-known/mercure"}).test_client()
    with_publisher = _app_with_publisher(generation_app, RecordingPublisher(None)).test_client()

    assert 'data-mercure-hub=""' in without
    assert 'data-mercure-hub=""' in hub_only.get(f"/?season={SEASON}").get_data(as_text=True)
    assert 'data-mercure-hub="/.well-known/mercure"' in with_publisher.get(f"/?season={SEASON}").get_data(as_text=True)
