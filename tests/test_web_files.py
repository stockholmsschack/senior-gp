"""Available files and Reports: what they list, and links that the host's file server resolves."""

from datetime import UTC, date, datetime
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from flask import abort, send_from_directory
import pytest

from senior_gp.generation import GenerationResult
from senior_gp.publication import publish
from senior_gp.web import create_app
from senior_gp.standings_generator.excel_exporter import workbook_names
from tests.test_web_hosting import PREFIX, _host, _signed_in
from tests.test_web_shell import CLOCK

ORIGIN = "http://senior.localhost:5000"


def _publish(output, season, published_at, day=date(2026, 10, 25)):
    """Publish a run with placeholder workbooks at the UTC time `published_at` and return its directory."""
    validation, clean = workbook_names(season, day)
    result = GenerationResult(season, day, 1, {}, {clean: f"clean {published_at}".encode(),
                                                   validation: f"validation {published_at}".encode()})
    return publish(result, output, published_at=datetime.fromisoformat(published_at).replace(tzinfo=UTC))


def _links(body):
    return re.findall(r'<a class="btn btn-primary btn-sm" href="([^"]+)"', body)


def _rows(body):
    """Return each row's season and the text of its file cell."""
    return [(int(season), " ".join(re.sub(r"<[^>]+>", " ", file).split()))
            for season, file in re.findall(r'<tr data-season="\d+">\s*<td>(\d+)</td>\s*<td>(.*?)</td>', body, re.S)]


@pytest.fixture
def standalone(tmp_path):
    return create_app({"TESTING": True, "STATE_DIRECTORY": tmp_path / "state", "OUTPUT_DIRECTORY": tmp_path / "output",
                       "FILES_PUBLIC_ORIGIN": ORIGIN, "CLOCK": CLOCK})


def test_standalone_links_name_files_that_caddy_serves_from_output_runs(standalone, tmp_path):
    output = tmp_path / "output"
    older = _publish(output, 2025, "2026-10-24T09:00")
    latest = _publish(output, 2025, "2026-10-25T10:00")
    client = standalone.test_client()

    downloads = client.get("/downloads?lang=en").get_data(as_text=True)
    reports = client.get("/reports?lang=en").get_data(as_text=True)

    assert _rows(downloads) == [(2025, "Standings workbook Latest run"), (2025, "Standings workbook")]
    assert _rows(reports) == [(2025, "Validation workbook Latest run"), (2025, "Validation workbook")]
    # Each file's suffix dates its row in Stockholm time, which left summer time at 01:00 UTC that day.
    assert '<time datetime="2026-10-25T11:00:00+01:00">' in downloads
    for category, body, run in (("downloads", downloads, latest), ("reports", reports, latest),
                                ("downloads", downloads, older)):
        links = [link for link in _links(body) if f"/{run.name}/" in link]
        assert links
        for link in links:
            # The workspace Caddyfile strips /downloads or /reports and serves the rest from output/runs.
            assert link.startswith(f"{ORIGIN}/{category}/2025/{run.name}/")
            relative = unquote(urlsplit(link).path.removeprefix(f"/{category}/"))
            assert (output / "runs" / relative).read_bytes() == (run / Path(relative).name).read_bytes()
    assert {Path(link).name for link in _links(downloads) if older.name in link} == {
        "2025-gp-standings-20261024T090000Z.xlsx"}
    assert {Path(link).name for link in _links(reports) if latest.name in link} == {
        "2025-gp-standings-validations-20261025T100000Z.xlsx"}


def test_prefixed_links_retrieve_the_files_through_the_hosts_file_route(tmp_path):
    host = _host(tmp_path)
    output = tmp_path / "output"

    @host.get("/files/senior/<category>/<path:filename>")
    def serve_file(category, filename):
        """Serve output/runs at both categories, like Verktyg's file route."""
        if category not in ("downloads", "reports"):
            abort(404)
        return send_from_directory(output / "runs", filename, as_attachment=True)

    run = _publish(output, 2025, "2026-10-25T10:00")
    client = _signed_in(host)

    for page, names in (("downloads", {"2025-gp-standings-20261025T100000Z.xlsx"}),
                        ("reports", {"2025-gp-standings-validations-20261025T100000Z.xlsx"})):
        body = client.get(f"{PREFIX}/{page}").get_data(as_text=True)
        assert f'href="{PREFIX}/{page}?lang=sv"' in body
        links = _links(body)
        assert {Path(link).name for link in links} == names
        for link in links:
            assert link.startswith(f"/files/senior/{page}/2025/{run.name}/")
            response = client.get(link)
            assert response.status_code == 200
            assert response.data == (run / Path(link).name).read_bytes()


def test_listings_show_every_season_and_leave_out_everything_else(standalone, tmp_path):
    output = tmp_path / "output"
    run_2025 = _publish(output, 2025, "2026-10-25T10:00")
    run_2023 = _publish(output, 2023, "2024-03-01T10:00", day=date(2024, 3, 1))
    run_2026 = _publish(output, 2026, "2026-10-26T10:00")
    # A staging directory, a symlinked run, a file of another season, a file with a date suffix, a file with an
    # impossible time, an unknown file and a directory that is not a year.
    staging = output / "runs" / "2026" / ".20261027T100000000000Z.abc"
    staging.mkdir()
    (staging / "2026-gp-standings-20261027T100000Z.xlsx").write_bytes(b"staged")
    (output / "runs" / "2026" / "20261027T100000000000Z").symlink_to(run_2026)
    (run_2026 / "2025-gp-standings-20261026T100000Z.xlsx").write_bytes(b"wrong season")
    (run_2026 / "2026-gp-standings-20261026.xlsx").write_bytes(b"date suffix")
    (run_2026 / "2026-gp-standings-20261399T100000Z.xlsx").write_bytes(b"month 13")
    (run_2026 / "notes.txt").write_text("notes")
    legacy = output / "runs" / "legacy"
    legacy.mkdir()
    (legacy / "2026-gp-standings-20261026T100000Z.xlsx").write_bytes(b"legacy")

    downloads = standalone.test_client().get("/downloads?lang=en").get_data(as_text=True)

    assert [season for season, _file in _rows(downloads)] == [2026, 2025, 2023]
    assert all("Latest run" in file for _season, file in _rows(downloads))
    assert sorted(urlsplit(link).path for link in _links(downloads)) == sorted(
        f"/downloads/{run.parent.name}/{run.name}/{season}-gp-standings-{run.name[:15]}Z.xlsx"
        for season, run in ((2026, run_2026), (2025, run_2025), (2023, run_2023)))


@pytest.mark.parametrize("page, lang, message", [
    ("downloads", "en", "No files yet. Each generation adds its standings workbook here."),
    ("reports", "sv", "Inga rapporter ännu. Varje generering lägger till sitt valideringsblad här."),
])
def test_an_empty_listing_says_what_will_appear(standalone, page, lang, message):
    body = standalone.test_client().get(f"/{page}?lang={lang}").get_data(as_text=True)

    assert message in body
    assert "<table" not in body


def test_the_overview_links_both_listings_for_a_host_shell_without_senior_navigation(tmp_path):
    body = _signed_in(_host(tmp_path)).get(f"{PREFIX}/").get_data(as_text=True)

    # The page's script links a completed run to Available files.
    assert f'data-files-url="{PREFIX}/downloads?lang=sv"' in body
    assert f'<a href="{PREFIX}/downloads?lang=sv">Tillgängliga filer</a>' in body
    assert f'<a href="{PREFIX}/reports?lang=sv">Rapporter</a>' in body
