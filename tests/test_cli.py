"""Check the installed `senior` command against the accepted 2025 reference."""

from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from typer.testing import CliRunner

from senior_gp.chess_results import RetrievedTunx
from senior_gp.cli import app
from senior_gp.configuration import configuration_path, save_configuration
from senior_gp.publication import latest_run, season_output_directory
from tests.test_generation import ACCEPTED, CAPTURE, RILTON_INPUTS, SEASON, reference_configuration, run_file, workbook_parts

SENIOR = Path(sys.executable).parent / "senior"
CAPTURE_DAY = "2026-10-25"
# Any request through these proxies fails, so a test cannot reach the network by accident.
RETRIEVED = RetrievedTunx("1301929", "Rilton U1800", b"TUNX", "https://chess-results.com/tnr1301929.aspx",
                          "https://chess-results.com/DownloadTurnier.aspx?art=1", None, "2026-10-25T00:00:00+00:00")
NO_NETWORK = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / "state"
        self.output = self.root / "output"
        save_configuration(self.state, replace(reference_configuration(), revision=0))

    def retain_reference_inputs(self, rilton=True):
        """Copy the captured responses and TUNX files into the retained-input layout."""
        shutil.copytree(CAPTURE / "inputs" / "http", self.state / "inputs" / "http")
        if rilton:
            (self.state / "inputs" / "rilton").mkdir()
            for identifier, name in (("1301929", "rilton_u1800_2025_2026_1301929.TUNX"),
                                     ("1301930", "rilton_u2200_2025_2026_1301930.TUNX")):
                shutil.copy(RILTON_INPUTS / name, self.state / "inputs" / "rilton" / f"{identifier}.TUNX")

    def invoke(self, *arguments):
        return CliRunner().invoke(app, ["--state-dir", str(self.state), "--output-dir", str(self.output),
                                        "--season", str(SEASON), *arguments], env=NO_NETWORK)


