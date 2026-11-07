"""Check the generation service against the accepted 2025 reference."""

from dataclasses import replace
from datetime import date
import hashlib
from io import BytesIO
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import zipfile

from tests.test_tunx import config_offset, pairing_offset, patched
from senior_gp.tunx.constants import CONFIG_OFFSET_CURRENT_ROUND, CONFIG_OFFSET_TIEBREAKS

from senior_gp.configuration import (
    RILTON, ActiveConfiguration, ConfigurationValidationError, StaleConfigurationError, Tournament,
    by_date_of_play, configuration_path, load_configuration, save_configuration,
)
from senior_gp.generation import (
    GenerationError, GenerationResult, Membership, MemberSystemClient, TunxRiltonSections, XlsRiltonSections,
    generate,
)
from senior_gp.publication import generate_and_publish, latest_run, publish, season_runs_directory, standings_document
from senior_gp.standings_generator.excel_exporter import ExcelExporter

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "reference-artifacts" / "current-config-2025"
ACCEPTED = ROOT / "reference-artifacts" / "accepted-2025" / "expected"
CAPTURE_DAY = date(2026, 10, 25)
SEASON = 2025
RILTON_INPUTS = CAPTURE / "inputs" / "rilton"


class RecordedSession:
    """Answer GET requests from the capture's retained HTTP responses."""

    def get(self, url, timeout=None):
        body = CAPTURE / "inputs" / "http" / f"{hashlib.sha256(url.encode()).hexdigest()}.body"
        if not body.exists():
            raise ConnectionError(f"no recorded response for {url}")
        return RecordedResponse(body.read_bytes())


class RecordedResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


def reference_configuration() -> ActiveConfiguration:
    """Return the captured 2025 configuration with both Rilton sections, each with its first day of play."""
    captured = json.loads((CAPTURE / "inputs" / "tournaments.json").read_text())["tournaments"]
    member = tuple(Tournament("member", t["id"], t["name"], "DM" if t["dm"] else "GP",
                              start_date=REFERENCE_START_DATES[t["id"]]) for t in captured)
    rilton = (Tournament(RILTON, "1301929", "Rilton U1800", start_date=date(2026, 1, 2)),
              Tournament(RILTON, "1301930", "Rilton U2200", rating_floor=1800, start_date=date(2025, 12, 27)))
    return ActiveConfiguration(SEASON, by_date_of_play(rilton + member), revision=1)


# The start dates that the member system gives for the captured tournaments.
REFERENCE_START_DATES = {"5366": date(2025, 3, 3), "5382": date(2025, 3, 21), "5383": date(2025, 5, 18)}


def reference_membership() -> Membership:
    """Return the membership lists retained with the accepted outputs."""
    data = ACCEPTED / "data"
    return Membership(
        january=tuple(json.loads((data / "ratings_list-2025.json").read_text())),
        joined=tuple(json.loads((data / "remainder.json").read_text())["members"]),
    )


def reference_sources():
    """Return member-system and TUNX Rilton sources backed by retained inputs."""
    rilton = TunxRiltonSections({
        "1301929": RILTON_INPUTS / "rilton_u1800_2025_2026_1301929.TUNX",
        "1301930": RILTON_INPUTS / "rilton_u2200_2025_2026_1301930.TUNX",
    })
    return MemberSystemClient(RecordedSession()), rilton


def xls_sources():
    """Return the reference sources with Rilton read from the retained XLS exports."""
    rilton = XlsRiltonSections({
        "1301929": RILTON_INPUTS / "rilton-u1800-2025.xls",
        "1301930": RILTON_INPUTS / "rilton-u2200-2025.xls",
    })
    return MemberSystemClient(RecordedSession()), rilton


def workbook_parts(content: bytes) -> dict:
    """Return workbook parts except the creation timestamp."""
    with zipfile.ZipFile(BytesIO(content)) as workbook:
        return {name: workbook.read(name) for name in workbook.namelist() if name != "docProps/core.xml"}


