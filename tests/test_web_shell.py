"""The standalone pages and the `senior-web` entry point."""

from datetime import UTC, datetime
from pathlib import Path
import re
import tomllib
from unittest.mock import Mock, patch

import pytest

from senior_gp.configuration import DM, GP, MEMBER_SYSTEM, RILTON, ActiveConfiguration, Tournament, save_configuration
from senior_gp.web import create_app
from senior_gp.web.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
CONFIGURATION = ActiveConfiguration(2025, (
    Tournament(RILTON, "1301929", "Rilton U1800", GP),
    Tournament(MEMBER_SYSTEM, "5366", "Stockholmsmästerskapet", DM),
))
# 31 May 2026 in Stockholm: the last day on which 2025 is the default season.
CLOCK = lambda: datetime(2026, 5, 31, 12, tzinfo=UTC)  # noqa: E731


@pytest.fixture
def make_client(tmp_path):
    def make(configuration=CONFIGURATION, **settings):
        state_directory = tmp_path / "state"
        if configuration is not None:
            save_configuration(state_directory, configuration)
        app = create_app({
            "TESTING": True,
            "STATE_DIRECTORY": state_directory,
            "OUTPUT_DIRECTORY": tmp_path / "output",
            "CLOCK": CLOCK,
            **settings,
        })
        return app.test_client()
    return make


def _body(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


class TestOverview:

    @pytest.mark.parametrize("lang, heading", [("sv", "Turneringar"), ("en", "Tournaments")])
    def test_the_summary_names_the_season_and_lists_both_sources_in_order(self, make_client, lang, heading):
        body = _body(make_client(), f"/?lang={lang}")

        assert f'<html lang="{lang}">' in body
        assert "<h1>Senior GP 2025</h1>" in body
        assert re.search(r"<title>Senior GP 2025 · ", body)
        assert '<dd class="col-sm-9">2025</dd>' in body
        assert {"sv": "1 från medlemssystemet, 1 Rilton", "en": "1 from the member system, 1 Rilton"}[lang] in body
        picker = body[body.index(f'id="tournaments-heading">{heading}<'):]
        rilton, member = picker.index('"tournament_id": 1301929'), picker.index('"tournament_id": 5366')
        assert rilton < member
        assert '"name": "Rilton U1800"' in picker and '"scoring": "DM"' in picker

    def test_swedish_is_the_default(self, make_client):
        assert '<html lang="sv">' in _body(make_client(), "/")

    def test_a_season_without_a_file_says_so(self, make_client):
        body = _body(make_client(configuration=None), "/?lang=en")

        assert "<h1>Senior GP 2025</h1>" in body
        assert "Season 2025 has no configuration yet." in body
        assert '<p class="lead" hidden data-configuration-intro>' in body
        assert "0 from the member system, 0 Rilton" in body

    def test_an_invalid_configuration_lists_its_problems(self, make_client, tmp_path):
        client = make_client()
        path = tmp_path / "state" / "seasons" / "2025" / "active-configuration.toml"
        path.write_bytes(b"\xff")
        body = _body(client, "/?lang=en")

        assert "The active configuration cannot be used." in body
        assert "cannot read active configuration" in body

    def test_the_season_query_selects_another_season_and_survives_a_language_change(self, make_client):
        body = _body(make_client(), "/?lang=en&season=2026")

        assert "<h1>Senior GP 2026</h1>" in body
        assert "Season 2026 has no configuration yet." in body
        assert '<option value="2026" selected>2026</option>' in body
        assert '<input type="hidden" name="season" value="2026">' in body

    @pytest.mark.parametrize("development, choices", [(False, ["2026", "2025"]), (True, ["2026", "2025", "2024"])])
    def test_the_year_choices_follow_the_development_setting(self, make_client, development, choices):
        client = make_client(DEVELOPMENT=development)
        body = _body(client, "/")

        assert re.findall(r'<option value="(\d{4})"', body) == choices
        assert client.get("/?season=2023").status_code == 404
        assert client.get("/?season=next").status_code == 404

    def test_every_asset_is_bundled_and_served(self, make_client):
        client = make_client()
        body = _body(client, "/")

        assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', body)
        assert sorted(assets) == ["/static/css/app.css", "/static/css/bootstrap.min.css",
                                  "/static/js/bootstrap.bundle.min.js", "/static/js/generation.js",
                                  "/static/js/tournament-search.js"]
        # Follow the modules' relative imports, such as lit-html.
        pending, served = list(assets), set()
        while pending:
            asset = pending.pop()
            response = client.get(asset)
            assert response.status_code == 200, asset
            served.add(asset)
            if asset.endswith(".js"):
                imports = re.findall(r'from "\./([^"]+)"', response.get_data(as_text=True))
                pending += [f"/static/js/{name}" for name in imports if f"/static/js/{name}" not in served]
        assert "/static/js/lit-html.js" in served

    def test_the_files_origin_defaults_to_the_local_caddy_origin(self, make_client, monkeypatch):
        monkeypatch.delenv("SENIOR_FILES_PUBLIC_ORIGIN", raising=False)
        app = make_client().application

        assert app.extensions["senior"]["settings"]["FILES_PUBLIC_ORIGIN"] == "http://senior.localhost:5000"


class TestEntryPoint:

    def test_the_defaults_bind_to_loopback_with_the_local_directories(self):
        application = Mock()
        with patch("senior_gp.web.__main__.create_app", return_value=application) as factory:
            main([])

        application.run.assert_called_once_with(host="127.0.0.1", port=9001, debug=False)
        assert factory.call_args.args[0] == {
            "STATE_DIRECTORY": Path("state"), "OUTPUT_DIRECTORY": Path("output"), "DEVELOPMENT": False,
        }

    def test_debug_restarts_when_a_catalogue_changes_and_offers_development_years(self):
        application = Mock()
        with patch("senior_gp.web.__main__.create_app", return_value=application) as factory:
            main(["--debug"])

        assert factory.call_args.args[0]["DEVELOPMENT"] is True

        run_options = application.run.call_args.kwargs
        assert run_options["debug"] is True
        assert {path.name for path in run_options["extra_files"]} == {"en.json", "sv.json"}

    def test_the_senior_web_command_is_declared(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())

        assert project["project"]["scripts"]["senior-web"] == "senior_gp.web.__main__:main"