class OfflineReplayTests(CliTestCase):
    def test_installed_command_outside_the_checkout_reproduces_the_accepted_result(self):
        self.retain_reference_inputs()
        completed = subprocess.run(
            [SENIOR, "--season", str(SEASON), "generate", "--offline", "--date", CAPTURE_DAY], cwd=self.root,
            env={**os.environ, **NO_NETWORK}, capture_output=True, text=True, check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("Warning:", completed.stderr)
        published = latest_run(self.output, SEASON)
        self.assertEqual(completed.stdout, f"{published.resolve()}\n")
        self.assertEqual(run_file(published, "2025-gp-standings.json").read_text(), (ACCEPTED / "standings.json").read_text())
        for workbook in (ACCEPTED / "output").glob("*.xlsx"):
            self.assertEqual(workbook_parts(run_file(published, workbook.name).read_bytes()),
                             workbook_parts(workbook.read_bytes()), workbook.name)
        self.assertEqual(json.loads(run_file(published, "2025-gp-report.json").read_text())["warnings"], [])


class GenerationDateTests(CliTestCase):
    def invoke_on(self, today, *arguments):
        with mock.patch("senior_gp.cli.stockholm_today", return_value=date.fromisoformat(today)):
            return self.invoke(*arguments)

    def report(self):
        return json.loads(run_file(latest_run(self.output, SEASON), "2025-gp-report.json").read_text())

    def test_a_season_from_last_year_generates_at_todays_stockholm_date(self):
        self.retain_reference_inputs()
        result = self.invoke_on(CAPTURE_DAY, "generate", "--offline")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertEqual(self.report()["generated_on"], CAPTURE_DAY)

    def test_a_historical_season_replays_at_the_date_of_its_latest_run(self):
        self.retain_reference_inputs()
        self.assertEqual(self.invoke("generate", "--offline", "--date", CAPTURE_DAY).exit_code, 0)
        result = self.invoke_on("2027-06-01", "generate", "--offline")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertIn(f"Generating season {SEASON}, which is older than last year, at {CAPTURE_DAY}", result.stderr)
        self.assertEqual(self.report()["generated_on"], CAPTURE_DAY)

    def test_a_historical_season_without_a_run_needs_a_date(self):
        result = self.invoke_on("2027-06-01", "generate", "--offline")
        self.assertEqual(result.exit_code, 2)
        self.assertIn(f"season {SEASON} is older than last year and has no run.", result.stderr)
        self.assertIsNone(latest_run(self.output, SEASON))

    def test_a_historical_season_with_an_unreadable_latest_run_fails(self):
        latest = season_output_directory(self.output, SEASON) / "latest.json"
        latest.parent.mkdir(parents=True)
        latest.write_text("{")
        result = self.invoke_on("2027-06-01", "generate", "--offline")
        self.assertEqual(result.exit_code, 1)
        self.assertIn(f"Error: cannot read the date of season {SEASON}'s latest run", result.stderr)


class FailureTests(CliTestCase):
    def test_validate_reports_every_problem(self):
        self.assertEqual(self.invoke("validate").exit_code, 0)
        configuration_path(self.state, SEASON).write_text(
            configuration_path(self.state, SEASON).read_text().replace('scoring = "GP"', 'scoring = "XX"', 1)
            .replace("season = 2025", "season = 25"))
        result = self.invoke("validate")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("cannot be used:", result.stderr)
        self.assertIn("season must be a four-digit year, not 25", result.stderr)
        self.assertIn("scoring must be one of GP, DM", result.stderr)

    def test_validate_reports_a_file_that_is_not_utf8(self):
        configuration_path(self.state, SEASON).write_bytes(b"\xff\xfe season = 2025")
        result = self.invoke("validate")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("cannot be used:", result.stderr)
        self.assertIn("cannot read active configuration: 'utf-8' codec can't decode", result.stderr)

    def test_validate_reports_a_rilton_name_that_is_not_text(self):
        configuration_path(self.state, SEASON).write_text(
            configuration_path(self.state, SEASON).read_text().replace('name = "Rilton U1800"', "name = 5", 1))
        result = self.invoke("validate")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("tournament '1301929': name is required", result.stderr)

    def test_offline_run_without_retained_rilton_leaves_out_rilton(self):
        self.retain_reference_inputs(rilton=False)
        result = self.invoke("generate", "--offline", "--date", CAPTURE_DAY)
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertIn("Warning: Rilton: left out: no retained TUNX file for Rilton section 1301930 (Rilton U2200)",
                      result.stderr)
        report = json.loads(run_file(latest_run(self.output, SEASON), "2025-gp-report.json").read_text())
        self.assertEqual(len(report["included"]), 3)
        self.assertEqual(len(report["warnings"]), 1)

    def test_offline_run_without_rating_lists_fails_at_membership(self):
        self.retain_reference_inputs()
        shutil.rmtree(self.state / "inputs" / "http")
        result = self.invoke("generate", "--offline", "--date", CAPTURE_DAY)
        self.assertEqual(result.exit_code, 1)
        self.assertRegex(result.stderr, r"Generation failed at membership: no retained response for https://")
        self.assertIsNone(latest_run(self.output, SEASON))

    def test_a_season_without_tournaments_cannot_generate(self):
        path = configuration_path(self.state, SEASON)
        path.write_text(path.read_text().split("[[tournaments]]")[0])
        self.assertEqual(self.invoke("validate").exit_code, 0)
        result = self.invoke("generate", "--offline", "--date", CAPTURE_DAY)
        self.assertEqual(result.exit_code, 1)
        self.assertIn(f"Generation failed at configuration: season {SEASON} has no tournaments", result.stderr)
        self.assertIsNone(latest_run(self.output, SEASON))

    def test_invalid_arguments_exit_with_status_2(self):
        for arguments in (("generate", "--date", "25 October"), ("generate", "--offline", "--refresh-rilton"),
                          ("fetch-rilton", "https://example.com/tnr1.aspx")):
            with self.subTest(arguments):
                self.assertEqual(self.invoke(*arguments).exit_code, 2)

    def test_fetch_rilton_refuses_an_unconfigured_tournament(self):
        result = self.invoke("fetch-rilton", "https://s3.chess-results.com/tnr967028.aspx?lan=1")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Chess-results tournament 967028 is not a configured Rilton section", result.stderr)

    def test_fetch_rilton_reports_a_failed_save(self):
        self.block_rilton_directory()
        with mock.patch("senior_gp.cli.fetch_tunx", return_value=RETRIEVED):
            result = self.invoke("fetch-rilton", "1301929")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Error: cannot save the retained copy:", result.stderr)

    def test_generate_reports_a_failed_save_and_publishes_nothing(self):
        self.block_rilton_directory()
        with mock.patch("senior_gp.service.fetch_tunx", return_value=RETRIEVED):
            result = self.invoke("generate", "--refresh-rilton")
        self.assertEqual(result.exit_code, 1)
        self.assertRegex(result.stderr, r"^Error: cannot save a Rilton section: .*\nNothing was published")
        self.assertIsNone(latest_run(self.output, SEASON))

    def test_unwritable_output_fails_at_publication(self):
        self.retain_reference_inputs()
        self.output.write_text("")
        result = self.invoke("generate", "--offline", "--date", CAPTURE_DAY)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Generation failed at publication:", result.stderr)

    def block_rilton_directory(self):
        """Put a file where the Rilton directory belongs, so retaining a section fails."""
        (self.state / "inputs").mkdir()
        (self.state / "inputs" / "rilton").write_text("")

if __name__ == "__main__":
    unittest.main()