def run_file(run: Path, name: str) -> Path:
    """Return the run's file named like `name`, such as `2025-gp-report.json` or an accepted workbook's dated name,
    with the run's UTC time suffix in place of any date."""
    path = Path(re.sub(r"-\d{8}(?=\.)", "", name))
    match, = [file for file in run.iterdir()
              if re.fullmatch(rf"{re.escape(path.stem)}-\d{{8}}T\d{{6}}Z{re.escape(path.suffix)}", file.name)]
    return match

class AcceptedReferenceTests(unittest.TestCase):
    def test_tunx_and_xls_inputs_reproduce_accepted_outputs(self):
        for sources in (reference_sources, xls_sources):
            with self.subTest(sources.__name__):
                member_system, rilton = sources()
                result = generate(reference_configuration(), reference_membership(), member_system, rilton,
                                  today=CAPTURE_DAY)

                self.assertEqual(standings_document(result.standings), (ACCEPTED / "standings.json").read_text())
                expected = sorted(path.name for path in (ACCEPTED / "output").glob("*.xlsx"))
                self.assertEqual(sorted(result.workbooks), expected)
                for name in expected:
                    self.assertEqual(workbook_parts(result.workbooks[name]),
                                     workbook_parts((ACCEPTED / "output" / name).read_bytes()), name)


def test_a_single_rilton_section_generates_without_the_other():
    configuration = reference_configuration()
    configuration = replace(configuration, tournaments=tuple(
        tournament for tournament in configuration.tournaments if tournament.id != "1301930"
    ))
    member_system, rilton = reference_sources()

    result = generate(configuration, reference_membership(), member_system, rilton, today=CAPTURE_DAY)

    assert result.included == ("member:5366", "member:5382", "member:5383", "rilton:1301929")
    assert result.skipped == () and result.warnings == ()
    assert any("rilton" in standing.tournament_results
               for players in result.standings.values() for standing in players.values())


def test_events_count_and_list_by_date_of_play():
    configuration = reference_configuration()
    # Move both Rilton sections between Compo Cup (21 March) and the blitz championship (18 May).
    april = {"1301930": date(2025, 4, 5), "1301929": date(2025, 4, 12)}
    configuration = replace(configuration, tournaments=tuple(
        replace(tournament, start_date=april.get(tournament.id, tournament.start_date))
        for tournament in configuration.tournaments
    ))
    member_system, rilton = reference_sources()

    result = generate(configuration, reference_membership(), member_system, rilton, today=CAPTURE_DAY)

    assert result.included == ("member:5366", "member:5382", "rilton:1301930", "rilton:1301929", "member:5383")
    # The Turneringar sheet lists `included`, and the class sheets' columns follow the same order.
    by_key = {tournament.key: tournament for tournament in configuration.tournaments}
    exporter = ExcelExporter(result.standings, SEASON, [by_key[key] for key in result.included])
    assert exporter.tournament_columns("C") == ["5366", "5382", "rilton", "5383"]


def with_scoring(configuration: ActiveConfiguration, tournament_id: str, scoring: str) -> ActiveConfiguration:
    """Return the configuration with one tournament's scoring type changed."""
    return replace(configuration, tournaments=tuple(
        replace(t, scoring=scoring) if t.id == tournament_id else t for t in configuration.tournaments
    ))


class StateTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "state"
        self.output = Path(directory.name) / "output"
        self.saved = save_configuration(self.state, replace(reference_configuration(), revision=0))

    def generate_saved(self):
        member_system, rilton = reference_sources()
        return generate(load_configuration(self.state, SEASON), reference_membership(), member_system, rilton,
                        today=CAPTURE_DAY)


