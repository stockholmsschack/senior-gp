"""Check the scoring rules in `_spec/senior-gp-scoring-rules.md` on small fixtures."""

from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from senior_gp.rating_fetcher.exceptions import ProcessingError
from senior_gp.rating_fetcher.processor import merge_duplicate_members
from senior_gp.results_processor import processor as results
from senior_gp.results_processor.models import TournamentNotFinishedError
from senior_gp.rilton_processor.exceptions import RiltonProcessorError
from senior_gp.rilton_processor.pooling import Section, pool_sections
from senior_gp.standings_generator.processor import StandingsProcessor


def rilton_record(member, elo, points, klass="D", tie_break=0.0):
    """Return a matched section record."""
    return {
        "fideid": member + 1000, "contenderId": member, "elo_rating": elo, "klass": klass,
        "tournament_data": {"Name": f"Player {member}", "Pts": points,
                            "BH/C1": tie_break, "BH": 0.0, "PS": 0.0},
    }


def member_result(member, points, klass="D"):
    """Return a member-system result record."""
    return {"contenderId": member, "name": f"Player {member}", "points": points,
            "secPoints": 0.0, "klass": klass}


class PoolingTests(unittest.TestCase):
    def test_penalty_is_below_floor_only(self):
        pooled = pool_sections([
            Section("U1800", [rilton_record(1, 0, 5)]),
            Section("U2200", [rilton_record(2, 1799, 5), rilton_record(3, 1800, 5)], 1800),
        ])
        self.assertEqual([r["penalty"] for r in pooled], [False, True, False])

    def test_missing_tie_break_is_unsupported(self):
        record = rilton_record(1, 1500, 5)
        del record["tournament_data"]["PS"]
        with self.assertRaisesRegex(RiltonProcessorError, "Unsupported section 'Open'.*PS"):
            pool_sections([Section("Open", [record])])

    def test_fide_id_in_two_sections_fails(self):
        with self.assertRaisesRegex(RiltonProcessorError, "FIDE ID 1001 appears in both"):
            pool_sections([Section("U1800", [rilton_record(1, 1500, 5)]),
                           Section("U2200", [rilton_record(1, 1500, 5)])])


class StandingsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        (self.root / "tournaments" / "2025").mkdir(parents=True)
        (self.root / "config").mkdir()

    def generate(self, tournaments, files):
        """Write fixture inputs and return standings by class."""
        (self.root / "config" / "tournaments.json").write_text(json.dumps({"tournaments": [
            {"id": tid, "name": tid, "season": 2025, "dm": dm} for tid, dm in tournaments
        ]}))
        for name, rows in files.items():
            (self.root / "tournaments" / "2025" / name).write_text(json.dumps(rows))
        return StandingsProcessor(2025).process_standings()

    def test_gp_and_dm_allocation(self):
        rows = [member_result(i, 20 - i) for i in range(1, 18)]
        standings = self.generate([("1", False), ("2", True)],
                                  {"20250101-1.json": rows, "20250102-2.json": rows})
        player = standings["D"]
        self.assertEqual([player[i].tournament_results["1"].standings_points for i in (1, 10, 11)], [10, 1, 0])
        self.assertEqual([player[i].tournament_results["2"].standings_points for i in (1, 15, 16)], [15, 1, 0])

    def test_penalized_zero_differs_from_natural_zero(self):
        rows = [{**rilton_record(i, 1500, 20 - i), "penalty": i == 1} for i in range(1, 13)]
        standings = self.generate([], {"rilton-2025.json": rows})["D"]
        penalized, second, natural = (standings[i].tournament_results["rilton"] for i in (1, 2, 11))
        self.assertEqual((penalized.rank, penalized.standings_points), (1, -1))
        self.assertEqual(second.standings_points, 9)  # place 1's points go to nobody
        self.assertEqual(natural.standings_points, 0)
        self.assertEqual((standings[1].total_standings_points, standings[11].total_standings_points), (0, 0))

    def test_fewer_scoring_events_breaks_ties_then_shared_rank(self):
        # Players 1 and 100 reach 10 in one event; players 2-4 need two
        # (second event places 8-10 add 3, 2, 1 to first event's 7, 8, 9).
        first = [member_result(m, 10 - m) for m in (1, 2, 3, 4)]
        second = [member_result(100 + i, 20 - i) for i in range(7)]
        second += [member_result(m, 10 - i) for i, m in enumerate((4, 3, 2))]
        standings = self.generate([("1", False), ("2", False)],
                                  {"20250101-1.json": first, "20250102-2.json": second})["D"]
        self.assertEqual({standings[m].total_standings_points for m in (1, 2, 3, 4, 100)}, {10})
        self.assertEqual([standings[m].final_rank for m in (1, 100, 2, 3, 4)], [1, 1, 3, 3, 3])


class MembershipTests(unittest.TestCase):
    def test_duplicate_prefers_record_with_standard_elo(self):
        merged = merge_duplicate_members([
            {"id": 7, "elo": {}}, {"id": 7, "elo": {"rating": 1490}}, {"id": 8, "elo": None},
        ])
        self.assertEqual([(p["id"], p["elo"]) for p in merged], [(7, {"rating": 1490}), (8, None)])

    def test_conflicting_duplicate_fails(self):
        with self.assertRaisesRegex(ProcessingError, "Member 7"):
            merge_duplicate_members([{"id": 7, "elo": {"rating": 1490}}, {"id": 7, "elo": {"rating": 1500}}])


class IncompleteEventTests(unittest.TestCase):
    def run_on(self, start, end):
        """Process a tournament on 22 March 2025 and return its result."""
        processor = results.ResultsProcessor.__new__(results.ResultsProcessor)
        frozen = mock.Mock(wraps=datetime)
        frozen.now.return_value = datetime(2025, 3, 22)
        frozen.strptime = datetime.strptime
        with mock.patch.object(results, "datetime", frozen):
            return processor.process_tournament_results(
                {"id": 1, "name": "Cup", "start": start, "end": end, "rootClasses": []}, {})

    def test_running_tournament_fails(self):
        with self.assertRaisesRegex(TournamentNotFinishedError, "has not finished"):
            self.run_on("2025-03-21", "2025-03-23")

    def test_future_tournament_is_skipped(self):
        with mock.patch.object(results.ResultsProcessor, "fetch_group_results") as fetch:
            self.assertIsNone(self.run_on("2025-04-01", "2025-04-02"))
        fetch.assert_not_called()