class ScoringOverrideTests(StateTestCase):
    def test_saved_override_decides_allocation(self):
        # Compo Cup (5382) is GP in the reference; DM extends the points to places 11-15
        saved = save_configuration(self.state, with_scoring(self.saved, "5382", "DM"))
        self.assertEqual((saved.revision, load_configuration(self.state, SEASON).revision), (2, 2))
        compo = [player.tournament_results["5382"] for players in self.generate_saved().standings.values()
                 for player in players.values() if "5382" in player.tournament_results]
        self.assertEqual(max(result.standings_points for result in compo), 15)
        self.assertTrue(any(result.rank == 15 and result.standings_points == 1 for result in compo))

        save_configuration(self.state, with_scoring(saved, "5382", "GP"))
        self.assertEqual(standings_document(self.generate_saved().standings),
                         (ACCEPTED / "standings.json").read_text())

    def test_stale_save_keeps_stored_configuration(self):
        save_configuration(self.state, with_scoring(self.saved, "5382", "DM"))
        stored = configuration_path(self.state, SEASON).read_text()
        with self.assertRaisesRegex(StaleConfigurationError, "revision 1 is stale; current revision is 2"):
            save_configuration(self.state, with_scoring(self.saved, "5366", "GP"))
        self.assertEqual(configuration_path(self.state, SEASON).read_text(), stored)

    def test_invalid_save_reports_every_problem_and_keeps_stored_configuration(self):
        stored = configuration_path(self.state, SEASON).read_text()
        invalid = replace(self.saved, tournaments=self.saved.tournaments + (
            Tournament(RILTON, "1400000", "Rilton Open", rating_floor=0),
            Tournament("member", "5382", "Compo Cup 2025", "DM"),
        ))
        invalid = with_scoring(invalid, "1301929", "DM")
        with self.assertRaises(ConfigurationValidationError) as raised:
            save_configuration(self.state, invalid)
        self.assertEqual(len(raised.exception.problems), 3)
        self.assertRegex(str(raised.exception), "Rilton always scores as GP")
        self.assertRegex(str(raised.exception), "configured twice")
        self.assertRegex(str(raised.exception), "'1400000': rating floor must be a positive whole number")
        self.assertEqual(configuration_path(self.state, SEASON).read_text(), stored)


class CompleteGenerationTests(StateTestCase):
    def setUp(self):
        super().setUp()
        self.publish_saved()
        self.previous = latest_run(self.output, SEASON)
        self.previous_files = {path.name: path.read_bytes() for path in self.previous.iterdir()}
        self.stored = configuration_path(self.state, SEASON).read_text()

    def publish_saved(self, rilton=None):
        member_system, reference_rilton = reference_sources()
        return generate_and_publish(self.state, self.output, reference_membership(), member_system,
                                    rilton or reference_rilton, season=SEASON, today=CAPTURE_DAY)

    def rilton_with_u2200(self, content: bytes) -> TunxRiltonSections:
        """Return Rilton sources with the U2200 file replaced by `content`."""
        path = self.state.parent / "u2200.TUNX"
        path.write_bytes(content)
        rilton = reference_sources()[1]
        rilton.files["1301930"] = path
        return rilton

    def assert_previous_result_kept(self):
        self.assertEqual(latest_run(self.output, SEASON), self.previous)
        self.assertEqual({path.name: path.read_bytes() for path in self.previous.iterdir()}, self.previous_files)
        self.assertEqual(len(list(season_runs_directory(self.output, SEASON).iterdir())), 1)
        self.assertEqual(configuration_path(self.state, SEASON).read_text(), self.stored)

    def test_published_run_holds_workbooks_and_reports_with_one_time_suffix(self):
        file_time = self.previous.name[:15] + "Z"
        self.assertEqual(sorted(self.previous_files), sorted(f"2025-gp-{name}-{file_time}.{suffix}" for name, suffix in (
            ("standings", "xlsx"), ("standings-validations", "xlsx"), ("report", "json"), ("standings", "json"))))
        report = json.loads(self.previous_files[f"2025-gp-report-{file_time}.json"])
        self.assertEqual(report["generated_on"], CAPTURE_DAY.isoformat())
        self.assertEqual(report["configuration_revision"], 1)
        self.assertEqual(len(report["included"]), 5)
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["workbooks"], [f"2025-gp-standings-{file_time}.xlsx",
                                               f"2025-gp-standings-validations-{file_time}.xlsx"])

    def report(self, run):
        return json.loads(run_file(run, "2025-gp-report.json").read_text())

    def test_a_run_of_another_season_keeps_this_seasons_latest_run(self):
        later = GenerationResult(SEASON + 1, CAPTURE_DAY, 1, {}, {"later.xlsx": b"later"})
        run = publish(later, self.output)
        self.assertEqual(run.parent, season_runs_directory(self.output, SEASON + 1))
        self.assertEqual(latest_run(self.output, SEASON + 1), run)
        self.assert_previous_result_kept()

    def test_unreachable_tournament_is_left_out_with_warning(self):
        missing = Tournament("member", "999999", "Missing Cup")
        save_configuration(self.state, replace(self.saved, tournaments=self.saved.tournaments + (missing,)))
        warnings = self.report(self.publish_saved())["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertRegex(warnings[0], r"^tournament 999999 \(Missing Cup\): left out: no recorded response")
        self.assertEqual(run_file(latest_run(self.output, SEASON), "2025-gp-standings.json").read_text(),
                         (ACCEPTED / "standings.json").read_text())

    def test_malformed_row_leaves_out_its_tournament(self):
        group_table = MemberSystemClient.group_table

        def malformed(client, group_id):
            rows = group_table(client, group_id)
            return [{**row, "points": "n/a"} for row in rows] if group_id == compo_groups[0] else rows

        compo_groups = [group["id"] for root in reference_sources()[0].tournament("5382")["rootClasses"]
                        for group in root["groups"]]
        with mock.patch.object(MemberSystemClient, "group_table", malformed):
            run = self.publish_saved()
        report = self.report(run)
        self.assertNotIn("member:5382", report["included"])
        self.assertRegex(report["warnings"][0], r"^tournament 5382 \(Compo Cup 2025\): left out: Invalid result row")
        standings = json.loads(run_file(run, "2025-gp-standings.json").read_text())
        self.assertFalse(any("5382" in player["tournament_results"]
                             for players in standings.values() for player in players))

    def test_unreadable_rilton_section_leaves_out_rilton(self):
        u2200 = (RILTON_INPUTS / "rilton_u2200_2025_2026_1301930.TUNX").read_bytes()
        run = self.publish_saved(self.rilton_with_u2200(patched(u2200, pairing_offset(u2200, 0) + 4, 7)))
        report = self.report(run)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertRegex(report["warnings"][0],
                         r"^Rilton: left out: section 1301930 \(Rilton U2200\): Round 1, player \d+ "
                         r"against player \d+: unknown result code 7 \(byte \d+\)$")
        self.assertEqual([key for key in report["included"] if key.startswith("rilton:")], [])
        standings = json.loads(run_file(run, "2025-gp-standings.json").read_text())
        self.assertFalse(any("rilton" in player["tournament_results"]
                             for players in standings.values() for player in players))

    def test_unfinished_or_unsupported_rilton_section_fails(self):
        u2200 = (RILTON_INPUTS / "rilton_u2200_2025_2026_1301930.TUNX").read_bytes()
        cases = (
            (CONFIG_OFFSET_CURRENT_ROUND, 8, r"^Rilton: section 1301930 \(Rilton U2200\) has not finished: round 8 of 9$"),
            (CONFIG_OFFSET_TIEBREAKS, 52, r"^Rilton: section 1301930 \(Rilton U2200\): unsupported tie-break settings"),
        )
        for field, value, message in cases:
            with self.subTest(message):
                rilton = self.rilton_with_u2200(patched(u2200, config_offset(u2200, field), value))
                with self.assertRaisesRegex(GenerationError, message):
                    self.publish_saved(rilton)
                self.assert_previous_result_kept()

    def test_export_failure_keeps_previous_result(self):
        with mock.patch("senior_gp.generation.ExcelExporter.render", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(GenerationError, "^export: disk full"):
                self.publish_saved()
        self.assert_previous_result_kept()


if __name__ == "__main__":
    unittest.main()
